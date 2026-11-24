"""Bounded keyframe/delta records for live Viewer timelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .events import json_copy
from .incremental import apply_world_state_delta, compact_world_snapshot
from .world import World


JsonDict = dict[str, Any]
PROJECTION_KEYFRAME_SCHEMA = "ai-native-world.projection-keyframe.v2"
PROJECTION_DELTA_SCHEMA = "ai-native-world.projection-delta.v2"


@dataclass(slots=True)
class ProjectionDelta:
    sequence: int
    tick: int
    world_patch: JsonDict
    thought_schedules: list[JsonDict] = field(default_factory=list)
    action_visuals: list[JsonDict] = field(default_factory=list)
    speech_bubbles: list[JsonDict] = field(default_factory=list)
    expirations: list[JsonDict] = field(default_factory=list)
    summary_patch: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "schema": PROJECTION_DELTA_SCHEMA,
            "sequence": int(self.sequence),
            "tick": int(self.tick),
            "world_patch": json_copy(self.world_patch),
            "thought_schedules": json_copy(self.thought_schedules),
            "action_visuals": json_copy(self.action_visuals),
            "speech_bubbles": json_copy(self.speech_bubbles),
            "expirations": json_copy(self.expirations),
            "summary_patch": json_copy(self.summary_patch),
        }


def projection_keyframe(world: World, sequence: int = 0) -> JsonDict:
    return {
        "schema": PROJECTION_KEYFRAME_SCHEMA,
        "sequence": max(int(sequence), 0),
        "tick": int(world.tick),
        "world_state": compact_world_snapshot(world),
        "thought_schedules": [],
        "action_visuals": [],
        "speech_bubbles": [],
        "summary": {
            "world_id": world.id,
            "tick": int(world.tick),
            "node_count": len(world.nodes),
            "relationship_count": len(world.relationships),
        },
    }


def projection_delta_from_incremental(incremental: JsonDict) -> ProjectionDelta:
    commit = _dict(incremental.get("commit"))
    # Presentation events have a delivery-only lifetime. They are deliberately
    # distinct from authoritative events so bubbles cannot re-enter causal
    # recovery, model memory, or world snapshots.
    events = [
        item
        for item in _list(incremental.get("presentation_events"))
        if isinstance(item, dict)
    ]
    schedules: list[JsonDict] = []
    visuals: list[JsonDict] = []
    speech_bubbles: list[JsonDict] = []
    scheduled_at = datetime.now(timezone.utc)
    for event in events:
        payload = _dict(event.get("payload"))
        payload_type = str(payload.get("type", ""))
        if payload_type == "thought_schedule":
            schedule = json_copy(payload)
            schedule["scheduled_at"] = scheduled_at.isoformat()
            occurrences = []
            for raw_occurrence in _list(schedule.get("occurrences")):
                occurrence = _dict(raw_occurrence)
                if not occurrence:
                    continue
                display_at = scheduled_at + timedelta(
                    seconds=max(
                        float(occurrence.get("delay", 0.0) or 0.0), 0.0
                    )
                )
                occurrence["display_at"] = display_at.isoformat()
                occurrence["expires_at"] = (
                    display_at
                    + timedelta(
                        seconds=max(
                            float(occurrence.get("duration", 4.0) or 4.0),
                            0.0,
                        )
                    )
                ).isoformat()
                occurrences.append(occurrence)
            if occurrences:
                schedule["occurrences"] = occurrences
            schedules.append(
                {
                    **schedule,
                    "sequence": int(event.get("sequence", 0) or 0),
                    "tick": int(event.get("tick", 0) or 0),
                }
            )
        elif payload_type == "thought_bubble":
            # Legacy and key-character providers still emit immediate thought
            # bubbles. The live Web path consumes compact schedules only, so
            # adapt the bubble into one stable, acknowledgeable occurrence.
            sequence = int(event.get("sequence", 0) or 0)
            tick = int(event.get("tick", 0) or 0)
            node_id = str(payload.get("node_id", ""))
            text = str(payload.get("text", ""))
            delay = max(float(payload.get("delay", 0.0) or 0.0), 0.0)
            duration = max(float(payload.get("ttl", 6.0) or 6.0), 0.0)
            display_at = scheduled_at + timedelta(seconds=delay)
            expires_at = display_at + timedelta(seconds=duration)
            occurrence = {
                "occurrence_id": str(
                    payload.get("occurrence_id")
                    or f"thought:{sequence}:{node_id}:0"
                ),
                "node_id": node_id,
                "slice_index": int(payload.get("sequence_index", 0) or 0),
                "text": text,
                "delay": delay,
                "duration": duration,
                "display_at": display_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": "scheduled",
            }
            for key in (
                "origin",
                "ripple_from",
                "cognition_id",
                "generation",
                "causality_id",
                "root_causality_id",
                "caused_by",
            ):
                if key in payload:
                    occurrence[key] = json_copy(payload[key])
            schedules.append(
                {
                    **json_copy(payload),
                    "type": "thought_schedule",
                    "sequence": sequence,
                    "tick": tick,
                    "slice_count": 1,
                    "explicit_slices": [text],
                    "scheduled_at": scheduled_at.isoformat(),
                    "occurrences": [occurrence],
                }
            )
        elif payload_type == "action_bullet":
            visuals.append(
                {
                    **json_copy(payload),
                    "sequence": int(event.get("sequence", 0) or 0),
                    "tick": int(event.get("tick", 0) or 0),
                }
            )
        elif payload_type == "speech_bubble":
            speech_bubbles.append(
                {
                    **json_copy(payload),
                    "sequence": int(event.get("sequence", 0) or 0),
                    "tick": int(event.get("tick", 0) or 0),
                }
            )
    world_patch = _dict(commit.get("state_delta"))
    return ProjectionDelta(
        sequence=int(commit.get("sequence", 0) or 0),
        tick=int(commit.get("resulting_tick", 0) or 0),
        world_patch=world_patch,
        thought_schedules=schedules,
        action_visuals=visuals,
        speech_bubbles=speech_bubbles,
        summary_patch={
            "tick": int(commit.get("resulting_tick", 0) or 0),
            "phase": str(commit.get("resulting_phase", "running")),
        },
    )


def apply_projection_delta(keyframe: JsonDict, delta: JsonDict) -> JsonDict:
    result = json_copy(keyframe)
    result["sequence"] = int(
        delta.get("sequence", result.get("sequence", 0)) or 0
    )
    result["tick"] = int(delta.get("tick", result.get("tick", 0)) or 0)
    result["world_state"] = apply_world_state_delta(
        _dict(result.get("world_state")), _dict(delta.get("world_patch"))
    )
    result["summary"] = {
        **_dict(result.get("summary")),
        **_dict(delta.get("summary_patch")),
    }
    result["thought_schedules"] = _bounded_visuals(
        [
            *_list(result.get("thought_schedules")),
            *_list(delta.get("thought_schedules")),
        ],
        result["tick"],
        1024,
    )
    result["action_visuals"] = _bounded_visuals(
        [
            *_list(result.get("action_visuals")),
            *_list(delta.get("action_visuals")),
        ],
        result["tick"],
        256,
    )
    result["speech_bubbles"] = _bounded_visuals(
        [
            *_list(result.get("speech_bubbles")),
            *_list(delta.get("speech_bubbles")),
        ],
        result["tick"],
        256,
    )
    return result


def _bounded_visuals(rows: list[Any], current_tick: int, limit: int) -> list[JsonDict]:
    """Keep locally deliverable occurrences out of the simulation clock.

    ``delay`` and ``ttl`` are browser seconds.  Comparing them to a world tick
    previously discarded a six-slice schedule while its later wall-clock
    slices were still queued.  Delivery/consumption owns expiry; this bounded
    projection cache only constrains memory use.
    """

    active = []
    for item in rows:
        row = _dict(item)
        if not row:
            continue
        active.append(row)
    return json_copy(active[-max(int(limit), 1) :])


def _dict(value: object) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
