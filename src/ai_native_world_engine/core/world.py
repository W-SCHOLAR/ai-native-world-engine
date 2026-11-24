"""世界状态、节点、关系和基础移动。"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Any

from .action_contracts import ActionInstance, MAX_ACTION_HISTORY
from .activity_contracts import ActivityInstance, MAX_ACTIVITY_HISTORY
from .events import ActionBullet, EventStream, SpeechBubble, ThoughtBubble, TraceLedger, TraceRecord, json_copy


JsonDict = dict[str, Any]
MAX_SPEECH_EVENTS = 256


@dataclass(slots=True)
class Position:
    x: float
    y: float

    @classmethod
    def from_value(cls, value: "Position | dict[str, Any] | tuple[float, float] | list[float]") -> "Position":
        if isinstance(value, Position):
            return Position(value.x, value.y)
        if isinstance(value, dict):
            return Position(float(value.get("x", 0.0)), float(value.get("y", 0.0)))
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            return Position(float(value[0]), float(value[1]))
        raise ValueError("位置必须是 Position、dict 或二维序列")

    def distance_to(self, other: "Position") -> float:
        return hypot(other.x - self.x, other.y - self.y)

    def step_toward(self, target: "Position", distance: float) -> tuple["Position", bool]:
        total = self.distance_to(target)
        if total <= distance or total == 0:
            return Position(target.x, target.y), True
        ratio = distance / total
        return Position(
            self.x + (target.x - self.x) * ratio,
            self.y + (target.y - self.y) * ratio,
        ), False

    def to_dict(self) -> JsonDict:
        return {"x": self.x, "y": self.y}


@dataclass(slots=True)
class WorldNode:
    id: str
    type: str
    name: str
    position: Position
    attributes: JsonDict = field(default_factory=dict)
    movement_target: Position | None = None
    movement_speed: float = 0.0
    memories: list[JsonDict] = field(default_factory=list)
    rule_pressures: list[JsonDict] = field(default_factory=list)
    key_character: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "position": self.position.to_dict(),
            "attributes": json_copy(self.attributes),
            "movement_target": self.movement_target.to_dict() if self.movement_target else None,
            "movement_speed": self.movement_speed,
            "memories": json_copy(self.memories),
            "rule_pressures": json_copy(self.rule_pressures),
            # Presentation payloads intentionally stay out of authoritative
            # snapshots. They are delivered through the live presentation
            # stream and may be discarded once the local page accepts them.
            "key_character": json_copy(self.key_character),
        }


@dataclass(slots=True)
class RelationshipEdge:
    source: str
    target: str
    type: str
    weight: float = 0.0
    metadata: JsonDict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}->{self.target}:{self.type}"

    def to_dict(self) -> JsonDict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "weight": self.weight,
            "metadata": json_copy(self.metadata),
        }


class World:
    def __init__(self, id: str, attributes: JsonDict | None = None) -> None:
        if not id:
            raise ValueError("世界 id 不能为空")
        self.id = id
        self.tick = 0
        self.attributes = json_copy(attributes or {})
        self.nodes: dict[str, WorldNode] = {}
        self.relationships: dict[str, RelationshipEdge] = {}
        self.active_actions: dict[str, ActionInstance] = {}
        self.action_history: list[ActionInstance] = []
        self.action_sequence = 0
        self.active_activities: dict[str, ActivityInstance] = {}
        self.activity_history: list[ActivityInstance] = []
        self.activity_sequence = 0
        self.speech_events: list[JsonDict] = []
        self.events = EventStream()
        # Presentation is intentionally a separate, non-authoritative stream.
        # It is never snapshotted, recovered, fed into memory, or used by rules.
        # A viewer consumes these records once and they may then be discarded.
        self.presentation = EventStream()
        self.traces = TraceLedger()
        self.errors: list[JsonDict] = []

    @classmethod
    def scenario(cls, name: str, **kwargs: Any) -> "World":
        from .scenario_registry import DEFAULT_SCENARIO_REGISTRY

        return DEFAULT_SCENARIO_REGISTRY.create(name, **kwargs)

    @classmethod
    def from_snapshot(cls, snapshot: JsonDict) -> "World":
        world = cls(str(snapshot.get("id", "restored-world")), json_copy(_dict(snapshot.get("attributes"))))
        world.tick = int(snapshot.get("tick", 0) or 0)
        for raw_node in _list(snapshot.get("nodes")):
            node_data = _dict(raw_node)
            node_id = str(node_data.get("id", ""))
            if not node_id:
                continue
            movement_target = node_data.get("movement_target")
            world.nodes[node_id] = WorldNode(
                id=node_id,
                type=str(node_data.get("type", "")),
                name=str(node_data.get("name", node_id)),
                position=Position.from_value(_dict(node_data.get("position"))),
                attributes=json_copy(_dict(node_data.get("attributes"))),
                movement_target=Position.from_value(_dict(movement_target)) if isinstance(movement_target, dict) else None,
                movement_speed=float(node_data.get("movement_speed", 0.0) or 0.0),
                memories=json_copy(_list(node_data.get("memories"))),
                rule_pressures=json_copy(_list(node_data.get("rule_pressures"))),
                # Legacy snapshots may carry display rings. Never restore them
                # into new authoritative world state.
                key_character=json_copy(_dict(node_data.get("key_character"))),
            )
        for raw_edge in _list(snapshot.get("relationships")):
            edge_data = _dict(raw_edge)
            edge = RelationshipEdge(
                source=str(edge_data.get("source", "")),
                target=str(edge_data.get("target", "")),
                type=str(edge_data.get("type", "")),
                weight=float(edge_data.get("weight", 0.0) or 0.0),
                metadata=json_copy(_dict(edge_data.get("metadata"))),
            )
            world.relationships[edge.key] = edge
        for raw_action in _list(snapshot.get("active_actions")):
            if not isinstance(raw_action, dict):
                continue
            action = ActionInstance.from_dict(raw_action)
            if action.id and action.active:
                world.active_actions[action.id] = action
        for raw_action in _list(snapshot.get("action_history")):
            if not isinstance(raw_action, dict):
                continue
            action = ActionInstance.from_dict(raw_action)
            if action.id and action.terminal:
                world.action_history.append(action)
        world.action_history = world.action_history[-MAX_ACTION_HISTORY:]
        world.action_sequence = max(
            int(snapshot.get("action_sequence", 0) or 0),
            len(world.active_actions) + len(world.action_history),
        )
        for raw_activity in _list(snapshot.get("active_activities")):
            if isinstance(raw_activity, dict):
                activity = ActivityInstance.from_dict(raw_activity)
                if activity.id and activity.active:
                    world.active_activities[activity.id] = activity
        for raw_activity in _list(snapshot.get("activity_history")):
            if isinstance(raw_activity, dict):
                activity = ActivityInstance.from_dict(raw_activity)
                if activity.id and activity.terminal:
                    world.activity_history.append(activity)
        world.activity_history = world.activity_history[-MAX_ACTIVITY_HISTORY:]
        world.activity_sequence = max(
            int(snapshot.get("activity_sequence", 0) or 0),
            len(world.active_activities) + len(world.activity_history),
        )
        world.speech_events = [
            json_copy(item)
            for item in _list(snapshot.get("speech_events"))[-MAX_SPEECH_EVENTS:]
            if isinstance(item, dict)
        ]
        world.events = EventStream.from_records(_list(snapshot.get("events")), _list(snapshot.get("deltas")))
        world.traces = TraceLedger.from_records(_list(snapshot.get("traces")))
        world.errors = json_copy(_list(snapshot.get("errors")))
        return world

    def add_node(
        self,
        id: str,
        type: str,
        name: str,
        position: Position | dict[str, Any] | tuple[float, float] | list[float],
        attributes: JsonDict | None = None,
    ) -> WorldNode:
        node_id = str(id)
        if node_id in self.nodes:
            raise ValueError(f"节点 id 已存在：{node_id}")
        node = WorldNode(
            id=node_id,
            type=str(type),
            name=str(name),
            position=Position.from_value(position),
            attributes=json_copy(attributes or {}),
        )
        self.nodes[node.id] = node
        return node

    def node(self, node_id: str) -> WorldNode:
        try:
            return self.nodes[str(node_id)]
        except KeyError as exc:
            raise KeyError(f"节点不存在：{node_id}") from exc

    def has_node(self, node_id: str) -> bool:
        return str(node_id) in self.nodes

    def add_relationship(
        self,
        source: str,
        target: str,
        type: str,
        weight: float = 0.0,
        metadata: JsonDict | None = None,
    ) -> RelationshipEdge:
        self._require_node(source)
        self._require_node(target)
        edge = RelationshipEdge(str(source), str(target), str(type), float(weight), json_copy(metadata or {}))
        self.relationships[edge.key] = edge
        return edge

    def update_relationship_weight(
        self,
        source: str,
        target: str,
        type: str,
        weight: float,
    ) -> RelationshipEdge:
        key = RelationshipEdge(str(source), str(target), str(type)).key
        if key not in self.relationships:
            return self.add_relationship(source, target, type, weight)
        self.relationships[key].weight = float(weight)
        return self.relationships[key]

    def adjust_relationship_weight(
        self,
        source: str,
        target: str,
        type: str,
        delta: float,
        metadata: JsonDict | None = None,
    ) -> RelationshipEdge:
        key = RelationshipEdge(str(source), str(target), str(type)).key
        if key not in self.relationships:
            return self.add_relationship(source, target, type, delta, metadata)
        edge = self.relationships[key]
        edge.weight += float(delta)
        if metadata:
            edge.metadata.update(json_copy(metadata))
        return edge

    def set_movement_target(
        self,
        node_id: str,
        target: Position | dict[str, Any] | tuple[float, float] | list[float],
        speed: float,
    ) -> None:
        node = self.node(node_id)
        node.movement_target = Position.from_value(target)
        node.movement_speed = max(float(speed), 0.0)

    def emit_thought_bubble(self, bubble: ThoughtBubble) -> None:
        self._require_node(bubble.node_id)
        payload = bubble.to_dict()
        self.presentation.record(self.tick, "display_payload", bubble.source, payload)

    def emit_action_bullet(self, bullet: ActionBullet) -> None:
        self._require_node(bullet.node_id)
        payload = bullet.to_dict()
        self.presentation.record(self.tick, "display_payload", bullet.source, payload)

    def emit_speech_bubble(self, bubble: SpeechBubble) -> None:
        self._require_node(bubble.node_id)
        self.presentation.record(
            self.tick, "display_payload", bubble.source, bubble.to_dict()
        )

    def emit_thought_schedule(self, payload: JsonDict, source: str) -> None:
        """Record one compact non-authoritative visual schedule."""

        node_id = str(payload.get("node_id", ""))
        self._require_node(node_id)
        schedule = json_copy(payload)
        schedule["type"] = "thought_schedule"
        schedule["node_id"] = node_id
        schedule.setdefault("source", source or "system")
        self.presentation.record(self.tick, "display_payload", source, schedule)

    def step(self, rule_engine: Any | None = None) -> None:
        self.tick += 1
        self.traces.record(TraceRecord(self.tick, "tick", "world"))
        if rule_engine is None:
            from .rules import MovementRulePackage, RuleEngineSet

            rule_engine = RuleEngineSet([MovementRulePackage()])
        rule_engine.step(self)
        self.decay_rule_pressures()

    def decay_rule_pressures(self) -> None:
        expired: list[JsonDict] = []
        for node in self.nodes.values():
            active: list[JsonDict] = []
            for pressure in node.rule_pressures:
                next_pressure = json_copy(pressure)
                next_pressure["ttl"] = int(next_pressure.get("ttl", 1) or 1) - 1
                if next_pressure["ttl"] > 0:
                    active.append(next_pressure)
                else:
                    expired.append({"node_id": node.id, "pressure": next_pressure})
            node.rule_pressures = active
        if expired:
            self.traces.record(
                TraceRecord(
                    tick=self.tick,
                    kind="pressure_decay",
                    source="world",
                    observed={"expired_count": len(expired)},
                    delta={"expired": expired[-20:]},
                )
            )
            self.events.record_delta(
                self.tick,
                "world",
                {
                    "kind": "pressure_decay",
                    "expired_count": len(expired),
                    "expired": expired[-20:],
                },
            )

    def snapshot(self) -> JsonDict:
        return {
            "id": self.id,
            "tick": self.tick,
            "attributes": json_copy(self.attributes),
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "relationships": [edge.to_dict() for edge in self.relationships.values()],
            "active_actions": [
                self.active_actions[action_id].to_dict()
                for action_id in sorted(self.active_actions)
            ],
            "action_history": [
                action.to_dict() for action in self.action_history[-MAX_ACTION_HISTORY:]
            ],
            "action_sequence": int(self.action_sequence),
            "active_activities": [
                self.active_activities[item_id].to_dict()
                for item_id in sorted(self.active_activities)
            ],
            "activity_history": [
                item.to_dict() for item in self.activity_history[-MAX_ACTIVITY_HISTORY:]
            ],
            "activity_sequence": int(self.activity_sequence),
            "speech_events": json_copy(self.speech_events[-MAX_SPEECH_EVENTS:]),
            "events": self.events.recent(),
            "deltas": self.events.recent_deltas(),
            "traces": self.traces.recent(),
            "errors": json_copy(self.errors),
        }

    def _require_node(self, node_id: str) -> None:
        if str(node_id) not in self.nodes:
            raise KeyError(f"节点不存在：{node_id}")


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
