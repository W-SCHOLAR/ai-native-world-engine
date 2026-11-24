"""Time-sliced relationship-network output application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import json_copy
from .feedback import WorldEffect, effect
from .pressure_grounding import rule_pressure_is_groundable
from .thought_presentation import split_thought_for_presentation
from .world import World


JsonDict = dict[str, Any]

ACTIVE_NODE_LIMIT = 10
THOUGHT_SLICE_COUNT = 6
RIPPLE_TARGETS_PER_ACTIVE = 3
REQUIRED_RIPPLE_NODE_COUNT = ACTIVE_NODE_LIMIT * RIPPLE_TARGETS_PER_ACTIVE
PRIMARY_GRAPH_MIN_COVERAGE = ACTIVE_NODE_LIMIT + REQUIRED_RIPPLE_NODE_COUNT
RIPPLE_RULE_WEIGHT_FACTOR = 0.35
ACTIVE_BUBBLE_TTL = 4.0
ACTIVE_BUBBLE_INTERVAL_BASE = 10.0
ACTIVE_BUBBLE_GAP = 0.0
RIPPLE_BUBBLE_TTL = 6.0
RIPPLE_BUBBLE_SALIENCE = 0.72

ALLOWED_EDGE_RELATIONS = {
    "care",
    "trust",
    "fear",
    "resentment",
    "hatred",
    "respect",
    "predator_pressure",
    "prey_opportunity",
    "resource_need",
    "claim",
    "scarcity",
    "danger",
    "route_memory",
    "settlement_pressure",
    "need",
    "surplus",
    "dependency",
    "trade_trust",
    "distrust",
    "competition",
    "loyalty",
    "obedience",
    "authority",
    "gratitude",
}


@dataclass(slots=True)
class RelationshipNodeUpdate:
    node_id: str
    thought: str
    action_tendencies: list[JsonDict] = field(default_factory=list)
    rule_mods: list[JsonDict] = field(default_factory=list)
    thought_bubbles: list[JsonDict] = field(default_factory=list)
    observe_only_reason: str = ""

    @classmethod
    def from_dict(cls, value: JsonDict) -> "RelationshipNodeUpdate":
        return cls(
            node_id=str(value.get("node_id", value.get("id", ""))),
            thought=str(value.get("thought", "")),
            action_tendencies=_dict_list(value.get("action_tendencies")),
            rule_mods=_dict_list(value.get("rule_mods")),
            thought_bubbles=_dict_list(value.get("thought_bubbles")),
            observe_only_reason=str(value.get("observe_only_reason", "")),
        )


@dataclass(slots=True)
class RelationshipRoundResult:
    effects: list[WorldEffect]
    active_node_ids: list[str]
    ripple_node_ids: list[str]
    ripple_targets_by_active: dict[str, list[str]] = field(default_factory=dict)
    edge_update_count: int = 0
    observe_only_node_ids: list[str] = field(default_factory=list)

    def to_metadata(self) -> JsonDict:
        return {
            "active_node_limit": ACTIVE_NODE_LIMIT,
            "active_node_count": len(self.active_node_ids),
            "active_node_ids": list(self.active_node_ids),
            "ripple_node_count": len(self.ripple_node_ids),
            "ripple_node_ids": list(self.ripple_node_ids),
            "ripple_targets_per_active": RIPPLE_TARGETS_PER_ACTIVE,
            "required_ripple_node_count": len(self.active_node_ids) * RIPPLE_TARGETS_PER_ACTIVE,
            "ripple_targets_by_active": json_copy(self.ripple_targets_by_active),
            "edge_update_count": self.edge_update_count,
            "observe_only_node_ids": list(self.observe_only_node_ids),
            "observe_only_node_count": len(self.observe_only_node_ids),
        }


class RelationshipRoundApplier:
    def build_effects(
        self,
        world: World,
        updates: list[RelationshipNodeUpdate | JsonDict],
        edge_updates: list[JsonDict] | None = None,
        source: str = "relationship-round",
        memory_prefix: str = "relationship thought",
        expected_node_ids: list[str] | None = None,
        propagation_node_ids: list[str] | None = None,
    ) -> RelationshipRoundResult:
        active_updates: list[RelationshipNodeUpdate] = []
        seen: set[str] = set()
        effects: list[WorldEffect] = []
        expected_set = {
            str(node_id)
            for node_id in (expected_node_ids or [])
            if world.has_node(str(node_id))
        }
        propagation_set = {
            str(node_id)
            for node_id in (propagation_node_ids or [])
            if world.has_node(str(node_id))
        }

        for raw_update in updates:
            update = raw_update if isinstance(raw_update, RelationshipNodeUpdate) else RelationshipNodeUpdate.from_dict(raw_update)
            node_id = update.node_id
            if (
                not node_id
                or node_id in seen
                or not world.has_node(node_id)
                or (expected_set and node_id not in expected_set)
            ):
                continue
            seen.add(node_id)
            active_updates.append(update)
            effects.extend(self._active_effects(world, update, source, memory_prefix, len(active_updates) - 1))
            if len(active_updates) >= ACTIVE_NODE_LIMIT:
                break

        ripple_targets_by_active = _ripple_assignments(
            world,
            active_updates,
            propagation_set,
            source,
            require_exact=propagation_node_ids is not None,
        )
        ripple_node_ids: list[str] = []
        for active_index, update in enumerate(active_updates):
            ripple_targets = ripple_targets_by_active.get(update.node_id, [])
            effects.append(
                self._thought_schedule_effect(
                    update,
                    source,
                    active_index,
                    ripple_targets,
                )
            )
            for ripple_index, target_id in enumerate(ripple_targets):
                ripple_node_ids.append(target_id)
                effects.extend(self._ripple_effects(world, update, target_id, source, active_index, ripple_index))
        edge_effects = _edge_update_effects(
            world,
            edge_updates or [],
            source,
            memory_prefix,
            allowed_node_ids=(propagation_set | expected_set) or None,
        )
        effects.extend(edge_effects)
        edge_update_count = sum(1 for item in edge_effects if item.type == "relationship_delta")

        return RelationshipRoundResult(
            effects=effects,
            active_node_ids=[update.node_id for update in active_updates],
            ripple_node_ids=ripple_node_ids,
            ripple_targets_by_active=ripple_targets_by_active,
            edge_update_count=edge_update_count,
            observe_only_node_ids=[
                update.node_id
                for update in active_updates
                if not update.action_tendencies and bool(update.observe_only_reason.strip())
            ],
        )

    def _active_effects(
        self,
        world: World,
        update: RelationshipNodeUpdate,
        source: str,
        memory_prefix: str,
        active_index: int,
    ) -> list[WorldEffect]:
        effects: list[WorldEffect] = []
        if update.thought:
            effects.append(
                effect(
                    "memory_add",
                    target=f"node:{update.node_id}",
                    text=f"{memory_prefix}: {update.thought}",
                    source=source,
                    importance=0.55,
                )
            )
        for rule in update.rule_mods + update.action_tendencies:
            if not rule_pressure_is_groundable(world, update.node_id, str(rule.get("rule", "")), rule):
                continue
            pressure = _rule_pressure_effect(update.node_id, rule, source, update.thought, 1.0)
            if pressure:
                effects.append(pressure)
        return effects

    def _thought_schedule_effect(
        self,
        update: RelationshipNodeUpdate,
        source: str,
        active_index: int,
        ripple_targets: list[str],
    ) -> WorldEffect:
        base_delay = active_index + 0.15 + _hash_fraction(
            f"{source}:{update.node_id}:start"
        ) * 0.7
        return effect(
            "thought_schedule_add",
            target=f"node:{update.node_id}",
            text=update.thought or "保持观察。",
            explicit_slices=_thought_segments(update),
            source=source,
            salience=0.82 + min(active_index, 5) * 0.02,
            ttl=ACTIVE_BUBBLE_TTL,
            delay=round(base_delay, 3),
            interval=round(_bubble_interval(update.node_id, source), 3),
            slice_count=THOUGHT_SLICE_COUNT,
            ripple_targets=[
                {
                    "node_id": target_id,
                    "influence_order": ripple_index,
                }
                for ripple_index, target_id in enumerate(ripple_targets)
            ],
            seed=f"{source}:{update.node_id}",
            origin="active_node",
        )

    def _ripple_effects(
        self,
        world: World,
        update: RelationshipNodeUpdate,
        target_id: str,
        source: str,
        active_index: int,
        _ripple_index: int,
    ) -> list[WorldEffect]:
        ripple_source = f"{source}:ripple"
        active_name = world.node(update.node_id).name
        ripple_text = _ripple_response_text(active_name, world.node(target_id).name)
        effects: list[WorldEffect] = [
            effect(
                "thought_schedule_add",
                target=f"node:{target_id}",
                text=ripple_text,
                explicit_slices=[ripple_text],
                source=ripple_source,
                salience=RIPPLE_BUBBLE_SALIENCE,
                ttl=RIPPLE_BUBBLE_TTL,
                delay=round(
                    _bubble_base_delay(target_id, f"{ripple_source}:{update.node_id}")
                    + _ripple_index * 2.1,
                    3,
                ),
                interval=0.0,
                slice_count=1,
                origin="ripple_response",
                ripple_from=update.node_id,
            )
        ]
        for rule in update.action_tendencies or update.rule_mods:
            if rule.get("option_id"):
                continue
            if not rule_pressure_is_groundable(world, target_id, str(rule.get("rule", "")), rule):
                continue
            pressure = _rule_pressure_effect(
                target_id,
                rule,
                ripple_source,
                f"ripple from {update.node_id}",
                RIPPLE_RULE_WEIGHT_FACTOR,
            )
            if pressure:
                effects.append(pressure)
        return effects


def _ripple_response_text(active_name: str, target_name: str) -> str:
    source_name = str(active_name).strip() or "同伴"
    if str(target_name).strip():
        return f"听到{source_name}的判断，我也得重新观察。"
    return f"受{source_name}影响，我也得重新观察。"


def _thought_segments(update: RelationshipNodeUpdate) -> list[str]:
    explicit = [
        str(item.get("text", "")).strip()
        for item in update.thought_bubbles
        if str(item.get("text", "")).strip()
    ]
    if len(explicit) == THOUGHT_SLICE_COUNT:
        return explicit
    return split_thought_for_presentation(
        update.thought or "保持观察。", THOUGHT_SLICE_COUNT
    )


def _split_text(text: str, count: int) -> list[str]:
    return split_thought_for_presentation(text, count)


def _rule_pressure_effect(
    node_id: str,
    raw_rule: JsonDict,
    source: str,
    fallback_reason: str,
    factor: float,
) -> WorldEffect | None:
    rule = str(raw_rule.get("rule", "")).strip()
    if not rule:
        return None
    weight = float(raw_rule.get("weight", 0.0) or 0.0) * factor
    ttl = int(raw_rule.get("ttl", 2) or 2)
    extra = {
        key: json_copy(value)
        for key, value in raw_rule.items()
        if key not in {"rule", "weight", "ttl", "reason", "target", "type"}
    }
    return effect(
        "rule_pressure_add",
        target=f"node:{node_id}",
        rule=rule,
        weight=round(weight, 4),
        ttl=ttl,
        source=source,
        reason=str(raw_rule.get("reason", fallback_reason)),
        origin="ripple_response" if factor < 1 else "active_node",
        **extra,
    )


def _edge_update_effects(
    world: World,
    updates: list[JsonDict],
    source: str,
    memory_prefix: str,
    allowed_node_ids: set[str] | None = None,
) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    for raw_edge in updates:
        if not isinstance(raw_edge, dict):
            continue
        source_id = _node_ref(str(raw_edge.get("from", raw_edge.get("source", ""))))
        target_id = _node_ref(str(raw_edge.get("to", raw_edge.get("target", ""))))
        relation = _normalized_edge_relation(str(raw_edge.get("relation", raw_edge.get("edge_type", ""))))
        if not source_id or not target_id or not relation:
            continue
        if not world.has_node(source_id) or not world.has_node(target_id):
            continue
        if allowed_node_ids is not None and (
            source_id not in allowed_node_ids or target_id not in allowed_node_ids
        ):
            continue
        reason = str(raw_edge.get("reason", "")).strip()
        effects.append(
            effect(
                "relationship_delta",
                source=f"node:{source_id}",
                target=f"node:{target_id}",
                relation=relation,
                delta=max(-1.0, min(float(raw_edge.get("delta", 0.0) or 0.0), 1.0)),
                ttl=max(4, min(int(raw_edge.get("ttl", 16) or 16), 60)),
                source_agent=source,
                reason=reason,
            )
        )
        if reason:
            effects.append(
                effect(
                    "memory_add",
                    target=f"node:{source_id}",
                    text=f"{memory_prefix}: {reason}",
                    source=source,
                    importance=0.45,
                )
            )
    return effects


def _normalized_edge_relation(raw: str) -> str:
    value = str(raw).strip().lower()
    if value in ALLOWED_EDGE_RELATIONS:
        return value
    aliases = {
        "照料": "care",
        "关心": "care",
        "信任": "trust",
        "恐惧": "fear",
        "怨恨": "resentment",
        "仇恨": "hatred",
        "尊重": "respect",
        "服从": "obedience",
        "权威": "authority",
        "威望": "authority",
    }
    return aliases.get(value, "")


def _node_ref(value: str) -> str:
    if value.startswith("node:"):
        return value.split(":", 1)[1]
    return value


def _bubble_interval(node_id: str, source: str) -> float:
    return ACTIVE_BUBBLE_INTERVAL_BASE


def _bubble_base_delay(node_id: str, source: str) -> float:
    return _hash_fraction(f"{source}:{node_id}:start") * 3.0


def _hash_fraction(text: str) -> float:
    hash_value = 5381
    for character in text:
        hash_value = ((hash_value << 5) + hash_value + ord(character)) & 0xFFFFFFFF
    return (hash_value % 1000) / 1000


def _neighbor_ids(
    world: World,
    node_id: str,
    excluded: set[str],
    allowed_node_ids: set[str] | None = None,
) -> list[str]:
    weights_by_node: dict[str, float] = {}
    for edge in world.relationships.values():
        other = ""
        if edge.source == node_id:
            other = edge.target
        elif edge.target == node_id:
            other = edge.source
        if (
            other
            and other not in excluded
            and world.has_node(other)
            and (allowed_node_ids is None or other in allowed_node_ids)
        ):
            weights_by_node[other] = max(weights_by_node.get(other, 0.0), abs(float(edge.weight)))
    candidates = [(weight, node_id) for node_id, weight in weights_by_node.items()]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [node_id for _, node_id in candidates]


def _ripple_assignments(
    world: World,
    active_updates: list[RelationshipNodeUpdate],
    propagation_node_ids: set[str],
    source: str,
    require_exact: bool,
) -> dict[str, list[str]]:
    active_ids = {update.node_id for update in active_updates}
    used_ids = set(active_ids)
    assignments: dict[str, list[str]] = {}
    for update in active_updates:
        targets = _neighbor_ids(
            world,
            update.node_id,
            used_ids,
            allowed_node_ids=propagation_node_ids or None,
        )[:RIPPLE_TARGETS_PER_ACTIVE]
        if require_exact and len(targets) < RIPPLE_TARGETS_PER_ACTIVE:
            fallback_ids = _rotated_coverage_ids(
                propagation_node_ids,
                used_ids | set(targets),
                f"{source}:{update.node_id}:ripple_targets",
            )
            targets.extend(fallback_ids[: RIPPLE_TARGETS_PER_ACTIVE - len(targets)])
        if require_exact and len(targets) != RIPPLE_TARGETS_PER_ACTIVE:
            raise ValueError(
                "relationship_round requires exactly "
                f"{RIPPLE_TARGETS_PER_ACTIVE} distinct ripple targets per active node; "
                f"{update.node_id} got {len(targets)}"
            )
        assignments[update.node_id] = targets
        used_ids.update(targets)
    return assignments


def _rotated_coverage_ids(node_ids: set[str], excluded: set[str], rotation_key: str) -> list[str]:
    candidates = sorted(node_id for node_id in node_ids if node_id not in excluded)
    if not candidates:
        return []
    offset = int(_hash_fraction(rotation_key) * len(candidates)) % len(candidates)
    return [*candidates[offset:], *candidates[:offset]]


def _ripple_text(thought: str, source_node: str) -> str:
    clean = " ".join(str(thought).split())
    if not clean:
        return f"我受到 {source_node} 的关系压力影响。"
    return f"听见 {source_node} 的压力后，我也开始犹豫：{clean[:36]}"


def _dict_list(value: Any) -> list[JsonDict]:
    return [json_copy(item) for item in value] if isinstance(value, list) else []
