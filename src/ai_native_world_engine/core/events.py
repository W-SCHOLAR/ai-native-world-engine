"""事件、展示载荷和追踪账本。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonDict = dict[str, Any]


def json_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_copy(v) for v in value]
    if isinstance(value, tuple):
        return [json_copy(v) for v in value]
    return value


@dataclass(slots=True)
class EventRecord:
    sequence: int
    tick: int
    kind: str
    source: str
    payload: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "sequence": self.sequence,
            "tick": self.tick,
            "kind": self.kind,
            "source": self.source,
            "payload": json_copy(self.payload),
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "EventRecord":
        return cls(
            sequence=int(value.get("sequence", 0) or 0),
            tick=int(value.get("tick", 0) or 0),
            kind=str(value.get("kind", "")),
            source=str(value.get("source", "unknown")),
            payload=json_copy(value.get("payload", {})) if isinstance(value.get("payload"), dict) else {},
        )


@dataclass(slots=True)
class ThoughtBubble:
    node_id: str
    text: str
    source: str = "system"
    mood: str = ""
    salience: float = 0.5
    ttl: float = 6.0
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result = {
            "type": "thought_bubble",
            "node_id": self.node_id,
            "text": self.text,
            "source": self.source,
            "mood": self.mood,
            "salience": self.salience,
            "ttl": self.ttl,
        }
        result.update(json_copy(self.metadata))
        return result


@dataclass(slots=True)
class ActionBullet:
    node_id: str
    text: str
    source: str = "system"
    salience: float = 0.5
    ttl: float = 4.0
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result = {
            "type": "action_bullet",
            "node_id": self.node_id,
            "text": self.text,
            "source": self.source,
            "salience": self.salience,
            "ttl": self.ttl,
        }
        result.update(json_copy(self.metadata))
        return result


@dataclass(slots=True)
class SpeechBubble:
    node_id: str
    text: str
    source: str = "system"
    speech_event_id: str = ""
    conversation_id: str = ""
    target_ids: list[str] = field(default_factory=list)
    ttl: float = 4.0
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result = {
            "type": "speech_bubble",
            "node_id": self.node_id,
            "text": self.text,
            "source": self.source,
            "speech_event_id": self.speech_event_id,
            "conversation_id": self.conversation_id,
            "target_ids": json_copy(self.target_ids),
            "ttl": self.ttl,
        }
        result.update(json_copy(self.metadata))
        return result


class EventStream:
    def __init__(self) -> None:
        self._next_sequence = 1
        self._events: list[EventRecord] = []
        self._deltas: list[EventRecord] = []

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    @property
    def count(self) -> int:
        return len(self._events)

    @classmethod
    def from_records(cls, events: list[JsonDict], deltas: list[JsonDict] | None = None) -> "EventStream":
        stream = cls()
        stream._events = [EventRecord.from_dict(event) for event in events if isinstance(event, dict)]
        if deltas is None:
            stream._deltas = [event for event in stream._events if event.kind == "state_delta"]
        else:
            stream._deltas = [EventRecord.from_dict(delta) for delta in deltas if isinstance(delta, dict)]
        max_sequence = max((event.sequence for event in [*stream._events, *stream._deltas]), default=0)
        stream._next_sequence = max_sequence + 1
        return stream

    def record(
        self,
        tick: int,
        kind: str,
        source: str,
        payload: JsonDict | None = None,
    ) -> EventRecord:
        record = EventRecord(
            sequence=self._next_sequence,
            tick=tick,
            kind=kind,
            source=source or "unknown",
            payload=json_copy(payload or {}),
        )
        self._next_sequence += 1
        self._events.append(record)
        return record

    def record_delta(
        self,
        tick: int,
        source: str,
        payload: JsonDict | None = None,
    ) -> EventRecord:
        record = EventRecord(
            sequence=self._next_sequence,
            tick=tick,
            kind="state_delta",
            source=source or "unknown",
            payload=json_copy(payload or {}),
        )
        self._next_sequence += 1
        self._deltas.append(record)
        self._events.append(record)
        return record

    def recent(self, limit: int | None = None) -> list[JsonDict]:
        if limit is not None and limit <= 0:
            return []
        events = self._events if limit is None else self._events[-limit:]
        return [event.to_dict() for event in events]

    def recent_deltas(self, limit: int | None = None) -> list[JsonDict]:
        if limit is not None and limit <= 0:
            return []
        deltas = self._deltas if limit is None else self._deltas[-limit:]
        return [delta.to_dict() for delta in deltas]

    def since_index(self, index: int) -> list[JsonDict]:
        """Copy records appended at or after a zero-based in-memory cursor."""

        return [event.to_dict() for event in self._events[max(int(index), 0) :]]


@dataclass(slots=True)
class TraceRecord:
    tick: int
    kind: str
    source: str
    observed: JsonDict = field(default_factory=dict)
    candidates: list[JsonDict] = field(default_factory=list)
    selected: JsonDict = field(default_factory=dict)
    delta: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "tick": self.tick,
            "kind": self.kind,
            "source": self.source,
            "observed": json_copy(self.observed),
            "candidates": json_copy(self.candidates),
            "selected": json_copy(self.selected),
            "delta": json_copy(self.delta),
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "TraceRecord":
        return cls(
            tick=int(value.get("tick", 0) or 0),
            kind=str(value.get("kind", "")),
            source=str(value.get("source", "unknown")),
            observed=json_copy(value.get("observed", {})) if isinstance(value.get("observed"), dict) else {},
            candidates=json_copy(value.get("candidates", [])) if isinstance(value.get("candidates"), list) else [],
            selected=json_copy(value.get("selected", {})) if isinstance(value.get("selected"), dict) else {},
            delta=json_copy(value.get("delta", {})) if isinstance(value.get("delta"), dict) else {},
        )


class TraceLedger:
    def __init__(self) -> None:
        self._records: list[TraceRecord] = []

    @classmethod
    def from_records(cls, records: list[JsonDict]) -> "TraceLedger":
        ledger = cls()
        ledger._records = [TraceRecord.from_dict(record) for record in records if isinstance(record, dict)]
        return ledger

    def record(self, record: TraceRecord) -> TraceRecord:
        self._records.append(record)
        return record

    @property
    def count(self) -> int:
        return len(self._records)

    def recent(self, limit: int | None = None) -> list[JsonDict]:
        if limit is not None and limit <= 0:
            return []
        records = self._records if limit is None else self._records[-limit:]
        return [record.to_dict() for record in records]

    def all(self) -> list[TraceRecord]:
        return list(self._records)

    def since_index(self, index: int) -> list[JsonDict]:
        """Copy records appended at or after a zero-based in-memory cursor."""

        return [record.to_dict() for record in self._records[max(int(index), 0) :]]
