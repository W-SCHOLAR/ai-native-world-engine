"""Batch experiment matrices built on the run harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import json_copy
from .providers import AgentProvider
from .runner import RunConfig, run


JsonDict = dict[str, Any]


@dataclass(slots=True)
class ExperimentProviderConfig:
    name: str = ""
    provider: AgentProvider | None = None
    provider_params: JsonDict = field(default_factory=dict)
    govern_provider_output: bool = False
    provider_id: str = ""
    allowed_rule_names: list[str] = field(default_factory=list)
    allowed_relationship_types: list[str] = field(default_factory=list)
    provider_profile: JsonDict = field(default_factory=dict)

    def label(self) -> str:
        if self.name:
            return self.name
        if self.provider is not None:
            return self.provider.name
        return "deterministic-pressure"

    def to_dict(self) -> JsonDict:
        return {
            "name": self.label(),
            "provider": self.provider.name if self.provider is not None else None,
            "provider_params": json_copy(self.provider_params),
            "govern_provider_output": self.govern_provider_output,
            "provider_id": self.provider_id or _profile_id(self.provider_profile) or self.label(),
            "allowed_rule_names": json_copy(self.allowed_rule_names),
            "allowed_relationship_types": json_copy(self.allowed_relationship_types),
            "provider_profile": json_copy(self.provider_profile),
        }


@dataclass(slots=True)
class ExperimentConfig:
    scenario: str = "seed"
    seeds: list[int] = field(default_factory=lambda: [7])
    ticks: int = 3
    rules: list[str] = field(default_factory=lambda: ["movement"])
    providers: list[ExperimentProviderConfig] = field(default_factory=list)
    sort_by: str = "score"
    evaluation_goals: JsonDict = field(default_factory=dict)

    def provider_configs(self) -> list[ExperimentProviderConfig]:
        return self.providers or [ExperimentProviderConfig()]

    def to_dict(self) -> JsonDict:
        return {
            "scenario": self.scenario,
            "seeds": json_copy(self.seeds),
            "ticks": self.ticks,
            "rules": json_copy(self.rules),
            "providers": [provider.to_dict() for provider in self.provider_configs()],
            "sort_by": self.sort_by,
            "evaluation_goals": json_copy(self.evaluation_goals),
        }


@dataclass(slots=True)
class ExperimentReport:
    config: JsonDict
    runs: list[JsonDict]
    leaderboard: list[JsonDict]
    summary: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "config": json_copy(self.config),
            "runs": json_copy(self.runs),
            "leaderboard": json_copy(self.leaderboard),
            "summary": json_copy(self.summary),
        }


def run_experiment(config: ExperimentConfig | None = None) -> ExperimentReport:
    config = config or ExperimentConfig()
    runs: list[JsonDict] = []

    for provider_config in config.provider_configs():
        provider_label = provider_config.label()
        for seed in config.seeds:
            run_id = f"{provider_label}:seed-{int(seed)}"
            provider_id = provider_config.provider_id or ("default" if provider_config.provider_profile else provider_label)
            try:
                result = run(
                    RunConfig(
                        scenario=config.scenario,
                        seed=int(seed),
                        ticks=config.ticks,
                        rules=json_copy(config.rules),
                        provider=provider_config.provider,
                        provider_params=json_copy(provider_config.provider_params),
                        govern_provider_output=provider_config.govern_provider_output,
                        provider_id=provider_id,
                        allowed_rule_names=json_copy(provider_config.allowed_rule_names),
                        allowed_relationship_types=json_copy(provider_config.allowed_relationship_types),
                        provider_profile=json_copy(provider_config.provider_profile),
                        evaluation_goals=json_copy(config.evaluation_goals),
                    )
                ).to_dict()
                scorecard = _scorecard_from_result(result)
                runs.append(
                    {
                        "run_id": run_id,
                        "scenario": config.scenario,
                        "seed": int(seed),
                        "provider": provider_label,
                        "status": "completed",
                        "ticks": result["snapshot"]["tick"],
                        "scorecard": scorecard,
                        "metrics": json_copy(scorecard.get("metrics", {})),
                        "provider_audits": json_copy(result.get("provider_audits", [])),
                        "provider_execution_report": json_copy(result.get("provider_execution_report", {})),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - experiment matrices should preserve partial results.
                runs.append(_failed_run(run_id, config.scenario, int(seed), provider_label, exc))

    leaderboard = _build_leaderboard(runs, config.sort_by)
    summary = _build_summary(runs, leaderboard, config)
    return ExperimentReport(
        config=config.to_dict(),
        runs=runs,
        leaderboard=leaderboard,
        summary=summary,
    )


def _build_leaderboard(runs: list[JsonDict], sort_by: str) -> list[JsonDict]:
    rows = [
        {
            "rank": 0,
            "run_id": item["run_id"],
            "scenario": item["scenario"],
            "seed": item["seed"],
            "provider": item["provider"],
            "score": _score(item),
            "sort_value": _sort_value(item, sort_by),
        }
        for item in runs
    ]
    rows.sort(key=lambda item: (-item["sort_value"], item["provider"], item["seed"], item["run_id"]))
    for index, item in enumerate(rows, start=1):
        item["rank"] = index
    return rows


def _build_summary(
    runs: list[JsonDict],
    leaderboard: list[JsonDict],
    config: ExperimentConfig,
) -> JsonDict:
    scores = [_score(item) for item in runs]
    provider_count = len({str(item["provider"]) for item in runs})
    seed_count = len({int(item["seed"]) for item in runs})
    provider_comparison = _build_provider_comparison(runs)
    return {
        "run_count": len(runs),
        "provider_count": provider_count,
        "seed_count": seed_count,
        "best_run": json_copy(leaderboard[0]) if leaderboard else {},
        "average_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "sort_by": config.sort_by,
        "provider_comparison": provider_comparison,
    }


def _scorecard_from_result(result: JsonDict) -> JsonDict:
    scorecard = result.get("scorecard", {})
    return json_copy(scorecard) if isinstance(scorecard, dict) else {"score": 0.0, "metrics": {}, "penalties": []}


def _failed_run(run_id: str, scenario: str, seed: int, provider: str, exc: Exception) -> JsonDict:
    scorecard = {
        "score": 0.0,
        "metrics": {
            "provider_failures": 1,
            "provider_attempts": 0,
            "provider_estimated_cost": 0.0,
            "provider_latency_ms": 0.0,
            "provider_governance_rejections": 0,
        },
        "penalties": [
            {
                "kind": "provider_failure",
                "count": 1,
                "points": 100,
                "reason": str(exc),
            }
        ],
        "summary": f"provider_failure={type(exc).__name__}: {exc}",
    }
    return {
        "run_id": run_id,
        "scenario": scenario,
        "seed": seed,
        "provider": provider,
        "status": "failed",
        "ticks": 0,
        "scorecard": scorecard,
        "metrics": json_copy(scorecard["metrics"]),
        "provider_audits": [],
        "provider_execution_report": {
            "totals": {
                "providers": 1,
                "outputs": 0,
                "attempts": 0,
                "estimated_cost": 0.0,
                "latency_ms": 0.0,
                "effect_count": 0,
                "audits": 0,
                "accepted_audits": 0,
                "rejected_audits": 0,
                "failures": 1,
                "outcome_pressures": 0,
                "outcome_matched_pressures": 0,
                "outcome_unmatched_pressures": 0,
                "outcome_alignment_rate": 0.0,
            },
            "providers": [{"provider": provider, "failures": 1}],
        },
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def _build_provider_comparison(runs: list[JsonDict]) -> list[JsonDict]:
    grouped: dict[str, list[JsonDict]] = {}
    for run_summary in runs:
        grouped.setdefault(str(run_summary.get("provider", "")), []).append(run_summary)

    comparison: list[JsonDict] = []
    for provider, provider_runs in sorted(grouped.items()):
        scores = [_score(item) for item in provider_runs]
        metrics = [_metrics(item) for item in provider_runs]
        profile_totals = [_provider_execution_totals(item) for item in provider_runs]
        comparison.append(
            {
                "provider": provider,
                "run_count": len(provider_runs),
                "completed_count": sum(1 for item in provider_runs if item.get("status") == "completed"),
                "failed_count": sum(1 for item in provider_runs if item.get("status") == "failed"),
                "average_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
                "average_provider_alignment_rate": _average_metric(metrics, "provider_outcome_alignment_rate"),
                "provider_outcome_pressures": int(
                    sum(float(item.get("provider_outcome_pressures", 0.0) or 0.0) for item in metrics)
                ),
                "provider_unmatched_pressures": int(
                    sum(float(item.get("provider_unmatched_pressures", 0.0) or 0.0) for item in metrics)
                ),
                "total_attempts": int(sum(float(item.get("provider_attempts", 0.0) or 0.0) for item in metrics)),
                "total_estimated_cost": round(
                    sum(float(item.get("provider_estimated_cost", 0.0) or 0.0) for item in metrics),
                    6,
                ),
                "total_latency_ms": round(
                    sum(float(item.get("provider_latency_ms", 0.0) or 0.0) for item in metrics),
                    3,
                ),
                "governance_rejections": int(
                    sum(float(item.get("provider_governance_rejections", 0.0) or 0.0) for item in metrics)
                ),
                "provider_failures": int(sum(float(item.get("provider_failures", 0.0) or 0.0) for item in metrics)),
                "profile_outputs": int(sum(float(item.get("outputs", 0.0) or 0.0) for item in profile_totals)),
                "profile_attempts": int(sum(float(item.get("attempts", 0.0) or 0.0) for item in profile_totals)),
                "profile_estimated_cost": round(
                    sum(float(item.get("estimated_cost", 0.0) or 0.0) for item in profile_totals),
                    6,
                ),
                "profile_latency_ms": round(
                    sum(float(item.get("latency_ms", 0.0) or 0.0) for item in profile_totals),
                    3,
                ),
                "profile_effect_count": int(sum(float(item.get("effect_count", 0.0) or 0.0) for item in profile_totals)),
                "profile_rejected_audits": int(
                    sum(float(item.get("rejected_audits", 0.0) or 0.0) for item in profile_totals)
                ),
                "profile_failures": int(sum(float(item.get("failures", 0.0) or 0.0) for item in profile_totals)),
                "profile_alignment_rate": _profile_alignment_rate(profile_totals),
                "average_required_action_coverage": _average_metric(metrics, "required_action_coverage"),
                "missing_required_actions": int(
                    sum(len(_list(item.get("missing_required_actions"))) for item in metrics)
                ),
            }
        )
    comparison.sort(key=lambda item: (-float(item["average_score"]), item["provider"]))
    return comparison


def _average_metric(metrics: list[JsonDict], key: str) -> float:
    if not metrics:
        return 0.0
    return round(sum(float(item.get(key, 0.0) or 0.0) for item in metrics) / len(metrics), 4)


def _score(run_summary: JsonDict) -> float:
    return float(_scorecard(run_summary).get("score", 0.0) or 0.0)


def _sort_value(run_summary: JsonDict, sort_by: str) -> float:
    scorecard = _scorecard(run_summary)
    if sort_by == "score":
        return _score(run_summary)
    metrics = scorecard.get("metrics", {})
    if isinstance(metrics, dict):
        return float(metrics.get(sort_by, 0.0) or 0.0)
    return 0.0


def _metrics(run_summary: JsonDict) -> JsonDict:
    metrics = run_summary.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    scorecard = _scorecard(run_summary)
    metrics = scorecard.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}


def _provider_execution_totals(run_summary: JsonDict) -> JsonDict:
    report = run_summary.get("provider_execution_report")
    if not isinstance(report, dict):
        return {}
    totals = report.get("totals")
    return totals if isinstance(totals, dict) else {}


def _profile_alignment_rate(profile_totals: list[JsonDict]) -> float:
    pressures = sum(float(item.get("outcome_pressures", 0.0) or 0.0) for item in profile_totals)
    matched = sum(float(item.get("outcome_matched_pressures", 0.0) or 0.0) for item in profile_totals)
    return round(matched / pressures, 4) if pressures else 0.0


def _profile_id(provider_profile: JsonDict) -> str:
    if not isinstance(provider_profile, dict):
        return ""
    return str(provider_profile.get("id", provider_profile.get("provider_id", ""))).strip()


def _scorecard(run_summary: JsonDict) -> JsonDict:
    scorecard = run_summary.get("scorecard", {})
    return scorecard if isinstance(scorecard, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
