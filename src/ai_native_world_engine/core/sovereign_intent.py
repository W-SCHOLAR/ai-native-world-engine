"""LLM-compiled sovereign user intent and declarative dynamic rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from .events import TraceRecord, json_copy
from .feedback import APPLY_AUTHORITATIVE, ActionFeedback, FeedbackIngestor, WorldEffect, effect, target
from .llm_provider import JsonLlmClient
from .rules import RuleCandidate
from .world import World, WorldNode


JsonDict = dict[str, Any]

SOVEREIGN_INTENT_SCHEMA = "sovereign_intent_plan_v1"
SOVEREIGN_INTENT_ENVELOPE_SCHEMA = "sovereign_intent_prompt_envelope_v1"

ALLOWED_SOVEREIGN_EFFECT_TYPES = frozenset(
    {
        "action_bullet_add",
        "memory_add",
        "node_attribute_delta",
        "node_attribute_merge",
        "node_state",
        "policy_state",
        "relationship_delta",
        "resource_delta",
        "rule_pressure_add",
        "thought_bubble_add",
        "world_state",
    }
)


@dataclass(slots=True)
class SovereignDynamicRule:
    id: str
    action: str
    summary: str = ""
    trigger: JsonDict = field(default_factory=dict)
    effects: list[WorldEffect] = field(default_factory=list)
    score: float = 1.0
    ttl: int = 3
    once_per_node: bool = True
    metadata: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: JsonDict) -> "SovereignDynamicRule":
        rule_id = _clean_id(value.get("id", value.get("rule_id", "")))
        if not rule_id:
            raise ValueError("dynamic rule requires id")
        raw_effects = _list(value.get("effects"))
        return cls(
            id=rule_id,
            action=_clean_id(value.get("action", rule_id)) or rule_id,
            summary=str(value.get("summary", "")),
            trigger=json_copy(_dict(value.get("trigger"))),
            effects=[_parse_effect(item, index) for index, item in enumerate(raw_effects)],
            score=float(value.get("score", 1.0) or 1.0),
            ttl=max(int(value.get("ttl", 3) or 3), 1),
            once_per_node=bool(value.get("once_per_node", True)),
            metadata=json_copy(_dict(value.get("metadata"))),
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "action": self.action,
            "summary": self.summary,
            "trigger": json_copy(self.trigger),
            "effects": [item.to_dict() for item in self.effects],
            "score": self.score,
            "ttl": self.ttl,
            "once_per_node": self.once_per_node,
            "metadata": json_copy(self.metadata),
        }


@dataclass(slots=True)
class SovereignIntentPlan:
    id: str
    user_input: str
    title: str
    summary: str
    impact_level: str = "decree"
    scheduled_tick: int = 0
    initial_effects: list[WorldEffect] = field(default_factory=list)
    dynamic_rules: list[SovereignDynamicRule] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: JsonDict) -> "SovereignIntentPlan":
        raw_effects = _list(value.get("initial_effects", value.get("effects", [])))
        raw_rules = _list(value.get("dynamic_rules"))
        title = str(value.get("title", "用户旨意")).strip() or "用户旨意"
        plan_id = _clean_id(value.get("id", "")) or _slug(title)
        return cls(
            id=plan_id,
            user_input=str(value.get("user_input", value.get("input", ""))),
            title=title,
            summary=str(value.get("summary", title)),
            impact_level=str(value.get("impact_level", value.get("level", "decree"))),
            scheduled_tick=max(int(value.get("scheduled_tick", value.get("tick", 0)) or 0), 0),
            initial_effects=[_parse_effect(item, index) for index, item in enumerate(raw_effects)],
            dynamic_rules=[SovereignDynamicRule.from_dict(_dict(item)) for item in raw_rules if isinstance(item, dict)],
            metadata=json_copy(_dict(value.get("metadata"))),
        )

    def to_dict(self) -> JsonDict:
        return {
            "schema": SOVEREIGN_INTENT_SCHEMA,
            "id": self.id,
            "user_input": self.user_input,
            "title": self.title,
            "summary": self.summary,
            "impact_level": self.impact_level,
            "scheduled_tick": self.scheduled_tick,
            "initial_effects": [item.to_dict() for item in self.initial_effects],
            "dynamic_rules": [item.to_dict() for item in self.dynamic_rules],
            "metadata": json_copy(self.metadata),
        }


@dataclass(slots=True)
class SovereignIntentCompiler:
    client: JsonLlmClient
    name: str = "sovereign-intent-compiler"
    instructions: str = (
        "You are the sovereign intent compiler for an AI interactive world engine. "
        "Turn the user's open-ended will into visible initial effects and declarative dynamic rules. "
        "Do not generate code. Return JSON only."
    )
    max_nodes: int = 24

    def compile(self, world: World, user_input: str, scheduled_tick: int = 0) -> SovereignIntentPlan:
        started = perf_counter()
        envelope = self.build_envelope(world, user_input, scheduled_tick)
        raw = self.client.complete(envelope)
        plan = SovereignIntentPlan.from_dict(
            {
                **raw,
                "user_input": str(raw.get("user_input", user_input)),
                "scheduled_tick": int(raw.get("scheduled_tick", scheduled_tick) or scheduled_tick),
            }
        )
        metadata = json_copy(plan.metadata)
        metadata["sovereign_intent_compiler"] = {
            "schema": SOVEREIGN_INTENT_ENVELOPE_SCHEMA,
            "provider": self.name,
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "candidate_node_count": len(envelope["world_context"]["candidate_nodes"]),
        }
        return SovereignIntentPlan(
            id=plan.id,
            user_input=plan.user_input,
            title=plan.title,
            summary=plan.summary,
            impact_level=plan.impact_level,
            scheduled_tick=plan.scheduled_tick,
            initial_effects=plan.initial_effects,
            dynamic_rules=plan.dynamic_rules,
            metadata=metadata,
        )

    def build_envelope(self, world: World, user_input: str, scheduled_tick: int = 0) -> JsonDict:
        return {
            "schema": SOVEREIGN_INTENT_ENVELOPE_SCHEMA,
            "compiler": self.name,
            "instructions": self.instructions,
            "user_input": user_input,
            "scheduled_tick": scheduled_tick,
            "world_context": {
                "world_id": world.id,
                "tick": world.tick,
                "attributes": json_copy(world.attributes),
                "candidate_nodes": [_node_context(node) for node in list(world.nodes.values())[: self.max_nodes]],
                "relationship_count": len(world.relationships),
            },
            "allowed_effect_types": sorted(ALLOWED_SOVEREIGN_EFFECT_TYPES),
            "expected_output": {
                "id": "stable id",
                "title": "short title",
                "summary": "visible summary",
                "impact_level": "decree | edict | omen | new_law",
                "initial_effects": [{"type": "world_state | memory_add | rule_pressure_add | ..."}],
                "dynamic_rules": [
                    {
                        "id": "new behavior rule id",
                        "action": "visible action type",
                        "trigger": {"node_types": ["person"], "world_flag": "flag_name"},
                        "score": 3.0,
                        "ttl": 6,
                        "effects": [{"type": "memory_add", "target": "node:{node.id}", "text": "..."}],
                    }
                ],
            },
        }


class SovereignDynamicRulePackage:
    def __init__(self, plan: SovereignIntentPlan | JsonDict) -> None:
        self.plan = plan if isinstance(plan, SovereignIntentPlan) else SovereignIntentPlan.from_dict(plan)
        self.name = f"sovereign_intent:{self.plan.id}"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for rule in self.plan.dynamic_rules:
            if rule.once_per_node and _already_fired(node, rule):
                continue
            pressure = _matching_pressure(node, rule)
            if pressure is None and not _trigger_matches(world, node, rule.trigger):
                continue
            metadata = {
                "sovereign_intent": self.plan.to_dict(),
                "dynamic_rule": rule.to_dict(),
                "pressure": json_copy(pressure or {}),
            }
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action=rule.action,
                    score=rule.score + float((pressure or {}).get("weight", 0.0) or 0.0),
                    rule=rule.id,
                    reason=rule.summary or self.plan.summary,
                    metadata=metadata,
                    feedback=self._feedback_for_rule(world, node, rule),
                )
            )
        return candidates

    def _feedback_for_rule(self, world: World, node: WorldNode, rule: SovereignDynamicRule) -> ActionFeedback:
        effects = [_render_effect(effect_item, world, node, self.plan, rule) for effect_item in rule.effects]
        if rule.once_per_node:
            effects.append(
                effect(
                    "node_attribute_merge",
                    target=f"node:{node.id}",
                    field="_sovereign_intent_rules",
                    value={rule.id: {"tick": world.tick, "intent_id": self.plan.id}},
                )
            )
        return ActionFeedback(
            source=self.name,
            actor_type="node",
            actor_id=node.id,
            action=rule.action,
            summary=_render_text(rule.summary or self.plan.summary, world, node, self.plan, rule),
            targets=[target("node", node.id)],
            effects=effects,
            apply_mode=APPLY_AUTHORITATIVE,
            metadata={
                "sovereign_intent": {
                    "id": self.plan.id,
                    "title": self.plan.title,
                    "impact_level": self.plan.impact_level,
                },
                "dynamic_rule": {"id": rule.id, "action": rule.action},
            },
        )


def apply_sovereign_intent_plan(world: World, ingestor: FeedbackIngestor, plan: SovereignIntentPlan | JsonDict) -> JsonDict:
    normalized = plan if isinstance(plan, SovereignIntentPlan) else SovereignIntentPlan.from_dict(plan)
    feedback = ActionFeedback(
        source="sovereign_intent",
        actor_type="user",
        actor_id="sovereign",
        action="sovereign_intent",
        summary=normalized.summary,
        effects=normalized.initial_effects,
        apply_mode=APPLY_AUTHORITATIVE,
        metadata={"sovereign_intent": normalized.to_dict()},
    )
    result = ingestor.ingest(world, feedback)
    world.traces.record(
        TraceRecord(
            tick=world.tick,
            kind="sovereign_intent",
            source="sovereign_intent",
            observed={"id": normalized.id, "title": normalized.title, "impact_level": normalized.impact_level},
            delta={"initial_effect_count": len(normalized.initial_effects), "dynamic_rule_count": len(normalized.dynamic_rules)},
        )
    )
    return result


def _parse_effect(value: Any, index: int) -> WorldEffect:
    if not isinstance(value, dict):
        raise ValueError(f"sovereign effect[{index}] must be an object")
    kind = str(value.get("type", "")).strip()
    if kind not in ALLOWED_SOVEREIGN_EFFECT_TYPES:
        raise ValueError(f"sovereign effect type is not allowed: {kind}")
    return WorldEffect(kind, {key: json_copy(raw) for key, raw in value.items() if key != "type"})


def _render_effect(effect_item: WorldEffect, world: World, node: WorldNode, plan: SovereignIntentPlan, rule: SovereignDynamicRule) -> WorldEffect:
    fields = _render_value(effect_item.fields, world, node, plan, rule)
    return effect(effect_item.type, **fields)


def _render_value(value: Any, world: World, node: WorldNode, plan: SovereignIntentPlan, rule: SovereignDynamicRule) -> Any:
    if isinstance(value, str):
        return _render_text(value, world, node, plan, rule)
    if isinstance(value, list):
        return [_render_value(item, world, node, plan, rule) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_value(item, world, node, plan, rule) for key, item in value.items()}
    return json_copy(value)


def _render_text(text: str, world: World, node: WorldNode, plan: SovereignIntentPlan, rule: SovereignDynamicRule) -> str:
    return (
        text.replace("{world.id}", world.id)
        .replace("{world.tick}", str(world.tick))
        .replace("{node.id}", node.id)
        .replace("{node.name}", node.name)
        .replace("{node.type}", node.type)
        .replace("{intent.id}", plan.id)
        .replace("{intent.title}", plan.title)
        .replace("{intent.summary}", plan.summary)
        .replace("{rule.id}", rule.id)
        .replace("{rule.action}", rule.action)
    )


def _trigger_matches(world: World, node: WorldNode, trigger: JsonDict) -> bool:
    if not trigger:
        return False
    node_ids = {str(item) for item in _list(trigger.get("node_ids"))}
    if node_ids and node.id not in node_ids:
        return False
    node_types = {str(item) for item in _list(trigger.get("node_types"))}
    if node_types and node.type not in node_types:
        return False
    world_flag = str(trigger.get("world_flag", ""))
    if world_flag and not bool(world.attributes.get(world_flag)):
        return False
    attributes = _dict(trigger.get("attributes"))
    for key, expected in attributes.items():
        if node.attributes.get(str(key)) != expected:
            return False
    return bool(node_ids or node_types or world_flag or attributes)


def _matching_pressure(node: WorldNode, rule: SovereignDynamicRule) -> JsonDict | None:
    names = {rule.id, rule.action, f"dynamic:{rule.id}"}
    for pressure in node.rule_pressures:
        if str(pressure.get("rule", "")) in names:
            return pressure
    return None


def _already_fired(node: WorldNode, rule: SovereignDynamicRule) -> bool:
    fired = node.attributes.get("_sovereign_intent_rules")
    return isinstance(fired, dict) and rule.id in fired


def _node_context(node: WorldNode) -> JsonDict:
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type,
        "position": node.position.to_dict(),
        "attributes": json_copy(node.attributes),
        "memory_count": len(node.memories),
        "pressure_count": len(node.rule_pressures),
    }


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_id(value: Any) -> str:
    return str(value).strip().replace(" ", "_").replace(":", "_")


def _slug(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return clean or "sovereign_intent"
