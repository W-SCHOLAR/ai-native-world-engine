"""Evaluation scorecards for reproducible runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .domain_state import WorldDomainStateInspector
from .events import json_copy
from .rules import WORLD_ECOSYSTEM_RULES
from .world_director import WORLD_DIRECTOR_SOURCE


JsonDict = dict[str, Any]

WORLD_ECOSYSTEM_GROUNDED_ACTIONS = {
    "combat_attack",
    "collaboration",
    "economic_exchange",
    "infection_progress",
    "infection_spread",
    "logistics_transfer",
    "migration",
    "organization_decision",
    "production",
    "quarantine_policy",
    "science_publish",
    "social_spread",
}


@dataclass(slots=True)
class Scorecard:
    score: float
    metrics: JsonDict = field(default_factory=dict)
    penalties: list[JsonDict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> JsonDict:
        return {
            "score": self.score,
            "metrics": json_copy(self.metrics),
            "penalties": json_copy(self.penalties),
            "summary": self.summary,
        }


def evaluate_run(result: Any) -> Scorecard:
    data = result.to_dict() if hasattr(result, "to_dict") else json_copy(result)
    if not isinstance(data, dict):
        raise TypeError("evaluate_run expects a RunResult or JSON-compatible dict")

    snapshot = _dict(data.get("snapshot"))
    report = _dict(data.get("pressure_action_report"))
    totals = _dict(report.get("totals"))
    provider_outcome = _dict(data.get("provider_outcome_report"))
    provider_outcome_totals = _dict(provider_outcome.get("totals"))
    config = _dict(data.get("config"))
    events = _list(data.get("events"))
    provider_outputs = _list(data.get("provider_outputs"))
    provider_audits = _list(data.get("provider_audits"))
    provider_execution = _dict(data.get("provider_execution_report"))
    provider_execution_totals = _dict(provider_execution.get("totals"))
    intervention_audits = _list(data.get("intervention_audits"))
    memory_consolidation_report = _list(data.get("memory_consolidation_report"))
    timeline = _list(data.get("timeline"))
    errors = _list(snapshot.get("errors"))
    goal_report = _goal_report(config, events)

    pressures = int(totals.get("pressures", 0) or 0)
    matched = int(totals.get("matched", 0) or 0)
    unmatched = int(totals.get("unmatched", 0) or 0)
    pending_observation = int(totals.get("pending_observation", 0) or 0)
    match_rate = float(totals.get("match_rate", 0.0) or 0.0)
    world_errors = len(errors)
    action_count = sum(1 for event in events if _dict(event.get("payload")).get("action"))
    movement_completed = _count_completed_movements(snapshot)
    runtime = _provider_runtime(provider_outputs)
    governance_rejections = sum(1 for audit in provider_audits if _dict(audit).get("accepted") is False)
    intervention_errors = sum(int(_dict(audit).get("error_count", 0) or 0) for audit in intervention_audits)
    provider_unmatched_pressures = int(provider_outcome_totals.get("unmatched_pressures", 0) or 0)
    provider_pending_observation = int(
        provider_outcome_totals.get("pending_observation", 0) or 0
    )
    provider_outcome_pressures = int(provider_outcome_totals.get("pressures", 0) or 0)
    provider_alignment_rate = float(provider_outcome_totals.get("alignment_rate", 0.0) or 0.0)
    domain_report = _domain_report(snapshot)
    domain_issues = int(domain_report.get("issue_count", 0) or 0)
    domain_summary = _dict(domain_report.get("summary"))
    domain_risk = _dict(domain_summary.get("risk"))
    domain_infection = _dict(domain_summary.get("infection"))
    domain_resources = _dict(domain_summary.get("resources"))
    domain_coverage = _dict(domain_summary.get("domain_model_coverage"))
    memory_maintenance = _memory_maintenance(memory_consolidation_report)
    enabled_rules = [str(item) for item in _list(config.get("rules"))]
    ecosystem_rule_coverage = _ecosystem_rule_coverage(enabled_rules)
    director_activity = _world_director_activity(provider_outputs)
    action_coverage = _grounded_action_coverage(events)

    penalties: list[JsonDict] = []
    if unmatched:
        penalties.append(
            {
                "kind": "unmatched_pressure",
                "count": unmatched,
                "points": unmatched * 10,
                "reason": "pressure did not match a later grounded action",
            }
        )
    if world_errors:
        penalties.append(
            {
                "kind": "world_error",
                "count": world_errors,
                "points": world_errors * 25,
                "reason": "world recorded feedback application errors",
            }
        )
    if governance_rejections:
        penalties.append(
            {
                "kind": "provider_governance_rejection",
                "count": governance_rejections,
                "points": governance_rejections * 5,
                "reason": "provider output was rejected by governance boundary",
            }
        )
    if domain_issues:
        penalties.append(
            {
                "kind": "domain_state_issue",
                "count": domain_issues,
                "points": domain_issues * 15,
                "reason": "world snapshot contains invalid domain state",
            }
        )
    if goal_report["missing_required_actions"]:
        missing_count = len(goal_report["missing_required_actions"])
        penalties.append(
            {
                "kind": "missing_required_action",
                "count": missing_count,
                "points": missing_count * 8,
                "reason": "scenario required action was not observed in the event stream",
                "missing_actions": json_copy(goal_report["missing_required_actions"]),
            }
        )

    score = max(0.0, min(100.0, 100.0 - sum(float(item["points"]) for item in penalties)))
    metrics: JsonDict = {
        "pressure_match_rate": match_rate,
        "pressures": pressures,
        "matched_pressures": matched,
        "unmatched_pressures": unmatched,
        "pending_pressure_observations": pending_observation,
        "world_errors": world_errors,
        "action_count": action_count,
        "action_counts_by_type": json_copy(action_coverage["counts_by_type"]),
        "grounded_action_class_count": action_coverage["grounded_action_class_count"],
        "world_ecosystem_action_coverage": action_coverage["world_ecosystem_action_coverage"],
        "world_ecosystem_actions_hit": json_copy(action_coverage["world_ecosystem_actions_hit"]),
        "world_ecosystem_actions_missing": json_copy(action_coverage["world_ecosystem_actions_missing"]),
        "movement_completed": movement_completed,
        "provider_outputs": len(provider_outputs),
        "provider_attempts": runtime["attempts"],
        "provider_estimated_cost": runtime["estimated_cost"],
        "provider_latency_ms": runtime["latency_ms"],
        "provider_governance_rejections": governance_rejections,
        "provider_profile_providers": int(provider_execution_totals.get("providers", 0) or 0),
        "provider_profile_outputs": int(provider_execution_totals.get("outputs", 0) or 0),
        "provider_profile_attempts": int(provider_execution_totals.get("attempts", 0) or 0),
        "provider_profile_estimated_cost": float(provider_execution_totals.get("estimated_cost", 0.0) or 0.0),
        "provider_profile_latency_ms": float(provider_execution_totals.get("latency_ms", 0.0) or 0.0),
        "provider_profile_effect_count": int(provider_execution_totals.get("effect_count", 0) or 0),
        "provider_profile_accepted_audits": int(provider_execution_totals.get("accepted_audits", 0) or 0),
        "provider_profile_rejected_audits": int(provider_execution_totals.get("rejected_audits", 0) or 0),
        "provider_profile_failures": int(provider_execution_totals.get("failures", 0) or 0),
        "provider_profile_alignment_rate": float(provider_execution_totals.get("outcome_alignment_rate", 0.0) or 0.0),
        "provider_outcome_alignment_rate": provider_alignment_rate,
        "provider_outcome_pressures": provider_outcome_pressures,
        "provider_unmatched_pressures": provider_unmatched_pressures,
        "provider_pending_observations": provider_pending_observation,
        "interventions": len(intervention_audits),
        "intervention_errors": intervention_errors,
        "timeline_frames": len(timeline),
        "domain_state_issues": domain_issues,
        "domain_risk_score": int(domain_risk.get("score", 0) or 0),
        "domain_risk_level": str(domain_risk.get("level", "low") or "low"),
        "domain_active_infections": int(domain_infection.get("active_count", 0) or 0),
        "domain_scarcity_nodes": int(domain_resources.get("scarcity_nodes", 0) or 0),
        "enabled_rule_count": len(enabled_rules),
        "world_ecosystem_rule_coverage": ecosystem_rule_coverage["coverage"],
        "world_ecosystem_enabled": ecosystem_rule_coverage["enabled"],
        "domain_covered_domains": int(domain_coverage.get("covered_domains", 0) or 0),
        "domain_model_coverage": json_copy(_dict(domain_coverage.get("by_domain"))),
        "world_director_outputs": director_activity["outputs"],
        "world_director_effects": director_activity["effects"],
        "memory_consolidated_nodes": memory_maintenance["consolidated_nodes"],
        "memory_summary_count": memory_maintenance["summary_count"],
        "memory_forgotten_count": memory_maintenance["forgotten_count"],
        "required_action_count": goal_report["required_action_count"],
        "required_action_hits": goal_report["required_action_hits"],
        "required_action_coverage": goal_report["required_action_coverage"],
        "missing_required_actions": json_copy(goal_report["missing_required_actions"]),
        "ticks": int(snapshot.get("tick", config.get("ticks", 0)) or 0),
    }
    summary = (
        f"score={score:.1f}, pressure_match_rate={match_rate:.3f}, "
        f"unmatched_pressures={unmatched}, world_errors={world_errors}"
    )
    return Scorecard(round(score, 3), metrics, penalties, summary)


def _count_completed_movements(snapshot: JsonDict) -> int:
    return sum(
        1
        for node in _list(snapshot.get("nodes"))
        if _dict(node).get("attributes", {}).get("movement_arrived") is True
    )


def _provider_runtime(provider_outputs: list[Any]) -> JsonDict:
    attempts = 0
    estimated_cost = 0.0
    latency_ms = 0.0
    for output in provider_outputs:
        runtime = _dict(_dict(output).get("provider_runtime"))
        attempts += int(runtime.get("attempts", 0) or 0)
        estimated_cost += float(runtime.get("estimated_cost", 0.0) or 0.0)
        latency_ms += float(runtime.get("latency_ms", 0.0) or 0.0)
    return {
        "attempts": attempts,
        "estimated_cost": round(estimated_cost, 6),
        "latency_ms": round(latency_ms, 3),
    }


def _memory_maintenance(report: list[Any]) -> JsonDict:
    consolidated_nodes = 0
    summary_count = 0
    forgotten_count = 0
    for raw in report:
        item = _dict(raw)
        summary = _dict(item.get("summary"))
        if summary:
            consolidated_nodes += 1
        if summary.get("kind") == "memory_summary":
            summary_count += 1
        forgotten_count += int(summary.get("forgotten_count", 0) or 0)
    return {
        "consolidated_nodes": consolidated_nodes,
        "summary_count": summary_count,
        "forgotten_count": forgotten_count,
    }


def _domain_report(snapshot: JsonDict) -> JsonDict:
    try:
        inspector = WorldDomainStateInspector()
        report = inspector.validate_snapshot(snapshot).to_dict()
        report["summary"] = inspector.summarize_snapshot(snapshot).to_dict()
        return report
    except Exception:  # noqa: BLE001 - scorecard should not fail whole run on inspection fallback.
        return {"issue_count": 0, "issues": [], "summary": {"risk": {"score": 0, "level": "low"}}}


def _ecosystem_rule_coverage(enabled_rules: list[str]) -> JsonDict:
    enabled = set(enabled_rules)
    expected = set(WORLD_ECOSYSTEM_RULES)
    matched = len(enabled & expected)
    coverage = round(matched / len(expected), 4) if expected else 0.0
    return {
        "coverage": coverage,
        "enabled": coverage == 1.0,
    }


def _world_director_activity(provider_outputs: list[Any]) -> JsonDict:
    outputs = 0
    effects = 0
    for output in provider_outputs:
        item = _dict(output)
        if item.get("source") != WORLD_DIRECTOR_SOURCE:
            continue
        outputs += 1
        effects += len(_list(item.get("effects")))
    return {"outputs": outputs, "effects": effects}


def _grounded_action_coverage(events: list[Any]) -> JsonDict:
    counts: dict[str, int] = {}
    for event in events:
        payload = _dict(_dict(event).get("payload"))
        action = str(payload.get("action", "")).strip()
        actor_type = str(payload.get("actor_type", ""))
        if not action or actor_type not in {"node", "person"}:
            continue
        counts[action] = counts.get(action, 0) + 1
    hit = sorted(action for action in WORLD_ECOSYSTEM_GROUNDED_ACTIONS if action in counts)
    missing = sorted(action for action in WORLD_ECOSYSTEM_GROUNDED_ACTIONS if action not in counts)
    return {
        "counts_by_type": dict(sorted(counts.items())),
        "grounded_action_class_count": len(counts),
        "world_ecosystem_actions_hit": hit,
        "world_ecosystem_actions_missing": missing,
        "world_ecosystem_action_coverage": round(len(hit) / len(WORLD_ECOSYSTEM_GROUNDED_ACTIONS), 4),
    }


def _goal_report(config: JsonDict, events: list[Any]) -> JsonDict:
    goals = _dict(config.get("evaluation_goals"))
    required_actions = [str(item) for item in _list(goals.get("required_actions")) if str(item)]
    observed_actions = {
        str(_dict(_dict(event).get("payload")).get("action", ""))
        for event in events
        if _dict(_dict(event).get("payload")).get("action")
    }
    hits = [action for action in required_actions if action in observed_actions]
    missing = [action for action in required_actions if action not in observed_actions]
    required_count = len(required_actions)
    return {
        "required_action_count": required_count,
        "required_action_hits": len(hits),
        "required_action_coverage": round(len(hits) / required_count, 4) if required_count else 0.0,
        "missing_required_actions": missing,
    }


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
