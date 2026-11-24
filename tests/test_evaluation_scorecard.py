import json

from ai_native_world_engine.core import RunConfig, evaluate_run, run


def test_run_result_includes_scorecard() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=1)).to_dict()

    scorecard = result["scorecard"]
    assert scorecard["score"] == 100.0
    assert scorecard["metrics"]["pressures"] == 1
    assert scorecard["metrics"]["matched_pressures"] == 1
    assert scorecard["metrics"]["pressure_match_rate"] == 1.0
    assert scorecard["penalties"] == []
    json.dumps(scorecard, ensure_ascii=False)


def test_evaluate_run_is_deterministic_for_dict_input() -> None:
    result = run(RunConfig(scenario="seed", seed=23, ticks=2)).to_dict()

    first = evaluate_run(result).to_dict()
    second = evaluate_run(result).to_dict()

    assert first == second
    assert first == result["scorecard"]


def test_unmatched_pressure_creates_penalty() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=0)).to_dict()
    result["pressure_action_report"] = {
        "totals": {
            "pressures": 2,
            "matched": 1,
            "unmatched": 1,
            "match_rate": 0.5,
        },
        "recent": [],
    }

    scorecard = evaluate_run(result).to_dict()

    assert scorecard["score"] == 90.0
    assert scorecard["metrics"]["unmatched_pressures"] == 1
    assert scorecard["penalties"][0]["kind"] == "unmatched_pressure"


def test_world_errors_create_penalty() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=0)).to_dict()
    result["snapshot"]["errors"] = [{"error": "bad effect"}, {"error": "missing node"}]

    scorecard = evaluate_run(result).to_dict()

    assert scorecard["score"] == 50.0
    assert scorecard["metrics"]["world_errors"] == 2
    assert scorecard["penalties"][0]["kind"] == "world_error"


def test_scorecard_reports_required_action_goal_coverage() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            evaluation_goals={"required_actions": ["move", "missing_action"]},
        )
    ).to_dict()

    scorecard = result["scorecard"]

    assert result["config"]["evaluation_goals"]["required_actions"] == ["move", "missing_action"]
    assert scorecard["score"] == 92.0
    assert scorecard["metrics"]["required_action_count"] == 2
    assert scorecard["metrics"]["required_action_hits"] == 1
    assert scorecard["metrics"]["required_action_coverage"] == 0.5
    assert scorecard["metrics"]["missing_required_actions"] == ["missing_action"]
    assert scorecard["penalties"][0]["kind"] == "missing_required_action"


def test_scorecard_goal_coverage_passes_when_required_actions_occur() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            evaluation_goals={"required_actions": ["move"]},
        )
    ).to_dict()

    scorecard = result["scorecard"]

    assert scorecard["score"] == 100.0
    assert scorecard["metrics"]["required_action_count"] == 1
    assert scorecard["metrics"]["required_action_hits"] == 1
    assert scorecard["metrics"]["required_action_coverage"] == 1.0
    assert scorecard["metrics"]["missing_required_actions"] == []


def test_scorecard_reports_grounded_action_coverage() -> None:
    result = run(RunConfig(scenario="compound_crisis", seed=31, ticks=1)).to_dict()
    metrics = result["scorecard"]["metrics"]

    assert metrics["action_counts_by_type"]["combat_attack"] == 1
    assert metrics["action_counts_by_type"]["logistics_transfer"] == 1
    assert metrics["action_counts_by_type"]["infection_spread"] == 1
    assert metrics["action_counts_by_type"]["organization_decision"] == 1
    assert metrics["action_counts_by_type"]["social_spread"] == 1
    assert metrics["action_counts_by_type"]["production"] == 1
    assert metrics["action_counts_by_type"]["economic_exchange"] == 1
    assert metrics["grounded_action_class_count"] >= 12
    assert "combat_attack" in metrics["world_ecosystem_actions_hit"]
    assert "production" in metrics["world_ecosystem_actions_hit"]
    assert "economic_exchange" in metrics["world_ecosystem_actions_hit"]
    assert "infection_spread" in metrics["world_ecosystem_actions_hit"]
    assert "organization_decision" in metrics["world_ecosystem_actions_hit"]
    assert "production" not in metrics["world_ecosystem_actions_missing"]
    assert "economic_exchange" not in metrics["world_ecosystem_actions_missing"]
    assert metrics["world_ecosystem_action_coverage"] == 1.0
