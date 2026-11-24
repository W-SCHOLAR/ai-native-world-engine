import json

from ai_native_world_engine.core import (
    AgentSchedulerConfig,
    COMMERCIAL_LENS_ORIGIN,
    DeterministicCommercialLensProvider,
    ProviderContext,
    RunConfig,
    World,
    commercial_lens_ids,
    enterprise_agent_jobs,
    project_run_for_viewer,
    relationship_lens_ids,
    run,
)


def test_commercial_lens_provider_emits_lens_tagged_structured_pressure() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    provider = DeterministicCommercialLensProvider("resource_supply", max_targets=3)
    output = provider.observe(ProviderContext(world, world.tick, world.snapshot()))
    effects = [item.to_dict() for item in output.effects]

    assert output.metadata["commercial_lens"]["id"] == "resource_supply"
    assert output.metadata["commercial_lens"]["target_nodes"]
    assert output.metadata["commercial_lens"]["effect_count"] == len(effects)
    assert {item["type"] for item in effects} == {
        "thought_bubble_add",
        "rule_pressure_add",
        "memory_add",
        "relationship_delta",
    }
    assert all(item.get("origin") == COMMERCIAL_LENS_ORIGIN for item in effects)
    assert all(item.get("lens_id") == "resource_supply" for item in effects)
    assert any(item.get("rule") == "resource_transfer" for item in effects)
    json.dumps(output.to_dict(), ensure_ascii=False)


def test_enterprise_scheduler_includes_all_commercial_lens_jobs() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    jobs = enterprise_agent_jobs(world)
    lens_jobs = [job for job in jobs if job.kind == "commercial_lens"]

    relationship_lens_jobs = [job for job in jobs if job.kind == "relationship_lens"]

    assert len(jobs) == 26
    assert [job.metadata["lens_id"] for job in lens_jobs] == commercial_lens_ids()
    assert all(job.slot == "event_lens" for job in lens_jobs)
    assert [job.metadata["lens_id"] for job in relationship_lens_jobs] == relationship_lens_ids()
    assert all(job.metadata["ai_isekai_relationship_lens"] is True for job in relationship_lens_jobs)


def test_run_harness_dispatches_commercial_lenses_with_budget_and_projection_metadata() -> None:
    config = RunConfig(
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

    result = run(config)
    data = result.to_dict()
    projection = project_run_for_viewer(result).to_dict()
    lens_outputs = [item for item in data["provider_outputs"] if "commercial_lens" in item]
    lens_thoughts = [
        item
        for item in projection["thoughts"]
        if item.get("origin") == COMMERCIAL_LENS_ORIGIN
    ]

    assert data["scheduler_status"]["started_count"] == 7
    assert data["scheduler_status"]["queue_length"] == 19
    assert len(lens_outputs) == 5
    assert [item["commercial_lens"]["id"] for item in lens_outputs] == commercial_lens_ids()
    assert lens_thoughts == []
    json.dumps(projection, ensure_ascii=False)
