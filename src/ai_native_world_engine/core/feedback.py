"""行动反馈、世界效果和反馈摄取器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .action_contracts import ActionInstance, MAX_ACTION_HISTORY
from .activity_contracts import ActivityInstance, MAX_ACTIVITY_HISTORY
from .events import ActionBullet, SpeechBubble, ThoughtBubble, json_copy
from .rule_names import canonical_rule_name
from .world import Position, World


JsonDict = dict[str, Any]

APPLY_OBSERVED = "observed"
APPLY_AUTHORITATIVE = "authoritative"


@dataclass(slots=True)
class WorldTarget:
    type: str
    id: str
    extra: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result = {"type": self.type, "id": self.id}
        result.update(json_copy(self.extra))
        return result


@dataclass(slots=True)
class WorldEffect:
    type: str
    fields: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result = {"type": self.type}
        result.update(json_copy(self.fields))
        return result


@dataclass(slots=True)
class ActionFeedback:
    source: str
    actor_type: str
    actor_id: str
    action: str
    summary: str
    targets: list[WorldTarget] = field(default_factory=list)
    effects: list[WorldEffect] = field(default_factory=list)
    apply_mode: str = APPLY_OBSERVED
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result = {
            "source": self.source,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "action": self.action,
            "summary": self.summary,
            "targets": [target.to_dict() for target in self.targets],
            "effects": [effect.to_dict() for effect in self.effects],
            "apply_mode": self.apply_mode,
        }
        result.update(json_copy(self.metadata))
        return result

    @classmethod
    def from_dict(cls, value: JsonDict) -> "ActionFeedback":
        normalized = normalize_feedback(value)
        return cls(
            source=normalized["source"],
            actor_type=normalized["actor_type"],
            actor_id=str(normalized["actor_id"]),
            action=normalized["action"],
            summary=normalized["summary"],
            targets=[
                WorldTarget(str(t.get("type", "node")), str(t.get("id", "")), {k: v for k, v in t.items() if k not in {"type", "id"}})
                for t in normalized["targets"]
            ],
            effects=[
                WorldEffect(str(e.get("type", "")), {k: v for k, v in e.items() if k != "type"})
                for e in normalized["effects"]
            ],
            apply_mode=normalized["apply_mode"],
            metadata={k: v for k, v in normalized.items() if k not in {"source", "actor_type", "actor_id", "action", "summary", "targets", "effects", "apply_mode"}},
        )


def target(type: str, id: str, **extra: Any) -> WorldTarget:
    return WorldTarget(type, str(id), json_copy(extra))


def effect(type: str, **fields: Any) -> WorldEffect:
    return WorldEffect(type, json_copy(fields))


def normalize_feedback(value: JsonDict | ActionFeedback) -> JsonDict:
    if isinstance(value, ActionFeedback):
        value = value.to_dict()
    result = json_copy(value)
    result.setdefault("source", "unknown")
    result.setdefault("actor_type", "system")
    result.setdefault("actor_id", result.get("source", "system"))
    result.setdefault("action", "unknown")
    result.setdefault("summary", result.get("action", "unknown"))
    if not isinstance(result.get("targets"), list):
        result["targets"] = []
    if not isinstance(result.get("effects"), list):
        result["effects"] = []
    result.setdefault("apply_mode", APPLY_OBSERVED)
    return result


class FeedbackIngestor:
    def ingest(self, world: World, feedback: JsonDict | ActionFeedback) -> JsonDict:
        normalized = normalize_feedback(feedback)
        _stamp_pressure_observation_windows(normalized, world.tick)
        record = world.events.record(world.tick, "action_feedback", normalized["source"], normalized)
        applied: list[int] = []
        errors: list[JsonDict] = []
        if normalized["apply_mode"] == APPLY_AUTHORITATIVE:
            for index, raw_effect in enumerate(normalized["effects"]):
                try:
                    if self.apply_effect(world, raw_effect, normalized):
                        applied.append(index)
                except Exception as exc:  # noqa: BLE001 - 错误需要进入世界审计记录。
                    error = {
                        "feedback_sequence": record.sequence,
                        "effect_index": index,
                        "effect": json_copy(raw_effect),
                        "error": str(exc),
                    }
                    world.errors.append(error)
                    errors.append(error)
        world.events.record_delta(
            world.tick,
            normalized["source"],
            {
                "feedback_sequence": record.sequence,
                "apply_mode": normalized["apply_mode"],
                "applied_effects": applied,
                "errors": errors,
            },
        )
        normalized["sequence"] = record.sequence
        normalized["applied_effects"] = applied
        normalized["errors"] = errors
        return normalized
    def apply_effect(self, world: World, raw_effect: JsonDict, feedback: JsonDict) -> bool:
        kind = str(raw_effect.get("type", ""))
        if kind in {"action_state_start", "action_state_update", "action_state_finish"}:
            return _apply_action_state(world, raw_effect, kind)
        if kind == "activity_state_upsert":
            activity_data = raw_effect.get("activity")
            if not isinstance(activity_data, dict):
                raise ValueError("activity_state_upsert 缺少 activity")
            activity = ActivityInstance.from_dict(activity_data)
            if not activity.id:
                raise ValueError("activity_state_upsert 缺少 id")
            world.activity_sequence = max(world.activity_sequence + 1, 1)
            if activity.active:
                world.active_activities[activity.id] = activity
            else:
                world.active_activities.pop(activity.id, None)
                world.activity_history = [
                    item for item in world.activity_history if item.id != activity.id
                ]
                world.activity_history.append(activity)
                world.activity_history = world.activity_history[-MAX_ACTIVITY_HISTORY:]
            return True
        if kind == "node_state":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            field = str(raw_effect.get("field", ""))
            if not field:
                raise ValueError("node_state 缺少 field")
            node.attributes[field] = json_copy(raw_effect.get("value"))
            return True
        if kind == "node_attribute_delta":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            field = str(raw_effect.get("field", ""))
            if not field:
                raise ValueError("node_attribute_delta 缺少 field")
            current = float(node.attributes.get(field, 0.0) or 0.0)
            value = current + float(raw_effect.get("delta", 0.0) or 0.0)
            if "floor" in raw_effect:
                value = max(value, float(raw_effect["floor"]))
            if "ceiling" in raw_effect:
                value = min(value, float(raw_effect["ceiling"]))
            node.attributes[field] = _clean_number(value)
            return True
        if kind == "node_attribute_merge":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            field = str(raw_effect.get("field", ""))
            value = raw_effect.get("value", {})
            if not field or not isinstance(value, dict):
                raise ValueError("node_attribute_merge 需要 field 和对象 value")
            existing = node.attributes.setdefault(field, {})
            if not isinstance(existing, dict):
                raise ValueError(f"节点属性 {field} 必须是对象")
            existing.update(json_copy(value))
            return True
        if kind == "health_delta":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            current = float(node.attributes.get("health", raw_effect.get("default", 10.0)) or 0.0)
            value = current + float(raw_effect.get("delta", 0.0) or 0.0)
            if "floor" in raw_effect:
                value = max(value, float(raw_effect["floor"]))
            if "ceiling" in raw_effect:
                value = min(value, float(raw_effect["ceiling"]))
            node.attributes["health"] = _clean_number(value)
            if value <= 0:
                node.attributes["alive"] = False
            return True
        if kind == "infection_state":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            reserved = {"type", "target", "node_id", "pathogen", "status", "severity"}
            infection = {
                "pathogen": str(raw_effect.get("pathogen", "scenario_pathogen")),
                "status": str(raw_effect.get("status", "exposed")),
                "severity": float(raw_effect.get("severity", 1.0) or 1.0),
                "tick": world.tick,
                "source": feedback.get("source", ""),
            }
            infection.update({key: json_copy(value) for key, value in raw_effect.items() if key not in reserved})
            node.attributes["infection"] = infection
            return True
        if kind == "policy_state":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            policies = node.attributes.setdefault("policies", {})
            if not isinstance(policies, dict):
                raise ValueError("节点 policies 必须是对象")
            policy = str(raw_effect.get("policy", "policy"))
            policies[policy] = {
                "status": raw_effect.get("status", "active"),
                "tick": world.tick,
                "source": feedback.get("source", ""),
            }
            policies[policy].update(
                {
                    key: json_copy(value)
                    for key, value in raw_effect.items()
                    if key not in {"type", "target", "node_id", "policy", "status"}
                }
            )
            return True
        if kind == "publication_add":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            publications = node.attributes.setdefault("publications", [])
            if not isinstance(publications, list):
                raise ValueError("节点 publications 必须是列表")
            publication = {
                "title": str(raw_effect.get("title", "Scenario note")),
                "topic": str(raw_effect.get("topic", "scenario research")),
                "tick": world.tick,
                "source": feedback.get("source", ""),
            }
            publications.append(publication)
            node.memories.append(
                {
                    "tick": world.tick,
                    "text": f"published {publication['title']} about {publication['topic']}",
                    "source": feedback.get("source", ""),
                    "importance": 0.65,
                }
            )
            return True
        if kind == "migration_state":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            reserved = {"type", "target", "node_id", "destination", "status"}
            node.attributes["migration"] = {
                "destination": str(raw_effect.get("destination", "")),
                "status": str(raw_effect.get("status", "migrating")),
                "tick": world.tick,
                "source": feedback.get("source", ""),
            }
            node.attributes["migration"].update(
                {key: json_copy(value) for key, value in raw_effect.items() if key not in reserved}
            )
            if raw_effect.get("destination"):
                node.attributes["location_label"] = str(raw_effect["destination"])
            return True
        if kind == "collaboration_add":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            collaborations = node.attributes.setdefault("collaborations", [])
            if not isinstance(collaborations, list):
                raise ValueError("节点 collaborations 必须是列表")
            collaborations.append(
                {
                    "partner": str(raw_effect.get("partner", "")),
                    "project": str(raw_effect.get("project", "scenario collaboration")),
                    "tick": world.tick,
                    "source": feedback.get("source", ""),
                }
            )
            return True
        if kind == "node_position":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            next_position = Position.from_value(raw_effect.get("position", raw_effect))
            node.position = next_position
            if raw_effect.get("arrived"):
                node.movement_target = None
                node.movement_speed = 0.0
            return True
        if kind == "relationship_delta":
            source = _node_id(raw_effect.get("source", raw_effect.get("from", "")))
            target_id = _node_id(raw_effect.get("target", raw_effect.get("to", "")))
            relation = str(raw_effect.get("relation", raw_effect.get("edge_type", "")))
            if not relation:
                raise ValueError("relationship_delta 缺少 relation")
            world.adjust_relationship_weight(
                source,
                target_id,
                relation,
                float(raw_effect.get("delta", 0.0)),
                {
                    "ttl": raw_effect.get("ttl"),
                    "source": raw_effect.get("source_label", feedback.get("source")),
                    "reason": raw_effect.get("reason", ""),
                },
            )
            return True
        if kind == "memory_add":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            memory = {
                "tick": world.tick,
                "text": str(raw_effect.get("text", "")),
                "source": raw_effect.get("source", feedback.get("source")),
                "importance": float(raw_effect.get("importance", 0.0)),
            }
            if isinstance(raw_effect.get("metadata"), dict):
                memory["metadata"] = json_copy(raw_effect["metadata"])
            node.memories.append(memory)
            return True
        if kind == "rule_pressure_add":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            pressure = {
                "rule": canonical_rule_name(str(raw_effect.get("rule", ""))),
                "weight": float(raw_effect.get("weight", 0.0)),
                "ttl": int(raw_effect.get("ttl", 1)),
                "source": raw_effect.get("source", feedback.get("source")),
                "reason": raw_effect.get("reason", ""),
            }
            pressure.update(
                {
                    key: json_copy(value)
                    for key, value in raw_effect.items()
                    if key
                    not in {
                        "type",
                        "target",
                        "node_id",
                        "rule",
                        "weight",
                        "ttl",
                        "source",
                        "reason",
                    }
                }
            )
            node.rule_pressures.append(pressure)
            return True
        if kind == "resource_transfer":
            source = world.node(_node_id(raw_effect.get("from", raw_effect.get("source", ""))))
            receiver = world.node(_node_id(raw_effect.get("to", raw_effect.get("target", ""))))
            resource = str(raw_effect.get("resource", ""))
            amount = float(raw_effect.get("amount", 0.0) or 0.0)
            if not resource:
                raise ValueError("resource_transfer 缺少 resource")
            if amount <= 0:
                raise ValueError("resource_transfer amount 必须大于 0")
            source_resources = _resources(source.attributes)
            receiver_resources = _resources(receiver.attributes)
            available = float(source_resources.get(resource, 0.0) or 0.0)
            if available < amount:
                raise ValueError(f"资源不足：{source.id}.{resource}={available}, requested={amount}")
            source_resources[resource] = _clean_number(available - amount)
            receiver_resources[resource] = _clean_number(
                float(receiver_resources.get(resource, 0.0) or 0.0) + amount
            )
            return True
        if kind == "resource_delta":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            resource = str(raw_effect.get("resource", ""))
            if not resource:
                raise ValueError("resource_delta 缺少 resource")
            resources = _resources(node.attributes)
            current = float(resources.get(resource, raw_effect.get("default", 0.0)) or 0.0)
            value = current + float(raw_effect.get("delta", 0.0) or 0.0)
            if "floor" in raw_effect:
                value = max(value, float(raw_effect["floor"]))
            if "ceiling" in raw_effect:
                value = min(value, float(raw_effect["ceiling"]))
            resources[resource] = _clean_number(value)
            return True
        if kind == "thought_bubble_add":
            reserved = {"type", "target", "node_id", "text", "source", "mood", "salience", "ttl"}
            world.emit_thought_bubble(
                ThoughtBubble(
                    node_id=_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))),
                    text=str(raw_effect.get("text", "")),
                    source=str(raw_effect.get("source", feedback.get("source", "system"))),
                    mood=str(raw_effect.get("mood", "")),
                    salience=float(raw_effect.get("salience", 0.5)),
                    ttl=float(raw_effect.get("ttl", 6.0)),
                    metadata={key: json_copy(value) for key, value in raw_effect.items() if key not in reserved},
                )
            )
            return True
        if kind == "thought_schedule_add":
            reserved = {"type", "target", "node_id"}
            node_id = _node_id(
                raw_effect.get("target", raw_effect.get("node_id", ""))
            )
            world.emit_thought_schedule(
                {
                    "node_id": node_id,
                    **{
                        key: json_copy(value)
                        for key, value in raw_effect.items()
                        if key not in reserved
                    },
                },
                str(raw_effect.get("source", feedback.get("source", "system"))),
            )
            return True
        if kind == "action_bullet_add":
            reserved = {"type", "target", "node_id", "text", "source", "salience", "ttl"}
            world.emit_action_bullet(
                ActionBullet(
                    node_id=_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))),
                    text=str(raw_effect.get("text", "")),
                    source=str(raw_effect.get("source", feedback.get("source", "system"))),
                    salience=float(raw_effect.get("salience", 0.5)),
                    ttl=float(raw_effect.get("ttl", 4.0)),
                    metadata={key: json_copy(value) for key, value in raw_effect.items() if key not in reserved},
                )
            )
            return True
        if kind == "speech_bubble_add":
            reserved = {
                "type",
                "target",
                "node_id",
                "text",
                "source",
                "speech_event_id",
                "conversation_id",
                "target_ids",
                "ttl",
            }
            target_ids = raw_effect.get("target_ids", [])
            world.emit_speech_bubble(
                SpeechBubble(
                    node_id=_node_id(
                        raw_effect.get("target", raw_effect.get("node_id", ""))
                    ),
                    text=str(raw_effect.get("text", "")),
                    source=str(
                        raw_effect.get("source", feedback.get("source", "system"))
                    ),
                    speech_event_id=str(raw_effect.get("speech_event_id", "")),
                    conversation_id=str(raw_effect.get("conversation_id", "")),
                    target_ids=[str(item) for item in target_ids]
                    if isinstance(target_ids, list)
                    else [],
                    ttl=float(raw_effect.get("ttl", 4.0) or 4.0),
                    metadata={
                        key: json_copy(value)
                        for key, value in raw_effect.items()
                        if key not in reserved
                    },
                )
            )
            return True
        if kind == "speech_event_add":
            speech_event = raw_effect.get("event", {})
            if not isinstance(speech_event, dict):
                raise ValueError("speech_event_add requires event object")
            event_id = str(speech_event.get("id", ""))
            if not event_id:
                raise ValueError("speech_event_add event id is required")
            if not any(
                str(item.get("id", "")) == event_id
                for item in world.speech_events
                if isinstance(item, dict)
            ):
                world.speech_events.append(json_copy(speech_event))
                if len(world.speech_events) > 256:
                    world.speech_events = world.speech_events[-256:]
            return True
        if kind == "message_receive":
            node = world.node(
                _node_id(raw_effect.get("target", raw_effect.get("node_id", "")))
            )
            messages = node.attributes.setdefault("received_messages", [])
            if not isinstance(messages, list):
                raise ValueError("node received_messages must be an array")
            message = {
                key: json_copy(value)
                for key, value in raw_effect.items()
                if key not in {"type", "target", "node_id"}
            }
            messages.append(message)
            if len(messages) > 32:
                node.attributes["received_messages"] = messages[-32:]
            return True
        if kind == "key_character_state":
            node = world.node(_node_id(raw_effect.get("target", raw_effect.get("node_id", ""))))
            node.key_character.update(json_copy(raw_effect.get("value", {})))
            return True
        if kind == "world_state":
            key = str(raw_effect.get("field", ""))
            if not key:
                raise ValueError("world_state 缺少 field")
            world.attributes[key] = json_copy(raw_effect.get("value"))
            return True
        raise ValueError(f"不支持的效果类型：{kind}")


def _stamp_pressure_observation_windows(feedback: JsonDict, applied_tick: int) -> None:
    """Give correlated pressure a real post-application observation window.

    Provider output may be computed from an older source tick. The pressure
    cannot be judged before it has actually entered authoritative world state.
    """

    effects = feedback.get("effects", [])
    if not isinstance(effects, list):
        return
    for raw_effect in effects:
        if not isinstance(raw_effect, dict) or raw_effect.get("type") != "rule_pressure_add":
            continue
        if not str(raw_effect.get("pressure_id", "")).strip():
            continue
        ttl = max(int(raw_effect.get("ttl", 1) or 1), 1)
        existing_deadline = int(
            raw_effect.get("observation_deadline_tick", applied_tick) or applied_tick
        )
        raw_effect["applied_tick"] = int(applied_tick)
        raw_effect["observation_deadline_tick"] = max(
            existing_deadline,
            int(applied_tick) + max(ttl, 2),
        )


def _apply_action_state(world: World, raw_effect: JsonDict, kind: str) -> bool:
    value = raw_effect.get("action", {})
    if not isinstance(value, dict):
        raise ValueError(f"{kind} requires action object")
    action = ActionInstance.from_dict(value)
    if not action.id or not action.actor_id or not action.definition_id:
        raise ValueError(f"{kind} action identity is incomplete")
    if kind == "action_state_start":
        if not action.active:
            raise ValueError("action_state_start requires active status")
        if action.id in world.active_actions:
            raise ValueError(f"action already active: {action.id}")
        requested_locks = set(action.locks)
        for current in world.active_actions.values():
            if current.actor_id != action.actor_id:
                continue
            if current.channel == action.channel:
                raise ValueError(
                    f"action channel occupied: {action.actor_id}.{action.channel}"
                )
            if requested_locks.intersection(current.locks):
                raise ValueError(f"action locks occupied: {action.id}")
        world.active_actions[action.id] = action
    elif kind == "action_state_update":
        current = world.active_actions.get(action.id)
        if current is None:
            raise ValueError(f"active action not found: {action.id}")
        if not action.active:
            raise ValueError("action_state_update requires active status")
        if (
            current.actor_id != action.actor_id
            or current.definition_id != action.definition_id
            or current.channel != action.channel
        ):
            raise ValueError(f"action identity changed during update: {action.id}")
        world.active_actions[action.id] = action
    else:
        if not action.terminal:
            raise ValueError("action_state_finish requires terminal status")
        current = world.active_actions.get(action.id)
        if current is None:
            if any(item.id == action.id for item in world.action_history):
                raise ValueError(f"action already terminal: {action.id}")
            if action.started_tick != world.tick:
                raise ValueError(f"active action not found: {action.id}")
        elif (
            current.actor_id != action.actor_id
            or current.definition_id != action.definition_id
            or current.channel != action.channel
        ):
            raise ValueError(f"action identity changed during finish: {action.id}")
        world.active_actions.pop(action.id, None)
        world.action_history.append(action)
        if len(world.action_history) > MAX_ACTION_HISTORY:
            world.action_history = world.action_history[-MAX_ACTION_HISTORY:]
    world.action_sequence = max(
        world.action_sequence,
        _action_sequence_from_id(action.id),
        len(world.active_actions) + len(world.action_history),
    )
    return True


def _action_sequence_from_id(action_id: str) -> int:
    parts = action_id.split(":")
    if len(parts) >= 3 and parts[0] == "action":
        try:
            return max(int(parts[2]), 0)
        except ValueError:
            return 0
    return 0


def _node_id(value: Any) -> str:
    text = str(value)
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _resources(attributes: JsonDict) -> JsonDict:
    resources = attributes.setdefault("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("节点 resources 必须是对象")
    return resources


def _clean_number(value: float) -> int | float:
    if value.is_integer():
        return int(value)
    return value
