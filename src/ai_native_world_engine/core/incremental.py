"""Incremental live-run commits and compact recovery snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Iterable

from .events import json_copy
from .action_contracts import MAX_ACTION_HISTORY
from .activity_contracts import MAX_ACTIVITY_HISTORY
from .world import MAX_SPEECH_EVENTS, RelationshipEdge, World


JsonDict = dict[str, Any]
TICK_COMMIT_SCHEMA = "ai-native-world.tick-commit.v2"
COMPACT_CHECKPOINT_SCHEMA = "ai-native-world.compact-checkpoint.v2"


@dataclass(slots=True)
class TickCommit:
    """One idempotent authoritative transition of a live RunSession."""

    sequence: int
    source_tick: int
    resulting_tick: int
    source_phase: str
    resulting_phase: str
    state_delta: JsonDict
    session_state: JsonDict = field(default_factory=dict)
    event_start: int = 0
    event_end: int = 0
    trace_start: int = 0
    trace_end: int = 0
    provider_output_start: int = 0
    provider_output_end: int = 0
    provider_attempt_start: int = 0
    provider_attempt_end: int = 0
    id: str = ""
    checksum: str = ""

    def __post_init__(self) -> None:
        payload = self._identity_payload()
        digest = _checksum(payload)
        if self.checksum and self.checksum != digest:
            raise ValueError("TickCommit checksum mismatch")
        self.checksum = digest
        if not self.id:
            self.id = f"tick-{max(int(self.sequence), 0):012d}-{digest[:16]}"

    def _identity_payload(self) -> JsonDict:
        return {
            "schema": TICK_COMMIT_SCHEMA,
            "sequence": int(self.sequence),
            "source_tick": int(self.source_tick),
            "resulting_tick": int(self.resulting_tick),
            "source_phase": self.source_phase,
            "resulting_phase": self.resulting_phase,
            "state_delta": json_copy(self.state_delta),
            "session_state": json_copy(self.session_state),
            "event_range": [int(self.event_start), int(self.event_end)],
            "trace_range": [int(self.trace_start), int(self.trace_end)],
            "provider_output_range": [
                int(self.provider_output_start),
                int(self.provider_output_end),
            ],
            "provider_attempt_range": [
                int(self.provider_attempt_start),
                int(self.provider_attempt_end),
            ],
        }

    def to_dict(self) -> JsonDict:
        return {
            **self._identity_payload(),
            "id": self.id,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "TickCommit":
        event_range = _range(value.get("event_range"))
        trace_range = _range(value.get("trace_range"))
        output_range = _range(value.get("provider_output_range"))
        attempt_range = _range(value.get("provider_attempt_range"))
        return cls(
            sequence=int(value.get("sequence", 0) or 0),
            source_tick=int(value.get("source_tick", 0) or 0),
            resulting_tick=int(value.get("resulting_tick", 0) or 0),
            source_phase=str(value.get("source_phase", "running")),
            resulting_phase=str(value.get("resulting_phase", "running")),
            state_delta=_dict(value.get("state_delta")),
            session_state=_dict(value.get("session_state")),
            event_start=event_range[0],
            event_end=event_range[1],
            trace_start=trace_range[0],
            trace_end=trace_range[1],
            provider_output_start=output_range[0],
            provider_output_end=output_range[1],
            provider_attempt_start=attempt_range[0],
            provider_attempt_end=attempt_range[1],
            id=str(value.get("id", "")),
            checksum=str(value.get("checksum", "")),
        )


@dataclass(slots=True)
class IncrementalRunResult:
    """Bounded additions emitted by one RunSession hot-path step."""

    commit: TickCommit
    events: list[JsonDict] = field(default_factory=list)
    presentation_events: list[JsonDict] = field(default_factory=list)
    traces: list[JsonDict] = field(default_factory=list)
    provider_outputs: list[JsonDict] = field(default_factory=list)
    provider_attempts: list[JsonDict] = field(default_factory=list)
    provider_audits: list[JsonDict] = field(default_factory=list)
    intervention_audits: list[JsonDict] = field(default_factory=list)
    memory_consolidation: list[JsonDict] = field(default_factory=list)
    sovereign_intent_audits: list[JsonDict] = field(default_factory=list)
    runtime: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "commit": self.commit.to_dict(),
            "events": json_copy(self.events),
            "presentation_events": json_copy(self.presentation_events),
            "traces": json_copy(self.traces),
            "provider_outputs": json_copy(self.provider_outputs),
            "provider_attempts": json_copy(self.provider_attempts),
            "provider_audits": json_copy(self.provider_audits),
            "intervention_audits": json_copy(self.intervention_audits),
            "memory_consolidation": json_copy(self.memory_consolidation),
            "sovereign_intent_audits": json_copy(self.sovereign_intent_audits),
            "runtime": json_copy(self.runtime),
        }


def compact_world_snapshot(world: World) -> JsonDict:
    """Return recovery state without logs or non-authoritative display history."""

    nodes: list[JsonDict] = []
    for node in world.nodes.values():
        value = node.to_dict()
        value.pop("thought_bubbles", None)
        value.pop("action_bullets", None)
        nodes.append(value)
    return {
        "id": world.id,
        "tick": int(world.tick),
        "attributes": json_copy(world.attributes),
        "nodes": nodes,
        "relationships": [edge.to_dict() for edge in world.relationships.values()],
        "active_actions": [
            world.active_actions[action_id].to_dict()
            for action_id in sorted(world.active_actions)
        ],
        "action_history": [
            action.to_dict() for action in world.action_history[-MAX_ACTION_HISTORY:]
        ],
        "action_sequence": int(world.action_sequence),
        "active_activities": [
            world.active_activities[item_id].to_dict()
            for item_id in sorted(world.active_activities)
        ],
        "activity_history": [
            item.to_dict() for item in world.activity_history[-MAX_ACTIVITY_HISTORY:]
        ],
        "activity_sequence": int(world.activity_sequence),
        "speech_events": json_copy(world.speech_events[-MAX_SPEECH_EVENTS:]),
        "errors": json_copy(world.errors[-100:]),
    }


def world_state_delta(before: JsonDict, after: JsonDict) -> JsonDict:
    """Compute a deterministic replacement patch between compact snapshots."""

    before_nodes = _by_id(before.get("nodes"), "id")
    after_nodes = _by_id(after.get("nodes"), "id")
    before_edges = _by_relationship(before.get("relationships"))
    after_edges = _by_relationship(after.get("relationships"))
    changed_nodes = [
        json_copy(after_nodes[key])
        for key in sorted(after_nodes)
        if before_nodes.get(key) != after_nodes[key]
    ]
    changed_edges = [
        json_copy(after_edges[key])
        for key in sorted(after_edges)
        if before_edges.get(key) != after_edges[key]
    ]
    result: JsonDict = {
        "tick": int(after.get("tick", 0) or 0),
        "upsert_nodes": changed_nodes,
        "delete_node_ids": sorted(set(before_nodes) - set(after_nodes)),
        "upsert_relationships": changed_edges,
        "delete_relationship_keys": sorted(set(before_edges) - set(after_edges)),
    }
    for field_name in (
        "id",
        "attributes",
        "active_actions",
        "action_history",
        "action_sequence",
        "active_activities",
        "activity_history",
        "activity_sequence",
        "speech_events",
        "errors",
    ):
        if before.get(field_name) != after.get(field_name):
            result[field_name] = json_copy(after.get(field_name))
    return result


def apply_world_state_delta(snapshot: JsonDict, delta: JsonDict) -> JsonDict:
    """Apply a TickCommit state patch to a compact snapshot."""

    result = json_copy(snapshot)
    result["tick"] = int(delta.get("tick", result.get("tick", 0)) or 0)
    for field_name in (
        "id",
        "attributes",
        "active_actions",
        "action_history",
        "action_sequence",
        "active_activities",
        "activity_history",
        "activity_sequence",
        "speech_events",
        "errors",
    ):
        if field_name in delta:
            result[field_name] = json_copy(delta.get(field_name))

    nodes = _by_id(result.get("nodes"), "id")
    for node_id in _list(delta.get("delete_node_ids")):
        nodes.pop(str(node_id), None)
    for raw_node in _list(delta.get("upsert_nodes")):
        node = _dict(raw_node)
        node_id = str(node.get("id", ""))
        if node_id:
            nodes[node_id] = json_copy(node)
    result["nodes"] = list(nodes.values())

    edges = _by_relationship(result.get("relationships"))
    for edge_key in _list(delta.get("delete_relationship_keys")):
        edges.pop(str(edge_key), None)
    for raw_edge in _list(delta.get("upsert_relationships")):
        edge = _dict(raw_edge)
        key = _relationship_key(edge)
        if key:
            edges[key] = json_copy(edge)
    result["relationships"] = list(edges.values())
    return result


def replay_tick_commits(
    snapshot: JsonDict, commits: Iterable[TickCommit | JsonDict]
) -> tuple[JsonDict, int, str]:
    """Replay unique monotonic commits and reject divergent duplicate sequences."""

    result = json_copy(snapshot)
    seen: dict[int, str] = {}
    last_sequence = 0
    phase = "running"
    normalized = [
        item if isinstance(item, TickCommit) else TickCommit.from_dict(item)
        for item in commits
    ]
    for commit in sorted(normalized, key=lambda item: item.sequence):
        existing = seen.get(commit.sequence)
        if existing is not None:
            if existing != commit.checksum:
                raise ValueError(
                    f"divergent TickCommit sequence: {commit.sequence}"
                )
            continue
        if commit.sequence <= last_sequence:
            raise ValueError(f"non-monotonic TickCommit sequence: {commit.sequence}")
        result = apply_world_state_delta(result, commit.state_delta)
        seen[commit.sequence] = commit.checksum
        last_sequence = commit.sequence
        phase = commit.resulting_phase
    return result, last_sequence, phase


def world_from_compact_snapshot(
    snapshot: JsonDict,
    *,
    events: list[JsonDict] | None = None,
    traces: list[JsonDict] | None = None,
) -> World:
    restored = json_copy(snapshot)
    restored["events"] = json_copy(events or [])
    restored["deltas"] = [
        json_copy(event)
        for event in events or []
        if str(event.get("kind", "")) == "state_delta"
    ]
    restored["traces"] = json_copy(traces or [])
    return World.from_snapshot(restored)


def _checksum(value: JsonDict) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _by_id(value: object, field_name: str) -> dict[str, JsonDict]:
    return {
        str(item.get(field_name, "")): json_copy(item)
        for item in _list(value)
        if isinstance(item, dict) and str(item.get(field_name, ""))
    }


def _by_relationship(value: object) -> dict[str, JsonDict]:
    return {
        key: json_copy(item)
        for item in _list(value)
        if isinstance(item, dict) and (key := _relationship_key(item))
    }


def _relationship_key(value: JsonDict) -> str:
    source = str(value.get("source", ""))
    target = str(value.get("target", ""))
    kind = str(value.get("type", ""))
    if not source or not target or not kind:
        return ""
    return RelationshipEdge(source=source, target=target, type=kind).key


def _range(value: object) -> tuple[int, int]:
    raw = value if isinstance(value, list) else []
    return (
        int(raw[0] or 0) if len(raw) > 0 else 0,
        int(raw[1] or 0) if len(raw) > 1 else 0,
    )


def _dict(value: object) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
