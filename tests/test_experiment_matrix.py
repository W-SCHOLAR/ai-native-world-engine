import json

from ai_native_world_engine.core import (
    ExperimentConfig,
    ExperimentProviderConfig,
    JsonLlmProviderAdapter,
    ProviderContext,
    ProviderOutput,
    effect,
    run_experiment,
)


class BadRuleProvider:
    name = "bad-rule-provider"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        return ProviderOutput(
            source=self.name,
            summary="bad rule",
            effects=[effect("rule_pressure_add", target="node:mira", rule="attack", weight=1, ttl=1)],
        )


class ExperimentProfileProvider:
    name = "experiment-profile-provider"

    def __init__(self) -> None:
        self.observed_params: list[dict[str, object]] = []

    def observe(self, context: ProviderContext) -> ProviderOutput:
        self.observed_params.append(context.params)
        return ProviderOutput(
            source=self.name,
            summary="profiled experiment pressure",
            effects=[effect("rule_pressure_add", target="node:mira", rule="move", weight=0.2, ttl=1)],
            metadata={
                "provider_runtime": {
                    "provider": self.name,
                    "attempts": 1,
                    "estimated_cost": 0.02,
                    "cost_unit": "credits",
                    "latency_ms": 2.0,
                }
            },
        )


class FailingProvider:
    name = "failing-provider"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        raise RuntimeError("provider unavailable")


class RetryJsonClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, envelope: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        return {"summary": "retry ok", "effects": [], "metadata": {}}


def test_experiment_expands_seed_provider_matrix() -> None:
    report = run_experiment(
        ExperimentConfig(
            seeds=[7, 23],
            ticks=1,
            providers=[
                ExperimentProviderConfig(name="baseline"),
                ExperimentProviderConfig(
                    name="quiet",
                    provider_params={"emit_thoughts": False},
                ),
            ],
        )
    ).to_dict()

    assert report["summary"]["run_count"] == 4
    assert report["summary"]["provider_count"] == 2
    assert report["summary"]["seed_count"] == 2
    assert [item["run_id"] for item in report["runs"]] == [
        "baseline:seed-7",
        "baseline:seed-23",
        "quiet:seed-7",
        "quiet:seed-23",
    ]
    assert all(item["scorecard"]["score"] == 100.0 for item in report["runs"])
    json.dumps(report, ensure_ascii=False)


def test_experiment_report_is_reproducible() -> None:
    config = ExperimentConfig(seeds=[7, 23], ticks=2)

    first = run_experiment(config).to_dict()
    second = run_experiment(config).to_dict()

    assert first == second


def test_experiment_leaderboard_has_stable_tie_breaks() -> None:
    report = run_experiment(
        ExperimentConfig(
            seeds=[23, 7],
            ticks=1,
            providers=[
                ExperimentProviderConfig(name="quiet"),
                ExperimentProviderConfig(name="baseline"),
            ],
        )
    ).to_dict()

    leaderboard = report["leaderboard"]

    assert [item["rank"] for item in leaderboard] == [1, 2, 3, 4]
    assert [item["run_id"] for item in leaderboard] == [
        "baseline:seed-7",
        "baseline:seed-23",
        "quiet:seed-7",
        "quiet:seed-23",
    ]
    assert report["summary"]["best_run"] == leaderboard[0]


def test_experiment_can_sort_by_scorecard_metric() -> None:
    report = run_experiment(
        ExperimentConfig(
            seeds=[7],
            ticks=1,
            sort_by="pressure_match_rate",
        )
    ).to_dict()

    assert report["config"]["sort_by"] == "pressure_match_rate"
    assert report["leaderboard"][0]["sort_value"] == 1.0
    assert report["summary"]["average_score"] == 100.0


def test_experiment_comparison_aggregates_provider_retry_costs() -> None:
    client = RetryJsonClient()
    provider = JsonLlmProviderAdapter(client=client, max_attempts=2, estimated_cost_per_attempt=0.25)

    report = run_experiment(
        ExperimentConfig(
            seeds=[7],
            ticks=1,
            providers=[
                ExperimentProviderConfig(
                    name="retry-llm",
                    provider=provider,
                    provider_params={"agent_context_packet": {"schema": "test_packet", "active_candidates": []}},
                )
            ],
        )
    ).to_dict()

    comparison = report["summary"]["provider_comparison"][0]
    assert client.calls == 2
    assert comparison["provider"] == "retry-llm"
    assert comparison["total_attempts"] == 2
    assert comparison["total_estimated_cost"] == 0.5
    assert comparison["governance_rejections"] == 0
    assert comparison["average_provider_alignment_rate"] == 0.0
    assert comparison["profile_outputs"] == 1
    assert comparison["profile_attempts"] == 2
    assert comparison["profile_estimated_cost"] == 0.5
    assert report["runs"][0]["metrics"]["provider_attempts"] == 2
    assert report["runs"][0]["provider_execution_report"]["totals"]["attempts"] == 2


def test_experiment_forwards_provider_policy_profile() -> None:
    provider = ExperimentProfileProvider()

    report = run_experiment(
        ExperimentConfig(
            seeds=[7],
            ticks=1,
            providers=[
                ExperimentProviderConfig(
                    name="profiled",
                    provider=provider,
                    provider_profile={
                        "id": "experiment-policy",
                        "allowed_rule_names": ["move"],
                        "context_strategy": {"mode": "experiment", "memory_limit": 2},
                        "metadata": {"cohort": "a"},
                    },
                )
            ],
        )
    ).to_dict()

    run_row = report["runs"][0]
    audit = run_row["provider_audits"][0]

    assert report["config"]["providers"][0]["provider_id"] == "experiment-policy"
    assert report["config"]["providers"][0]["provider_profile"]["id"] == "experiment-policy"
    assert provider.observed_params[0]["context_strategy"] == {"mode": "experiment", "memory_limit": 2}
    assert audit["accepted"] is True
    assert audit["provider_id"] == "experiment-policy"
    assert audit["metadata"]["policy_profile"]["metadata"] == {"cohort": "a"}
    assert run_row["provider_execution_report"]["providers"][0]["provider_ids"] == ["experiment-policy"]


def test_experiment_comparison_counts_governance_rejections() -> None:
    report = run_experiment(
        ExperimentConfig(
            seeds=[7],
            ticks=1,
            providers=[
                ExperimentProviderConfig(
                    name="governed-bad",
                    provider=BadRuleProvider(),
                    govern_provider_output=True,
                    allowed_rule_names=["move"],
                )
            ],
        )
    ).to_dict()

    comparison = report["summary"]["provider_comparison"][0]
    assert report["runs"][0]["status"] == "completed"
    assert report["runs"][0]["scorecard"]["score"] == 95.0
    assert comparison["governance_rejections"] == 1
    assert comparison["profile_rejected_audits"] == 1
    assert comparison["profile_failures"] == 1
    assert comparison["average_score"] == 95.0
    assert report["runs"][0]["provider_audits"][0]["accepted"] is False


def test_experiment_aggregates_required_action_goal_coverage() -> None:
    report = run_experiment(
        ExperimentConfig(
            seeds=[7],
            ticks=1,
            evaluation_goals={"required_actions": ["move", "missing_action"]},
            sort_by="required_action_coverage",
        )
    ).to_dict()

    run_row = report["runs"][0]
    comparison = report["summary"]["provider_comparison"][0]

    assert report["config"]["evaluation_goals"]["required_actions"] == ["move", "missing_action"]
    assert run_row["metrics"]["required_action_coverage"] == 0.5
    assert run_row["metrics"]["missing_required_actions"] == ["missing_action"]
    assert report["leaderboard"][0]["sort_value"] == 0.5
    assert comparison["average_required_action_coverage"] == 0.5
    assert comparison["missing_required_actions"] == 1


def test_experiment_records_provider_failure_without_aborting_matrix() -> None:
    report = run_experiment(
        ExperimentConfig(
            seeds=[7],
            ticks=1,
            providers=[
                ExperimentProviderConfig(name="failing", provider=FailingProvider()),
                ExperimentProviderConfig(name="baseline"),
            ],
        )
    ).to_dict()

    runs = {item["provider"]: item for item in report["runs"]}
    comparisons = {item["provider"]: item for item in report["summary"]["provider_comparison"]}
    assert runs["failing"]["status"] == "failed"
    assert runs["failing"]["scorecard"]["score"] == 0.0
    assert runs["baseline"]["status"] == "completed"
    assert comparisons["failing"]["provider_failures"] == 1
    assert comparisons["failing"]["profile_failures"] == 1
    assert comparisons["baseline"]["failed_count"] == 0
    assert comparisons["baseline"]["average_provider_alignment_rate"] == 1.0
    assert comparisons["baseline"]["profile_alignment_rate"] == 1.0
    assert comparisons["baseline"]["provider_outcome_pressures"] == 1
    assert comparisons["baseline"]["provider_unmatched_pressures"] == 0
    assert report["summary"]["best_run"]["provider"] == "baseline"
