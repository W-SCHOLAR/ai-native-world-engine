import json

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    AgentSchedulerConfig,
    AiCausalityTraceLedger,
    FeedbackIngestor,
    RunConfig,
    World,
    effect,
    project_run_for_viewer,
    run,
)


def test_ai_causality_report_matches_visible_thought_pressure_and_action() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=1)).to_dict()
    report = result["ai_causality_report"]

    assert report["totals"]["thoughts"] >= 1
    assert report["totals"]["pressures"] == 1
    assert report["totals"]["matched_pressures"] == 1
    trace = report["recent"][0]
    assert trace["thought"]["text"] == "I should keep moving toward the target."
    assert trace["pressure"]["rule"] == "move"
    assert trace["matched"] is True
    assert trace["action"]["action"] == "move"
    json.dumps(report, ensure_ascii=False)


def test_ai_causality_report_keeps_unmatched_pressure_visible() -> None:
    world = World("unmatched")
    world.add_node("node", "person", "节点", (0, 0))
    ingestor = FeedbackIngestor()
    ingestor.ingest(
        world,
        ActionFeedback(
            source="agent",
            actor_type="agent",
            actor_id="mock",
            action="pressure",
            summary="unmatched pressure",
            effects=[
                effect("thought_bubble_add", target="node:node", text="我要先考虑隔离风险", source="agent"),
                effect("rule_pressure_add", target="node:node", rule="quarantine", weight=0.5, ttl=3, source="agent"),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )

    report = AiCausalityTraceLedger().build_report(world)

    assert report["totals"]["pressures"] == 1
    assert report["totals"]["unmatched_pressures"] == 1
    assert report["recent"][0]["matched"] is False
    assert report["recent"][0]["thought"]["text"] == "我要先考虑隔离风险"


def test_scheduler_run_projects_ai_causality_traces() -> None:
    result = run(
        RunConfig(
            scenario="enterprise_earth",
            seed=7,
            ticks=7,
            scheduler=AgentSchedulerConfig(
                enabled=True,
                max_concurrent=1,
                daily_budget=7,
                dispatch_slots=["relationship", "key_character", "lens", "lens", "lens", "lens", "lens"],
            ),
        )
    )

    data = result.to_dict()
    projection = project_run_for_viewer(result).to_dict()

    assert data["ai_causality_report"]["totals"]["thoughts"] > 0
    assert data["ai_causality_report"]["totals"]["pressures"] > 0
    assert "by_node" in data["ai_causality_report"]
    assert projection["ai_traces"]
    assert projection["ai_traces"] == data["ai_causality_report"]["recent"]
    json.dumps(projection, ensure_ascii=False)
