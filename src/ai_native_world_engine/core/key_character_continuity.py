"""Generalized key-character continuity and influence-circle pressure."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from math import ceil, hypot
from typing import Any

from .events import json_copy
from .feedback import WorldEffect, effect
from .pressure_grounding import rule_pressure_is_groundable
from .rule_registry import canonical_rule_name
from .world import World, WorldNode


JsonDict = dict[str, Any]

KEY_CHARACTER_MAX_ACTIVE = 5
KEY_CHARACTER_ACTIVE_THRESHOLD = 3.0
INFLUENCE_CIRCLE_LIMIT = 8
KEY_CHARACTER_INFLUENCE_MIN_WEIGHT = 0.2
KEY_CHARACTER_INFLUENCE_MAX_WEIGHT = 0.9
KEY_CHARACTER_INFLUENCE_BUBBLE_MAX = 6
KEY_CHARACTER_THOUGHT_SLICE_MIN_COUNT = 5
KEY_CHARACTER_THOUGHT_SLICE_COUNT = 6
KEY_CHARACTER_THOUGHT_SLICE_MIN_CHARS = 6
KEY_CHARACTER_BUBBLE_TTL = 4.0
KEY_CHARACTER_BUBBLE_GAP = 3.0


@dataclass(slots=True)
class KeyCharacterContinuityResult:
    effects: list[WorldEffect]
    active_character_ids: list[str] = field(default_factory=list)
    dormant_character_ids: list[str] = field(default_factory=list)
    influence_node_ids: list[str] = field(default_factory=list)

    def to_metadata(self) -> JsonDict:
        return {
            "active_character_count": len(self.active_character_ids),
            "active_character_ids": list(self.active_character_ids),
            "dormant_character_count": len(self.dormant_character_ids),
            "dormant_character_ids": list(self.dormant_character_ids),
            "influence_node_count": len(self.influence_node_ids),
            "influence_node_ids": list(self.influence_node_ids),
        }


class KeyCharacterContinuityApplier:
    def build_effects(
        self,
        world: World,
        source: str = "key-character-continuity",
        grounded_rule: str = "move",
        target_node_ids: list[str] | None = None,
    ) -> KeyCharacterContinuityResult:
        scored = [
            (self.salience_report(world, node), node)
            for node in _key_character_nodes(world)
        ]
        scored.sort(key=lambda item: (-float(item[0]["score"]), item[1].id))
        active_ids = {
            node.id
            for report, node in scored[:KEY_CHARACTER_MAX_ACTIVE]
            if float(report["score"]) >= KEY_CHARACTER_ACTIVE_THRESHOLD
        }

        target_set = {str(node_id) for node_id in (target_node_ids or [])}
        scoped_scored = [
            item for item in scored if not target_set or item[1].id in target_set
        ]
        effects: list[WorldEffect] = []
        influence_node_ids: list[str] = []
        key_nodes = [node for _, node in scored]
        for index, (report, node) in enumerate(scoped_scored):
            status = "active" if node.id in active_ids else "dormant"
            peer = _next_peer(node, key_nodes)
            influence_circle = _influence_circle(world, node, INFLUENCE_CIRCLE_LIMIT)
            influence_node_ids.extend(item["node_id"] for item in influence_circle)
            state = _continuity_state(
                world, node, report, status, peer, influence_circle, grounded_rule
            )
            effects.append(
                effect("key_character_state", target=f"node:{node.id}", value=state)
            )
            effects.append(
                effect(
                    "memory_add",
                    target=f"node:{node.id}",
                    text=f"continuity update: {state['goal']} / {state['current_step']}",
                    source=source,
                    importance=0.7 if status == "active" else 0.35,
                )
            )
            if status == "active":
                effects.extend(_lifecycle_effects(node, state, source))
                effects.extend(
                    _active_character_effects(world, node, state, source, index)
                )
                effects.extend(
                    _influence_effects(world, node, state, influence_circle, source)
                )

        dormant_ids = [
            node.id for _, node in scoped_scored if node.id not in active_ids
        ]
        return KeyCharacterContinuityResult(
            effects=effects,
            active_character_ids=[
                node.id for _, node in scoped_scored if node.id in active_ids
            ],
            dormant_character_ids=dormant_ids,
            influence_node_ids=_unique(influence_node_ids),
        )

    def salience_report(self, world: World, node: WorldNode) -> JsonDict:
        reasons: list[str] = []
        score = 0.0
        if (
            node.key_character.get("public_figure")
            or node.attributes.get("agent_layer") == "key_character"
        ):
            score += 2.4
            reasons.append("key_character_marker")
        if node.attributes.get("identity") or node.key_character.get("identity"):
            score += 0.6
            reasons.append("identity_anchor")

        degree = sum(
            1
            for edge in world.relationships.values()
            if edge.source == node.id or edge.target == node.id
        )
        if degree:
            score += min(degree * 0.25, 2.0)
            reasons.append("relationship_degree")
        if node.memories:
            score += min(len(node.memories) * 0.18, 1.0)
            reasons.append("memory_continuity")
        if node.rule_pressures:
            score += min(len(node.rule_pressures) * 0.35, 1.4)
            reasons.append("grounded_pressure")

        mentions = _recent_mentions(world, node.id)
        if mentions:
            score += min(mentions * 0.3, 1.2)
            reasons.append("recent_feedback_mentions")
        influence_count = len(_influence_circle(world, node, INFLUENCE_CIRCLE_LIMIT))
        if influence_count:
            score += min(influence_count * 0.08, 0.8)
            reasons.append("influence_circle")

        return {"score": round(score, 3), "reasons": reasons}


def apply_key_character_model_output(
    world: World,
    target_node_id: str,
    raw: JsonDict,
    source: str,
    allowed_rule_names: set[str] | None = None,
    grounded_pressure: JsonDict | None = None,
    require_grounded_pressure: bool = False,
) -> KeyCharacterContinuityResult:
    """Convert one live-model protagonist result into continuity effects."""

    if not world.has_node(target_node_id):
        raise ValueError(
            f"key-character provider referenced missing node: {target_node_id}"
        )
    node = world.node(target_node_id)
    if (
        node.type != "key_character"
        and node.key_character.get("agent_layer") != "key_character"
    ):
        raise ValueError(
            f"key-character provider target is not a key character: {target_node_id}"
        )
    payload = (
        raw.get("key_character") if isinstance(raw.get("key_character"), dict) else raw
    )
    if not isinstance(payload, dict):
        raise ValueError("key-character provider output must be a JSON object")
    emitted_id = str(
        payload.get("character_id", payload.get("node_id", payload.get("id", "")))
    ).strip()
    if emitted_id and emitted_id != target_node_id:
        raise ValueError(
            f"key-character provider returned {emitted_id}, expected {target_node_id}"
        )

    existing = json_copy(node.key_character)
    report = KeyCharacterContinuityApplier().salience_report(world, node)
    insight = str(
        payload.get("insight")
        or payload.get("visible_thought")
        or payload.get("thought")
        or raw.get("summary")
        or existing.get("self_narrative")
        or f"我正在重新确认 {node.name} 的下一步。"
    ).strip()
    personality_profile = payload.get("personality_profile")
    if personality_profile is not None and not isinstance(personality_profile, dict):
        raise ValueError("key-character personality_profile must be an object")
    plan_steps = _dict_list_or_strings(payload.get("plan_steps")) or _list(
        existing.get("plan_steps")
    )
    current_step = str(
        payload.get("current_step") or payload.get("plan_step") or ""
    ).strip()
    if not current_step and plan_steps:
        first_step = plan_steps[0]
        current_step = (
            str(first_step.get("text", ""))
            if isinstance(first_step, dict)
            else str(first_step)
        )
    if not current_step:
        current_step = str(
            existing.get("current_step") or "将当前判断转化为可验证的下一步"
        )
    grounded_rule = canonical_rule_name(
        str(
            (grounded_pressure or {}).get("rule")
            or payload.get("grounded_rule")
            or existing.get("grounded_rule")
            or "movement"
        )
    )
    canonical_allowed_rules = {
        canonical_rule_name(name) for name in (allowed_rule_names or set())
    }
    if (
        canonical_allowed_rules
        and grounded_rule
        and grounded_rule not in canonical_allowed_rules
        and grounded_pressure is None
    ):
        raise ValueError(
            f"key-character provider referenced unregistered rule: {grounded_rule}"
        )
    influence_circle = _influence_circle(world, node, INFLUENCE_CIRCLE_LIMIT)
    pressure_payload = json_copy(grounded_pressure or {})
    previous_initiative = json_copy(existing.get("current_initiative", {}))
    initiative_generation = int(existing.get("initiative_generation", 0) or 0) + 1
    initiative = _normalize_model_initiative(
        world,
        node,
        payload,
        pressure_payload,
        influence_circle,
        initiative_generation,
    )
    progress_delta = str(payload.get("progress_delta") or current_step).strip()
    action_assessment = json_copy(
        payload.get("previous_action_assessment", {})
        if isinstance(payload.get("previous_action_assessment"), dict)
        else {}
    )
    state = {
        **existing,
        "agent_layer": "key_character",
        "status": "active",
        "salience_score": report["score"],
        "salience_reasons": report["reasons"],
        "self_narrative": str(
            payload.get("self_narrative") or existing.get("self_narrative") or insight
        ),
        "personality_profile": json_copy(personality_profile)
        if isinstance(personality_profile, dict)
        else json_copy(existing.get("personality_profile", {})),
        "goal_status": str(
            payload.get("goal_status") or existing.get("goal_status") or "continue"
        ),
        "goal": str(
            payload.get("goal")
            or existing.get("goal")
            or f"推进 {node.name} 的长期目标"
        ),
        "plan_reason": str(
            payload.get("plan_reason") or existing.get("plan_reason") or insight
        ),
        "plan_steps": json_copy(plan_steps),
        "current_step": current_step,
        "grounded_rule": grounded_rule,
        "selected_action_option_id": str(
            (grounded_pressure or {}).get("option_id", "")
        ),
        "peer_interactions": _dict_list(payload.get("peer_interactions"))
        or _list(existing.get("peer_interactions")),
        "commitments": _dict_list(payload.get("commitments"))
        or _list(existing.get("commitments")),
        "influence_circle": influence_circle,
        "influence_circle_count": len(influence_circle),
        "last_model_insight": insight,
        "previous_initiative": previous_initiative,
        "current_initiative": initiative,
        "initiative_generation": initiative_generation,
        "last_action_assessment": action_assessment,
        "last_progress_delta": progress_delta,
        "initiative_changed": _initiative_signature(previous_initiative)
        != _initiative_signature(initiative),
        "progress_changed": _normalized_text(existing.get("last_progress_delta", ""))
        != _normalized_text(progress_delta),
    }
    effects = [
        effect("key_character_state", target=f"node:{node.id}", value=state),
        effect(
            "memory_add",
            target=f"node:{node.id}",
            text=f"key-character insight: {insight}",
            source=source,
            importance=0.76,
        ),
        effect(
            "memory_add",
            target=f"node:{node.id}",
            text=(
                f"key-character initiative {initiative['initiative_id']}: "
                f"{initiative['action']}"
            ),
            source=source,
            importance=0.9,
            metadata={
                "initiative_id": initiative["initiative_id"],
                "initiative_generation": initiative_generation,
                "progress_delta": progress_delta,
                "propagation_goal": initiative["propagation_goal"],
                "origin": "key_character_initiative",
            },
        ),
    ]
    thought_segments = _split_key_thought(insight, node.id, source)
    for sequence_index, text in enumerate(thought_segments):
        effects.append(
            effect(
                "thought_bubble_add",
                target=f"node:{node.id}",
                text=text,
                source=source,
                salience=0.84,
                ttl=KEY_CHARACTER_BUBBLE_TTL,
                delay=round(
                    _key_bubble_base_delay(node.id, source)
                    + sequence_index * _key_bubble_interval(node.id, source),
                    3,
                ),
                origin="key_character_continuity",
                sequence_index=sequence_index,
                sequence_total=len(thought_segments),
            )
        )
    if (
        grounded_rule
        and (grounded_pressure is not None or not require_grounded_pressure)
        and rule_pressure_is_groundable(
            world,
            node.id,
            grounded_rule,
            pressure_payload or None,
        )
    ):
        extra = {
            key: json_copy(value)
            for key, value in pressure_payload.items()
            if key not in {"rule", "weight", "ttl", "reason", "target", "type"}
        }
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{node.id}",
                rule=grounded_rule,
                weight=max(
                    0.0,
                    min(
                        float(
                            pressure_payload.get(
                                "weight", payload.get("rule_weight", 0.52)
                            )
                            or 0.52
                        ),
                        1.0,
                    ),
                ),
                ttl=max(
                    2,
                    min(
                        int(
                            pressure_payload.get("ttl", payload.get("rule_ttl", 4)) or 4
                        ),
                        7,
                    ),
                ),
                source=source,
                reason=str(
                    pressure_payload.get("reason")
                    or payload.get("rule_reason")
                    or current_step
                )[:160],
                origin="key_character_plan",
                **extra,
            )
        )
    effects.extend(
        _influence_effects(
            world,
            node,
            state,
            influence_circle,
            source,
            allowed_rule_names=allowed_rule_names,
            grounded_pressure=pressure_payload,
        )
    )
    return KeyCharacterContinuityResult(
        effects=effects,
        active_character_ids=[node.id],
        dormant_character_ids=[],
        influence_node_ids=_unique([item["node_id"] for item in influence_circle]),
    )


def _normalize_model_initiative(
    world: World,
    node: WorldNode,
    payload: JsonDict,
    pressure_payload: JsonDict,
    influence_circle: list[JsonDict],
    generation: int,
) -> JsonDict:
    raw = payload.get("initiative")
    initiative = json_copy(raw) if isinstance(raw, dict) else {}
    allowed_targets = {
        str(item.get("node_id", ""))
        for item in influence_circle
        if str(item.get("node_id", ""))
    }
    allowed_targets.update(
        item.id for item in _key_character_nodes(world) if item.id != node.id
    )
    target_node_ids = _unique(
        [
            str(node_id)
            for node_id in _list(initiative.get("target_node_ids"))
            if str(node_id) in allowed_targets and world.has_node(str(node_id))
        ]
    )[:5]
    if not target_node_ids:
        target_node_ids = [
            str(item.get("node_id", ""))
            for item in influence_circle[:1]
            if str(item.get("node_id", ""))
        ]
    action = str(
        initiative.get("action")
        or payload.get("current_step")
        or "advance the current grounded plan"
    ).strip()
    expected_change = str(
        initiative.get("expected_change") or payload.get("progress_delta") or action
    ).strip()
    propagation_goal = str(
        initiative.get("propagation_goal")
        or "invite the influence circle to evaluate and carry the initiative"
    ).strip()
    source_tick = int(pressure_payload.get("source_tick", world.tick) or world.tick)
    option_id = str(
        pressure_payload.get("option_id")
        or payload.get("selected_action_option_id", "")
    )
    seed = (
        f"{node.id}:{source_tick}:{generation}:{option_id}:{_normalized_text(action)}"
    )
    return {
        "initiative_id": f"initiative-{sha256(seed.encode('utf-8')).hexdigest()[:20]}",
        "generation": int(generation),
        "source_tick": source_tick,
        "action": action[:240],
        "target_node_ids": target_node_ids,
        "expected_change": expected_change[:240],
        "propagation_goal": propagation_goal[:240],
        "impact_scale": max(
            0.0,
            min(float(initiative.get("impact_scale", 0.65) or 0.65), 1.0),
        ),
        "selected_action_option_id": option_id,
    }


def _initiative_signature(value: Any) -> str:
    initiative = value if isinstance(value, dict) else {}
    parts = [
        initiative.get("action", ""),
        initiative.get("expected_change", ""),
        initiative.get("propagation_goal", ""),
        *(_list(initiative.get("target_node_ids"))),
    ]
    return "|".join(_normalized_text(part) for part in parts)


def _normalized_text(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _continuity_state(
    world: World,
    node: WorldNode,
    report: JsonDict,
    status: str,
    peer: WorldNode | None,
    influence_circle: list[JsonDict],
    grounded_rule: str,
) -> JsonDict:
    existing = json_copy(node.key_character)
    identity = str(
        node.attributes.get("identity") or existing.get("identity") or node.type
    )
    thought_seed = str(
        existing.get("thought_seed") or f"{node.name} is forming a public stance."
    )
    plan_steps = _list(existing.get("plan_steps")) or [
        f"Read the current {identity} context",
        "Convert the stance into a grounded next step",
        "Let the influence circle respond through weak pressure",
    ]
    current_step = str(plan_steps[int(world.tick) % len(plan_steps)])
    peer_interactions = _list(existing.get("peer_interactions"))
    commitments = _list(existing.get("commitments"))
    peer_interactions, commitments, lifecycle_changes = _refresh_lifecycle(
        world, node, peer_interactions, commitments
    )
    if peer is not None:
        peer_interactions = [
            {
                "target": peer.id,
                "status": "pending",
                "stance": "observe",
                "summary": f"{node.name} is comparing plans with {peer.name}.",
                "created_tick": world.tick,
                "reason": "deterministic continuity baseline",
            },
            *peer_interactions,
        ][:8]
        commitments = [
            {
                "target": peer.id,
                "status": "pending",
                "summary": f"Keep {identity} plan legible to {peer.name}.",
                "created_tick": world.tick,
                "reason": current_step,
            },
            *commitments,
        ][:8]

    value = {
        "agent_layer": "key_character",
        "status": status,
        "salience_score": report["score"],
        "salience_reasons": report["reasons"],
        "personality_profile": existing.get("personality_profile")
        or {
            "identity": identity,
            "stance": thought_seed,
            "operating_principle": "turn public context into auditable structured pressure",
        },
        "self_narrative": existing.get("self_narrative") or thought_seed,
        "goal": existing.get("goal")
        or f"Advance a coherent {identity} contribution without overriding the rule engine.",
        "plan_steps": plan_steps,
        "current_step": current_step,
        "grounded_rule": existing.get("grounded_rule") or grounded_rule,
        "peer_interactions": peer_interactions,
        "commitments": commitments,
        "lifecycle_changes": lifecycle_changes,
        "influence_circle": influence_circle,
        "influence_circle_count": len(influence_circle),
    }
    existing.update(value)
    return existing


def _refresh_lifecycle(
    world: World,
    node: WorldNode,
    peer_interactions: list[JsonDict],
    commitments: list[JsonDict],
) -> tuple[list[JsonDict], list[JsonDict], list[JsonDict]]:
    changes: list[JsonDict] = []
    next_commitments = []
    for item in commitments:
        current = json_copy(item)
        status = str(current.get("status", "pending"))
        target_id = str(current.get("target", ""))
        if status == "pending" and _grounded_feedback_between(
            world, node.id, target_id
        ):
            current.update(
                {
                    "status": "resolved",
                    "resolution_tick": world.tick,
                    "status_reason": "matching grounded action feedback",
                }
            )
            changes.append(
                {
                    "kind": "commitment",
                    "target": target_id,
                    "status": "resolved",
                    "summary": current.get("summary", ""),
                }
            )
        elif (
            status == "pending"
            and world.tick - int(current.get("created_tick", world.tick) or world.tick)
            >= 3
        ):
            current.update(
                {
                    "status": "overdue",
                    "last_checked_tick": world.tick,
                    "status_reason": "commitment aged without matching action",
                }
            )
            changes.append(
                {
                    "kind": "commitment",
                    "target": target_id,
                    "status": "overdue",
                    "summary": current.get("summary", ""),
                }
            )
        next_commitments.append(current)

    next_interactions = []
    for item in peer_interactions:
        current = json_copy(item)
        status = str(current.get("status", "pending"))
        stance = str(current.get("stance", "observe"))
        target_id = str(current.get("target", ""))
        if status in {"pending", "unresolved"} and _grounded_feedback_between(
            world, node.id, target_id
        ):
            next_status = (
                "reconciled"
                if stance in {"conflict", "misunderstanding", "resentment"}
                else "resolved"
            )
            current.update(
                {
                    "status": next_status,
                    "resolution_tick": world.tick,
                    "status_reason": "grounded interaction feedback",
                }
            )
            changes.append(
                {
                    "kind": "peer_interaction",
                    "target": target_id,
                    "status": next_status,
                    "summary": current.get("summary", ""),
                }
            )
        elif (
            status in {"pending", "unresolved"}
            and world.tick - int(current.get("created_tick", world.tick) or world.tick)
            >= 3
        ):
            next_status = (
                "stale"
                if stance in {"conflict", "misunderstanding", "resentment"}
                else "overdue"
            )
            current.update(
                {
                    "status": next_status,
                    "last_checked_tick": world.tick,
                    "status_reason": "interaction aged without feedback",
                }
            )
            changes.append(
                {
                    "kind": "peer_interaction",
                    "target": target_id,
                    "status": next_status,
                    "summary": current.get("summary", ""),
                }
            )
        next_interactions.append(current)
    return next_interactions[:8], next_commitments[:8], changes[:8]


def _lifecycle_effects(
    node: WorldNode, state: JsonDict, source: str
) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    for index, change in enumerate(_list(state.get("lifecycle_changes"))):
        status = str(change.get("status", ""))
        target_id = str(change.get("target", ""))
        summary = str(change.get("summary", "lifecycle changed"))
        effects.append(
            effect(
                "memory_add",
                target=f"node:{node.id}",
                text=f"key-character lifecycle {status}: {summary}",
                source=source,
                importance=0.66,
            )
        )
        effects.append(
            effect(
                "thought_bubble_add",
                target=f"node:{node.id}",
                text=f"关系承诺状态变成 {status}：{summary}",
                source=source,
                salience=0.76,
                ttl=4.0,
                delay=round(0.4 + index * 0.6, 3),
                origin="key_character_lifecycle",
                lifecycle_status=status,
                lifecycle_kind=change.get("kind", ""),
                lifecycle_target=target_id,
            )
        )
        if target_id and status in {"resolved", "reconciled"}:
            effects.append(
                effect(
                    "relationship_delta",
                    source=f"node:{node.id}",
                    target=f"node:{target_id}",
                    relation="trust",
                    delta=0.05,
                    ttl=12,
                    source_label=source,
                    reason=f"key-character lifecycle {status}",
                    origin="key_character_lifecycle",
                )
            )
    return effects


def _active_character_effects(
    world: World, node: WorldNode, state: JsonDict, source: str, index: int
) -> list[WorldEffect]:
    weight = min(0.85, 0.42 + float(state["salience_score"]) * 0.04)
    effects: list[WorldEffect] = []
    thought = f"我正在把目标推进成下一步：{state['current_step']}"
    thought_segments = _split_key_thought(thought, node.id, source)
    for sequence_index, text in enumerate(thought_segments):
        effects.append(
            effect(
                "thought_bubble_add",
                target=f"node:{node.id}",
                text=text,
                source=source,
                salience=0.82,
                ttl=KEY_CHARACTER_BUBBLE_TTL,
                delay=round(
                    _key_bubble_base_delay(node.id, source)
                    + sequence_index * _key_bubble_interval(node.id, source),
                    3,
                ),
                origin="key_character_continuity",
                sequence_index=sequence_index,
                sequence_total=len(thought_segments),
            )
        )
    grounded_rule = str(state["grounded_rule"])
    if rule_pressure_is_groundable(world, node.id, grounded_rule):
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{node.id}",
                rule=grounded_rule,
                weight=round(weight, 4),
                ttl=4,
                source=source,
                reason=str(state["current_step"]),
                origin="key_character_plan",
            )
        )
    return effects


def _influence_effects(
    world: World,
    node: WorldNode,
    state: JsonDict,
    influence_circle: list[JsonDict],
    source: str,
    *,
    allowed_rule_names: set[str] | None = None,
    grounded_pressure: JsonDict | None = None,
) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    initiative = json_copy(state.get("current_initiative", {}))
    if not initiative:
        seed = f"{node.id}:{world.tick}:{state.get('current_step', '')}"
        initiative = {
            "initiative_id": f"initiative-{sha256(seed.encode('utf-8')).hexdigest()[:20]}",
            "generation": int(state.get("initiative_generation", 0) or 0),
            "source_tick": world.tick,
            "action": str(state.get("current_step", "advance the current plan")),
            "target_node_ids": [],
            "expected_change": str(
                state.get("current_step", "advance the current plan")
            ),
            "propagation_goal": "invite the influence circle to respond",
            "impact_scale": 0.55,
        }
    named_targets = [
        str(node_id)
        for node_id in _list(initiative.get("target_node_ids"))
        if str(node_id)
    ]
    indexed_circle = list(enumerate(influence_circle))
    ranked_circle = [
        item
        for _, item in sorted(
            indexed_circle,
            key=lambda entry: (
                named_targets.index(str(entry[1].get("node_id", "")))
                if str(entry[1].get("node_id", "")) in named_targets
                else len(named_targets),
                entry[0],
            ),
        )
    ]
    preferred_rule = canonical_rule_name(
        str((grounded_pressure or {}).get("rule") or state.get("grounded_rule", ""))
    )
    enabled_rules = set()
    if allowed_rule_names is None or grounded_pressure is not None:
        enabled_rules = {
            canonical_rule_name(rule_name)
            for rule_name in (allowed_rule_names or {preferred_rule})
            if canonical_rule_name(rule_name)
        }
    source_weight = max(
        0.0,
        min(float((grounded_pressure or {}).get("weight", 0.5) or 0.5), 1.0),
    )
    source_ttl = max(
        2,
        min(int((grounded_pressure or {}).get("ttl", 4) or 4), 7),
    )
    impact_scale = max(
        0.0,
        min(float(initiative.get("impact_scale", 0.65) or 0.65), 1.0),
    )
    salience_factor = max(
        0.0,
        min(float(state.get("salience_score", 0.0) or 0.0) / 6.0, 1.0),
    )
    initiative_id = str(initiative.get("initiative_id", ""))
    for circle_index, target in enumerate(ranked_circle):
        node_id = str(target["node_id"])
        is_named_target = node_id in named_targets
        effects.append(
            effect(
                "memory_add",
                target=f"node:{node_id}",
                text=(
                    f"influenced by {node.name} initiative {initiative_id}: "
                    f"{initiative.get('action', state.get('current_step', ''))}"
                ),
                source=source,
                importance=min(0.95, 0.62 + impact_scale * 0.25),
                metadata={
                    "origin": "key_character_influence",
                    "influenced_by": node.id,
                    "initiative_id": initiative_id,
                    "propagation_depth": 1,
                    "propagation_goal": str(initiative.get("propagation_goal", "")),
                    "expected_change": str(initiative.get("expected_change", "")),
                    "named_target": is_named_target,
                },
            )
        )
        if circle_index < KEY_CHARACTER_INFLUENCE_BUBBLE_MAX:
            influence_delay = _key_influence_delay(node.id, node_id, circle_index)
            effects.append(
                effect(
                    "thought_bubble_add",
                    target=f"node:{node_id}",
                    text=f"受到 {node.name} 的计划影响：{state['current_step']}",
                    source=source,
                    salience=0.46,
                    ttl=4.0,
                    delay=influence_delay,
                    origin="key_character_influence",
                    influenced_by=node.id,
                    initiative_id=initiative_id,
                    propagation_depth=1,
                )
            )
        propagation_rule = _influence_rule_for_target(
            world,
            node_id,
            preferred_rule,
            enabled_rules,
        )
        if propagation_rule:
            rank_decay = max(0.55, 1.0 - circle_index * 0.06)
            named_boost = 1.12 if is_named_target else 1.0
            influence_weight = (
                source_weight
                * (0.5 + impact_scale * 0.25 + salience_factor * 0.15)
                * rank_decay
                * named_boost
            )
            influence_weight = max(
                KEY_CHARACTER_INFLUENCE_MIN_WEIGHT,
                min(influence_weight, KEY_CHARACTER_INFLUENCE_MAX_WEIGHT),
            )
            pressure_seed = f"{initiative_id}:{node_id}:1:{propagation_rule}"
            effects.append(
                effect(
                    "rule_pressure_add",
                    target=f"node:{node_id}",
                    rule=propagation_rule,
                    weight=round(influence_weight, 4),
                    ttl=max(3, source_ttl),
                    source=source,
                    reason=str(
                        initiative.get("propagation_goal")
                        or f"influence from {node.id}"
                    )[:160],
                    origin="key_character_influence",
                    influenced_by=node.id,
                    initiative_id=initiative_id,
                    propagation_depth=1,
                    propagation_goal=str(initiative.get("propagation_goal", ""))[:240],
                    pressure_id=(
                        f"pressure-{sha256(pressure_seed.encode('utf-8')).hexdigest()[:20]}"
                    ),
                    source_tick=int(
                        initiative.get("source_tick", world.tick) or world.tick
                    ),
                    observation_deadline_tick=world.tick + max(3, source_ttl),
                )
            )
    return effects


def _influence_rule_for_target(
    world: World,
    node_id: str,
    preferred_rule: str,
    enabled_rules: set[str],
) -> str:
    ordered = [
        preferred_rule,
        "collaboration",
        "social_spread",
        "organization_decision",
        "science_publish",
        "movement",
    ]
    for rule in _unique([canonical_rule_name(value) for value in ordered]):
        if not rule or rule not in enabled_rules:
            continue
        if rule_pressure_is_groundable(world, node_id, rule):
            return rule
    return ""


def _split_key_thought(text: str, node_id: str, source: str) -> list[str]:
    clean = " ".join(str(text).split())
    if not clean:
        clean = "我需要继续观察，再把计划落到规则里。"
    if len(clean) <= KEY_CHARACTER_THOUGHT_SLICE_MIN_CHARS:
        return [clean]
    target_count = KEY_CHARACTER_THOUGHT_SLICE_MIN_COUNT
    if _hash_fraction(f"{source}:{node_id}:count") >= 0.5:
        target_count = KEY_CHARACTER_THOUGHT_SLICE_COUNT
    target_count = min(
        target_count,
        max(1, ceil(len(clean) / KEY_CHARACTER_THOUGHT_SLICE_MIN_CHARS)),
    )
    step = ceil(len(clean) / target_count)
    segments: list[str] = []
    cursor = 0
    for index in range(target_count):
        if index == target_count - 1:
            segment = clean[cursor:]
        else:
            segment = clean[cursor : cursor + step]
        segments.append(segment.strip() or clean)
        cursor += len(segment)
    return segments


def _key_bubble_interval(node_id: str, source: str) -> float:
    gap = (
        KEY_CHARACTER_BUBBLE_GAP + _hash_fraction(f"{source}:{node_id}:gap") * 1.6 - 0.8
    )
    return max(KEY_CHARACTER_BUBBLE_TTL + 1.0, KEY_CHARACTER_BUBBLE_TTL + gap)


def _key_bubble_base_delay(node_id: str, source: str) -> float:
    return _hash_fraction(f"{source}:{node_id}:start") * 10.0


def _key_influence_delay(node_id: str, target_id: str, response_index: int) -> float:
    influence_source = f"boss_follow:{node_id}"
    jitter = _hash_fraction(f"{influence_source}:{target_id}:follower") * 2.4
    return round(2.0 + response_index * 5.6 + jitter, 3)


def _hash_fraction(text: str) -> float:
    hash_value = 5381
    for character in text:
        hash_value = ((hash_value << 5) + hash_value + ord(character)) & 0xFFFFFFFF
    return (hash_value % 1000) / 1000


def _key_character_nodes(world: World) -> list[WorldNode]:
    return [
        node
        for node in world.nodes.values()
        if node.type == "key_character"
        or node.key_character.get("agent_layer") == "key_character"
    ]


def _next_peer(node: WorldNode, key_nodes: list[WorldNode]) -> WorldNode | None:
    if len(key_nodes) <= 1:
        return None
    ordered = sorted(key_nodes, key=lambda item: item.id)
    index = ordered.index(node)
    return ordered[(index + 1) % len(ordered)]


def _influence_circle(world: World, node: WorldNode, limit: int) -> list[JsonDict]:
    related_country_ids = {
        edge.target if edge.source == node.id else edge.source
        for edge in world.relationships.values()
        if (edge.source == node.id or edge.target == node.id)
    }
    related_org_ids = {
        edge.source
        for edge in world.relationships.values()
        if edge.type == "operates_in" and edge.target in related_country_ids
    }
    candidates: list[WorldNode] = [
        item
        for item in world.nodes.values()
        if item.attributes.get("agent_layer") == "relationship_network_member"
        and str(item.attributes.get("parent_network", "")) in related_org_ids
    ]
    if not candidates:
        candidates = [
            item
            for item in world.nodes.values()
            if item.attributes.get("agent_layer") == "relationship_network_member"
        ]
    candidates.sort(
        key=lambda item: (
            hypot(item.position.x - node.position.x, item.position.y - node.position.y),
            item.id,
        )
    )
    return [
        {
            "node_id": item.id,
            "role": item.attributes.get("role", item.type),
            "parent_network": item.attributes.get("parent_network", ""),
        }
        for item in candidates[:limit]
    ]


def _recent_mentions(world: World, node_id: str) -> int:
    mentions = 0
    for event in world.events.recent(64):
        payload = event.get("payload", {})
        if str(payload.get("actor_id", "")) == node_id:
            mentions += 1
            continue
        for raw_effect in payload.get("effects", []):
            if not isinstance(raw_effect, dict):
                continue
            if any(
                str(raw_effect.get(field, "")).endswith(node_id)
                for field in ("target", "source", "from", "to")
            ):
                mentions += 1
                break
    return mentions


def _grounded_feedback_between(world: World, source_id: str, target_id: str) -> bool:
    if not target_id:
        return False
    for event in world.events.recent(96):
        payload = event.get("payload", {})
        if event.get("kind") != "action_feedback":
            continue
        if payload.get("actor_type") == "agent":
            continue
        text = f"{payload.get('actor_id', '')} {payload.get('summary', '')} {payload.get('action', '')} {payload.get('targets', '')} {payload.get('effects', '')}"
        if source_id in text and target_id in text:
            return True
        if str(payload.get("actor_id", "")) == source_id and target_id in text:
            return True
    return False


def _list(value: Any) -> list[JsonDict]:
    return [json_copy(item) for item in value] if isinstance(value, list) else []


def _dict_list(value: Any) -> list[JsonDict]:
    return (
        [json_copy(item) for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _dict_list_or_strings(value: Any) -> list[Any]:
    return (
        [json_copy(item) for item in value if isinstance(item, (dict, str))]
        if isinstance(value, list)
        else []
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
