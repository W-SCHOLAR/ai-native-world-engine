"""Deterministic, presentation-only pacing for relationship cognition."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from .events import json_copy
from .feedback import WorldEffect


JsonDict = dict[str, Any]

NORMAL_PRESENTATION_SECONDS = 60
NORMAL_PRESENTATION_ROUNDS = 6
NORMAL_PRESENTATION_SLOTS_PER_ROUND = 10
NORMAL_BUBBLE_DURATION_SECONDS = 4.0
NORMAL_RIPPLE_DURATION_SECONDS = 6.0
NORMAL_ACTIVE_STARTS_PER_SECOND = 10
NORMAL_RIPPLE_STARTS_PER_SECOND = 5
NORMAL_TOTAL_STARTS_PER_SECOND = (
    NORMAL_ACTIVE_STARTS_PER_SECOND + NORMAL_RIPPLE_STARTS_PER_SECOND
)
NORMAL_JITTER_MIN_SECONDS = 0.0
NORMAL_JITTER_MAX_SECONDS = 1.0
NORMAL_SAME_NODE_MIN_START_GAP_SECONDS = 10.0
NORMAL_ACTIVE_SCHEDULES_PER_GRAPH = 10
NORMAL_RIPPLE_SCHEDULES_PER_GRAPH = 30

_STRONG_PUNCTUATION = frozenset("。！？；.!?;")
_WEAK_PUNCTUATION = frozenset("，、：,:")
_MIN_SEMANTIC_SLICE_CHARACTERS = 6


def split_thought_for_presentation(text: str, count: int = 6) -> list[str]:
    """Split prose into at most ``count`` readable punctuation clauses."""

    clean = " ".join(str(text).split()) or "保持观察。"
    limit = max(int(count), 1)
    pieces = [
        clause
        for sentence in _split_after_marks(clean, _STRONG_PUNCTUATION)
        for clause in _split_after_marks(sentence, _WEAK_PUNCTUATION)
    ]
    pieces = _merge_short_semantic_pieces(pieces)
    while len(pieces) > limit:
        index = min(
            range(len(pieces) - 1),
            key=lambda item: (len(pieces[item]) + len(pieces[item + 1]), item),
        )
        pieces[index : index + 2] = [pieces[index] + pieces[index + 1]]
    return [piece for piece in pieces if piece]


def plan_normal_relationship_presentation(
    grouped_effects: list[tuple[int, list[WorldEffect]]],
    *,
    epoch_id: str,
    generation: int,
    seed: str,
) -> list[WorldEffect]:
    """Pace every active and ripple schedule from a normal cognition epoch."""

    active, ripple = _dense_schedule_records(grouped_effects)
    if not active and not ripple:
        return []
    active_ranks = _rank_records(active, f"{seed}:active")
    ripple_ranks = _rank_records(ripple, f"{seed}:ripple")
    planned: list[WorldEffect] = []
    for record in [*active, *ripple]:
        item = record[2]
        origin = str(item.fields.get("origin", "active_node"))
        rank = (
            ripple_ranks[_record_key(record)]
            if origin == "ripple_response"
            else active_ranks[_record_key(record)]
        )
        planned.append(
            _plan_schedule(
                record,
                rank=rank,
                epoch_id=epoch_id,
                generation=generation,
            )
        )
    return planned


def plan_incremental_relationship_presentation(
    effects: list[WorldEffect],
    *,
    graph_order: int,
    epoch_id: str,
    generation: int,
    seed: str,
) -> list[WorldEffect]:
    """Pace one completed graph without waiting for its epoch siblings.

    The graph-order offsets reserve the same minute-wide active/ripple lanes
    regardless of sibling completion order.  This lets live cognition stream
    as soon as a provider result is ready while keeping occurrence identities
    deterministic across recovery.
    """

    active, ripple = _dense_schedule_records([(int(graph_order), effects)])
    if not active and not ripple:
        return []
    local_active_ranks = _rank_records(active, f"{seed}:active:{graph_order}")
    local_ripple_ranks = _rank_records(ripple, f"{seed}:ripple:{graph_order}")
    planned: list[WorldEffect] = []
    for record in [*active, *ripple]:
        item = record[2]
        origin = str(item.fields.get("origin", "active_node"))
        if origin == "ripple_response":
            rank = (
                int(graph_order) * NORMAL_RIPPLE_SCHEDULES_PER_GRAPH
                + local_ripple_ranks[_record_key(record)]
            )
        else:
            rank = (
                int(graph_order) * NORMAL_ACTIVE_SCHEDULES_PER_GRAPH
                + local_active_ranks[_record_key(record)]
            )
        planned.append(
            _plan_schedule(
                record,
                rank=rank,
                epoch_id=epoch_id,
                generation=generation,
            )
        )
    return planned


def _dense_schedule_records(
    grouped_effects: list[tuple[int, list[WorldEffect]]],
) -> tuple[
    list[tuple[int, int, WorldEffect]],
    list[tuple[int, int, WorldEffect]],
]:
    active: list[tuple[int, int, WorldEffect]] = []
    ripple: list[tuple[int, int, WorldEffect]] = []
    for graph_order, effects in sorted(grouped_effects, key=lambda item: item[0]):
        graph_active: list[tuple[int, int, WorldEffect]] = []
        graph_ripple: list[tuple[int, int, WorldEffect]] = []
        for effect_index, item in enumerate(effects):
            if item.type != "thought_schedule_add" or not _effect_node_id(item):
                continue
            record = (int(graph_order), effect_index, item)
            if str(item.fields.get("origin", "active_node")) == "ripple_response":
                graph_ripple.append(record)
            else:
                graph_active.append(record)
        active.extend(graph_active[:NORMAL_ACTIVE_SCHEDULES_PER_GRAPH])
        ripple.extend(graph_ripple[:NORMAL_RIPPLE_SCHEDULES_PER_GRAPH])
    return active, ripple


def _rank_records(
    records: list[tuple[int, int, WorldEffect]], seed: str
) -> dict[tuple[int, int], int]:
    ordered = sorted(
        records,
        key=lambda record: (
            _stable_rank(
                f"{seed}:{record[0]}:{record[1]}:{_effect_node_id(record[2])}:"
                f"{record[2].fields.get('ripple_from', '')}"
            ),
            record[0],
            record[1],
            _effect_node_id(record[2]),
        ),
    )
    return {_record_key(record): rank for rank, record in enumerate(ordered)}


def _record_key(record: tuple[int, int, WorldEffect]) -> tuple[int, int]:
    return record[0], record[1]


def _plan_schedule(
    record: tuple[int, int, WorldEffect],
    *,
    rank: int,
    epoch_id: str,
    generation: int,
) -> WorldEffect:
    graph_order, effect_index, item = record
    fields = json_copy(item.fields)
    node_id = _effect_node_id(item)
    origin = str(fields.get("origin", "active_node"))
    is_ripple = origin == "ripple_response"
    if is_ripple:
        slices = [str(fields.get("text", "")).strip() or "我也会继续观察。"]
    else:
        slices = [
            str(value).strip()
            for value in fields.get("explicit_slices", [])
            if str(value).strip()
        ]
        if not slices:
            slices = split_thought_for_presentation(
                str(fields.get("text", "保持观察。")),
                NORMAL_PRESENTATION_ROUNDS,
            )
        slices = slices[:NORMAL_PRESENTATION_ROUNDS]
    duration = (
        NORMAL_RIPPLE_DURATION_SECONDS
        if is_ripple
        else NORMAL_BUBBLE_DURATION_SECONDS
    )
    occurrences: list[JsonDict] = []
    for slice_index, slice_text in enumerate(slices):
        if is_ripple:
            second = rank % NORMAL_PRESENTATION_SECONDS
            lane = NORMAL_ACTIVE_STARTS_PER_SECOND + (
                rank // NORMAL_PRESENTATION_SECONDS
            )
        else:
            round_seconds = max(NORMAL_PRESENTATION_SECONDS // len(slices), 1)
            second = min(
                slice_index * round_seconds + rank % round_seconds,
                NORMAL_PRESENTATION_SECONDS - 1,
            )
            lane = rank // round_seconds
        subsecond = (lane + 0.5) / NORMAL_TOTAL_STARTS_PER_SECOND
        delay = round(second + subsecond, 3)
        occurrence_id = (
            f"{epoch_id}:{int(generation)}:{origin}:{graph_order}:"
            f"{effect_index}:{node_id}:{slice_index}"
        )
        occurrences.append(
            {
                "occurrence_id": occurrence_id,
                "node_id": node_id,
                "slice_index": slice_index,
                "text": slice_text,
                "stratum": second,
                "delay": delay,
                "duration": duration,
                "status": "scheduled",
                "origin": origin,
                "ripple_from": str(fields.get("ripple_from", "")),
            }
        )
    cognition_id = (
        f"{epoch_id}:{int(generation)}:{origin}:{graph_order}:{effect_index}:{node_id}"
    )
    influence_targets = [
        str(value.get("node_id", ""))
        for value in fields.get("ripple_targets", [])
        if isinstance(value, dict) and str(value.get("node_id", ""))
    ]
    fields.update(
        {
            "cognition_id": cognition_id,
            "generation": int(generation),
            "presentation_epoch_id": epoch_id,
            "presentation_graph_order": int(graph_order),
            "presentation_schedule_index": int(effect_index),
            "priority": "periodic_relationship",
            "full_text": str(fields.get("text", "")),
            "explicit_slices": slices,
            "slice_count": len(slices),
            "ttl": duration,
            "delay": occurrences[0]["delay"] if occurrences else 0.0,
            "interval": 0.0,
            "occurrences": occurrences,
            "influence_targets": influence_targets,
            "origin": origin,
        }
    )
    return WorldEffect("thought_schedule_add", fields)


def _split_after_marks(text: str, marks: frozenset[str]) -> list[str]:
    pieces: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character in marks:
            pieces.append(text[start : index + 1])
            start = index + 1
    if start < len(text):
        pieces.append(text[start:])
    return [piece for piece in pieces if piece]


def _merge_short_semantic_pieces(pieces: list[str]) -> list[str]:
    merged: list[str] = []
    pending = ""
    for piece in pieces:
        pending += piece
        if len(pending) >= _MIN_SEMANTIC_SLICE_CHARACTERS:
            merged.append(pending)
            pending = ""
    if pending:
        if merged:
            merged[-1] += pending
        else:
            merged.append(pending)
    return merged


def _effect_node_id(item: WorldEffect) -> str:
    value = str(item.fields.get("target", item.fields.get("node_id", "")))
    return value.split(":", 1)[1] if value.startswith("node:") else value


def _stable_rank(key: str) -> int:
    return int.from_bytes(sha256(key.encode("utf-8")).digest()[:8], "big")
