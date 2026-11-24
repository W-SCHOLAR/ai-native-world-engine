"""Provider execution profile aggregation."""

from __future__ import annotations

from typing import Any

from .events import json_copy


JsonDict = dict[str, Any]


class ProviderExecutionProfiler:
    def build_report(
        self,
        provider_outputs: list[JsonDict],
        provider_audits: list[JsonDict],
        provider_outcome_report: JsonDict,
    ) -> JsonDict:
        rows: dict[str, JsonDict] = {}
        for output in provider_outputs:
            output_data = _dict(output)
            provider = _provider_name(output_data)
            row = _row(rows, provider)
            runtime = _dict(output_data.get("provider_runtime"))
            row["outputs"] += 1
            row["attempts"] += int(runtime.get("attempts", 0) or 0)
            row["estimated_cost"] += float(runtime.get("estimated_cost", 0.0) or 0.0)
            row["latency_ms"] += float(runtime.get("latency_ms", 0.0) or 0.0)
            row["effect_count"] += len(_list(output_data.get("effects")))
            row["accepted_outputs"] += 1

        for audit in provider_audits:
            audit_data = _dict(audit)
            provider = str(audit_data.get("provider_name", audit_data.get("provider_id", "unknown"))) or "unknown"
            row = _row(rows, provider)
            provider_id = str(audit_data.get("provider_id", ""))
            if provider_id:
                row["provider_ids"].add(provider_id)
            row["audits"] += 1
            row["raw_effect_count"] += int(audit_data.get("raw_effect_count", 0) or 0)
            row["accepted_effect_count"] += int(audit_data.get("accepted_effect_count", 0) or 0)
            if audit_data.get("accepted") is False:
                row["rejected_audits"] += 1
                if audit_data.get("error"):
                    row["failures"] += 1
            else:
                row["accepted_audits"] += 1

        for outcome in _list(_dict(provider_outcome_report).get("providers")):
            outcome_data = _dict(outcome)
            provider = str(outcome_data.get("provider", "unknown")) or "unknown"
            row = _row(rows, provider)
            row["outcome_pressures"] += int(outcome_data.get("pressures", 0) or 0)
            row["outcome_matched_pressures"] += int(outcome_data.get("matched_pressures", 0) or 0)
            row["outcome_unmatched_pressures"] += int(outcome_data.get("unmatched_pressures", 0) or 0)
            row["outcome_latency_ticks_total"] += float(outcome_data.get("average_latency_ticks", 0.0) or 0.0) * int(
                outcome_data.get("matched_pressures", 0) or 0
            )
            row["outcome_latency_samples"] += int(outcome_data.get("matched_pressures", 0) or 0)

        provider_rows = [_finalize(row) for _, row in sorted(rows.items())]
        totals = _totals(provider_rows)
        return {"totals": totals, "providers": provider_rows}


def _row(rows: dict[str, JsonDict], provider: str) -> JsonDict:
    if provider not in rows:
        rows[provider] = {
            "provider": provider,
            "provider_ids": set(),
            "outputs": 0,
            "accepted_outputs": 0,
            "attempts": 0,
            "estimated_cost": 0.0,
            "latency_ms": 0.0,
            "effect_count": 0,
            "audits": 0,
            "accepted_audits": 0,
            "rejected_audits": 0,
            "failures": 0,
            "raw_effect_count": 0,
            "accepted_effect_count": 0,
            "outcome_pressures": 0,
            "outcome_matched_pressures": 0,
            "outcome_unmatched_pressures": 0,
            "outcome_latency_ticks_total": 0.0,
            "outcome_latency_samples": 0,
        }
    return rows[provider]


def _finalize(row: JsonDict) -> JsonDict:
    pressures = int(row["outcome_pressures"])
    latency_samples = int(row["outcome_latency_samples"])
    return {
        "provider": row["provider"],
        "provider_ids": sorted(row["provider_ids"]),
        "outputs": int(row["outputs"]),
        "accepted_outputs": int(row["accepted_outputs"]),
        "attempts": int(row["attempts"]),
        "estimated_cost": round(float(row["estimated_cost"]), 6),
        "latency_ms": round(float(row["latency_ms"]), 3),
        "effect_count": int(row["effect_count"]),
        "audits": int(row["audits"]),
        "accepted_audits": int(row["accepted_audits"]),
        "rejected_audits": int(row["rejected_audits"]),
        "failures": int(row["failures"]),
        "raw_effect_count": int(row["raw_effect_count"]),
        "accepted_effect_count": int(row["accepted_effect_count"]),
        "outcome_pressures": pressures,
        "outcome_matched_pressures": int(row["outcome_matched_pressures"]),
        "outcome_unmatched_pressures": int(row["outcome_unmatched_pressures"]),
        "outcome_alignment_rate": round(float(row["outcome_matched_pressures"]) / pressures, 4) if pressures else 0.0,
        "average_outcome_latency_ticks": round(float(row["outcome_latency_ticks_total"]) / latency_samples, 4)
        if latency_samples
        else 0.0,
    }


def _totals(rows: list[JsonDict]) -> JsonDict:
    pressures = sum(int(row.get("outcome_pressures", 0) or 0) for row in rows)
    matched = sum(int(row.get("outcome_matched_pressures", 0) or 0) for row in rows)
    return {
        "providers": len(rows),
        "outputs": sum(int(row.get("outputs", 0) or 0) for row in rows),
        "attempts": sum(int(row.get("attempts", 0) or 0) for row in rows),
        "estimated_cost": round(sum(float(row.get("estimated_cost", 0.0) or 0.0) for row in rows), 6),
        "latency_ms": round(sum(float(row.get("latency_ms", 0.0) or 0.0) for row in rows), 3),
        "effect_count": sum(int(row.get("effect_count", 0) or 0) for row in rows),
        "audits": sum(int(row.get("audits", 0) or 0) for row in rows),
        "accepted_audits": sum(int(row.get("accepted_audits", 0) or 0) for row in rows),
        "rejected_audits": sum(int(row.get("rejected_audits", 0) or 0) for row in rows),
        "failures": sum(int(row.get("failures", 0) or 0) for row in rows),
        "outcome_pressures": pressures,
        "outcome_matched_pressures": matched,
        "outcome_unmatched_pressures": sum(int(row.get("outcome_unmatched_pressures", 0) or 0) for row in rows),
        "outcome_alignment_rate": matched / pressures if pressures else 0.0,
    }


def _provider_name(output: JsonDict) -> str:
    runtime = _dict(output.get("provider_runtime"))
    return str(runtime.get("provider", output.get("source", "unknown"))) or "unknown"


def _dict(value: Any) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
