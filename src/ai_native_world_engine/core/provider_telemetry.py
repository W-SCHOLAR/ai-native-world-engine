"""Secret-safe, call-local provider attempt records."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from .events import json_copy


JsonDict = dict[str, Any]
DEFAULT_PROVIDER_ATTEMPT_RETENTION = 100

_INTEGER_FIELDS = {
    "request_bytes",
    "response_bytes",
    "max_tokens",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "reasoning_chars",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "stable_prefix_bytes",
    "dynamic_message_bytes",
    "model_context_bytes",
    "model_context_l0_bytes",
    "model_context_l1_bytes",
    "model_context_l2_bytes",
    "evidence_candidate_count",
    "evidence_selected_count",
    "evidence_duplicate_suppressed_count",
}
_FLOAT_FIELDS = {
    "time_to_headers_ms",
    "body_read_ms",
    "response_json_decode_ms",
    "provider_output_extract_ms",
    "boundary_validation_ms",
    "total_latency_ms",
    "estimated_cost",
}
_STRING_FIELDS = {
    "finish_reason",
    "error_type",
    "status",
    "prompt_template_version",
    "stable_prefix_sha256",
    "model_context_projection",
}


def empty_provider_usage_totals() -> JsonDict:
    """Return the durable aggregate shape, independent of recent-row retention."""

    return {
        "attempts": 0,
        "completed": 0,
        "failed": 0,
        "timed_out": 0,
        "budget_rejected": 0,
        "estimated_cost": 0.0,
        **{field: 0 for field in _INTEGER_FIELDS},
        "latency_ms": 0.0,
    }


def accumulate_provider_usage(
    totals: JsonDict | None, attempts: list[JsonDict]
) -> JsonDict:
    """Fold safe attempt rows into a non-lossy Run aggregate."""

    result = empty_provider_usage_totals()
    for key, value in _dict(totals).items():
        if key in result and isinstance(value, (int, float)):
            result[key] = value
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        result["attempts"] += 1
        status = str(attempt.get("status", ""))
        if status in {"completed", "failed", "timed_out", "budget_rejected"}:
            result[status] += 1
        for field in _INTEGER_FIELDS:
            result[field] += int(attempt.get(field, 0) or 0)
        result["estimated_cost"] += float(attempt.get("estimated_cost", 0.0) or 0.0)
        result["latency_ms"] += float(attempt.get("total_latency_ms", 0.0) or 0.0)
    result["estimated_cost"] = round(float(result["estimated_cost"]), 6)
    result["latency_ms"] = round(float(result["latency_ms"]), 3)
    return result


def provider_attempts_from_output(output: JsonDict, ordinal: int = 0) -> list[JsonDict]:
    """Extract allowlisted attempt rows from one flattened ProviderOutput."""

    runtime = _dict(output.get("provider_runtime"))
    phases = _list_of_dicts(runtime.get("attempt_phases"))
    if not phases:
        return []
    scheduler = _dict(output.get("scheduler"))
    pending = _dict(output.get("provider_pending"))
    provider = str(runtime.get("provider") or output.get("source") or "unknown")
    model = str(runtime.get("model", ""))
    job_id = str(scheduler.get("job_id", ""))
    job_kind = str(scheduler.get("job_kind", ""))
    graph_key = str(scheduler.get("graph_key", ""))
    source_tick = int(
        pending.get("source_tick", scheduler.get("dispatched_tick", 0)) or 0
    )
    completed_tick = int(pending.get("completed_tick", source_tick) or source_tick)
    call_seed = f"{job_id or provider}:{source_tick}:{ordinal}"
    call_id = f"call-{sha256(call_seed.encode('utf-8')).hexdigest()[:20]}"
    rows: list[JsonDict] = []
    for index, raw_phase in enumerate(phases, start=1):
        attempt_index = int(raw_phase.get("attempt", index) or index)
        attempt_seed = f"{call_id}:{attempt_index}"
        row: JsonDict = {
            "attempt_id": f"attempt-{sha256(attempt_seed.encode('utf-8')).hexdigest()[:20]}",
            "call_id": call_id,
            "job_id": job_id,
            "job_kind": job_kind,
            "graph_key": graph_key,
            "source_tick": source_tick,
            "completed_tick": completed_tick,
            "provider": provider,
            "model": model,
            "attempt_index": attempt_index,
            "repair": attempt_index > 1,
            "status": str(raw_phase.get("status") or runtime.get("status") or "completed"),
        }
        for key in _INTEGER_FIELDS:
            if key in raw_phase and isinstance(raw_phase.get(key), (int, float)):
                row[key] = int(raw_phase[key])
        for key in _FLOAT_FIELDS:
            if key in raw_phase and isinstance(raw_phase.get(key), (int, float)):
                row[key] = round(float(raw_phase[key]), 3)
        for key in _STRING_FIELDS:
            if key in raw_phase:
                row[key] = str(raw_phase.get(key, ""))[:120]
        rows.append(row)
    return rows


def merge_provider_attempts(
    existing: list[JsonDict],
    additions: list[JsonDict],
    retention: int = DEFAULT_PROVIDER_ATTEMPT_RETENTION,
) -> tuple[list[JsonDict], int]:
    """Deduplicate attempt identities and retain a bounded newest suffix."""

    merged: list[JsonDict] = []
    seen: set[str] = set()
    for item in [*existing, *additions]:
        row = json_copy(item)
        attempt_id = str(row.get("attempt_id", ""))
        if not attempt_id or attempt_id in seen:
            continue
        seen.add(attempt_id)
        merged.append(row)
    limit = max(int(retention), 1)
    dropped = max(len(merged) - limit, 0)
    return merged[-limit:], dropped


def provider_attempt_totals(
    attempts: list[JsonDict],
    dropped: int = 0,
    cumulative: JsonDict | None = None,
) -> JsonDict:
    if cumulative is not None:
        result = accumulate_provider_usage(cumulative, [])
        result.update(
            {
                "retained_attempts": len(attempts),
                "dropped_attempts": max(int(dropped), 0),
            }
        )
        return result
    return {
        "attempts": len(attempts) + max(int(dropped), 0),
        "retained_attempts": len(attempts),
        "dropped_attempts": max(int(dropped), 0),
        "completed": sum(1 for item in attempts if item.get("status") == "completed"),
        "failed": sum(1 for item in attempts if item.get("status") == "failed"),
        "timed_out": sum(1 for item in attempts if item.get("status") == "timed_out"),
        "request_bytes": sum(int(item.get("request_bytes", 0) or 0) for item in attempts),
        "response_bytes": sum(int(item.get("response_bytes", 0) or 0) for item in attempts),
        "prompt_tokens": sum(int(item.get("prompt_tokens", 0) or 0) for item in attempts),
        "completion_tokens": sum(int(item.get("completion_tokens", 0) or 0) for item in attempts),
        "reasoning_tokens": sum(int(item.get("reasoning_tokens", 0) or 0) for item in attempts),
        "prompt_cache_hit_tokens": sum(
            int(item.get("prompt_cache_hit_tokens", 0) or 0) for item in attempts
        ),
        "prompt_cache_miss_tokens": sum(
            int(item.get("prompt_cache_miss_tokens", 0) or 0) for item in attempts
        ),
        "model_context_bytes": sum(int(item.get("model_context_bytes", 0) or 0) for item in attempts),
        "model_context_l0_bytes": sum(
            int(item.get("model_context_l0_bytes", 0) or 0) for item in attempts
        ),
        "model_context_l1_bytes": sum(
            int(item.get("model_context_l1_bytes", 0) or 0) for item in attempts
        ),
        "model_context_l2_bytes": sum(
            int(item.get("model_context_l2_bytes", 0) or 0) for item in attempts
        ),
        "evidence_candidate_count": sum(
            int(item.get("evidence_candidate_count", 0) or 0) for item in attempts
        ),
        "evidence_selected_count": sum(
            int(item.get("evidence_selected_count", 0) or 0) for item in attempts
        ),
        "evidence_duplicate_suppressed_count": sum(
            int(item.get("evidence_duplicate_suppressed_count", 0) or 0) for item in attempts
        ),
        "latency_ms": round(sum(float(item.get("total_latency_ms", 0.0) or 0.0) for item in attempts), 3),
    }


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[JsonDict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
