from __future__ import annotations

from collections import Counter

from ai_native_world_engine.core import (
    ActivityInstance,
    ActivityStep,
    ProviderOutputBoundary,
    RuleEngineSet,
    World,
    compact_world_snapshot,
    project_run_for_viewer,
)
from ai_native_world_engine.core.action_grounding import (
    action_option_is_groundable,
    groundable_action_options,
)
from ai_native_world_engine.scenarios import (
    TribeActivityRulePackage,
    TribeSurvivalRulePackage,
)


def _activity_engine() -> RuleEngineSet:
    return RuleEngineSet.from_scenario([], extra_packages=[TribeActivityRulePackage()])


def _food_total(world: World) -> float:
    total = 0.0
    for node in world.nodes.values():
        resources = node.attributes.get("resources", {})
        if isinstance(resources, dict):
            total += float(resources.get("food", 0.0) or 0.0)
    return total


def test_activity_contract_round_trip_is_bounded_and_serializable() -> None:
    activity = ActivityInstance(
        id="activity-1",
        definition_id="food_cycle",
        status="running",
        started_tick=1,
        updated_tick=2,
        steps=[ActivityStep("food_assess", "quartermaster", "盘点粮食")],
        participant_roles={"quartermaster": "granary-keepers"},
        root_causality_id="need-food-1",
    )

    restored = ActivityInstance.from_dict(activity.to_dict())

    assert restored.to_dict() == activity.to_dict()


def test_food_activity_runs_distinct_conserved_steps_without_llm() -> None:
    world = World.scenario("tribe_survival", seed=7)
    engine = _activity_engine()
    before = _food_total(world)

    for _ in range(24):
        world.step(engine)

    food_cycles = [
        item for item in world.activity_history if item.definition_id == "food_cycle"
    ]
    actions = {
        str(item.get("payload", {}).get("action", ""))
        for item in world.events.recent()
        if item.get("kind") == "action_feedback"
    }

    assert food_cycles
    assert {
        "food_assess",
        "food_source_select",
        "food_travel_out",
        "food_gather",
        "food_return",
        "food_store",
        "food_distribute",
        "food_eat",
    }.issubset(actions)
    assert _food_total(world) == before + len(food_cycles) * 5
    assert not world.errors


def test_activity_snapshot_restore_resumes_without_replaying_steps() -> None:
    world = World.scenario("tribe_survival", seed=7)
    engine = _activity_engine()
    for _ in range(6):
        world.step(engine)
    restored = World.from_snapshot(compact_world_snapshot(world))

    for _ in range(18):
        world.step(engine)
        restored.step(engine)

    assert compact_world_snapshot(restored) == compact_world_snapshot(world)


def test_no_model_fifty_tick_run_has_diverse_continuing_activities() -> None:
    world = World.scenario("tribe_survival", seed=7)
    engine = _activity_engine()
    observed_definitions: set[str] = set()
    for _ in range(50):
        world.step(engine)
        observed_definitions.update(
            item.definition_id for item in world.active_actions.values()
        )
        observed_definitions.update(item.definition_id for item in world.action_history)

    activity_types = Counter(item.definition_id for item in world.activity_history)
    projection = project_run_for_viewer(
        {"snapshot": world.snapshot(), "events": world.events.recent(), "traces": []}
    ).to_dict()

    # History is intentionally bounded and hundreds of simultaneous duty
    # completions can evict earlier definitions, so diversity is observed
    # across the run rather than inferred from only the final history suffix.
    assert len(observed_definitions) >= 20
    assert {"food_cycle", "defense_cycle", "care_cycle", "daily_duty"}.issubset(
        activity_types
    )
    assert activity_types["daily_duty"] >= 5
    assert world.active_activities
    assert len(world.activity_history) <= 128
    assert all(item.behavior_label != "协作" for item in world.action_history)
    assert all(
        item.get("activity_id") or str(item.get("action", "")).startswith("duty_")
        for item in projection["current_actions"]
    )
    assert not world.errors


def test_every_individually_visible_tribe_actor_has_person_bound_current_action() -> (
    None
):
    world = World.scenario("tribe_survival", seed=7)
    engine = RuleEngineSet.from_scenario(
        ["movement", "combat", "speak"],
        extra_packages=[TribeActivityRulePackage(), TribeSurvivalRulePackage()],
    )
    for _ in range(2):
        world.step(engine)

    roster_ids = {
        node.id
        for node in world.nodes.values()
        if node.attributes.get("viewer_behavior_actor", False)
    }
    active_actor_ids = {item.actor_id for item in world.active_actions.values()}
    projection = project_run_for_viewer(
        {"snapshot": world.snapshot(), "events": world.events.recent(), "traces": []}
    ).to_dict()
    current_actor_ids = {item["actor_id"] for item in projection["current_actions"]}

    # 11 relationship networks x 56 members, plus 7 key/person actors.
    assert len(roster_ids) == 623
    assert roster_ids <= active_actor_ids
    assert roster_ids <= current_actor_ids
    assert not {
        item["actor_id"]
        for item in projection["current_actions"]
        if world.node(item["actor_id"]).type == "organization"
    }


def test_active_tribe_duties_are_exported_as_node_local_grounding_options() -> None:
    world = World.scenario("tribe_survival", seed=7)
    engine = RuleEngineSet.from_scenario(
        ["movement", "combat", "speak"],
        extra_packages=[TribeActivityRulePackage(), TribeSurvivalRulePackage()],
    )
    for _ in range(2):
        world.step(engine)
    node_ids = [
        node.id
        for node in world.nodes.values()
        if node.attributes.get("parent_network") == "ember-guard"
    ][:10]

    options = groundable_action_options(
        world,
        node_ids,
        ["movement", "combat", "speak"],
    )

    duty_options = [item for item in options if item["rule"].startswith("duty_")]
    assert {item["node_id"] for item in duty_options} == set(node_ids)
    assert all(action_option_is_groundable(world, item) for item in options)
    assert all(
        item["parameters"]["_grounded_package_id"] == "tribe_activity_actions"
        for item in duty_options
    )

    updates = [
        {
            "id": node_id,
            "thought": f"我正在结合营地局势重新判断自己的下一步行动 {index}",
            "selected_action_option_id": f"invented-duty-{index}",
            "action_weight": 0.6,
            "action_ttl": 3,
            "action_reason": "继续职责",
        }
        for index, node_id in enumerate(node_ids)
    ]
    network_ids = {
        node.id
        for node in world.nodes.values()
        if node.attributes.get("parent_network") == "ember-guard"
    }

    output = ProviderOutputBoundary(
        source="tribe-grounding-test",
        allowed_rule_names={"movement", "combat", "speak"},
        required_active_node_count=10,
        expected_node_ids=set(node_ids),
        propagation_node_ids=network_ids,
        groundable_action_options=duty_options,
        provider_job_id="tribe-relationship-job",
        source_tick=world.tick,
    ).parse(world, {"summary": "tribe duties", "node_updates": updates})

    boundary = output.metadata["provider_output_boundary"]
    pressures = [item for item in output.effects if item.type == "rule_pressure_add"]
    assert boundary["action_option_repair_count"] == 10
    assert len(pressures) == 10
    assert all(str(item.fields["rule"]).startswith("duty_") for item in pressures)


def test_first_tribe_cognition_snapshot_has_grounded_social_options() -> None:
    world = World.scenario("tribe_survival", seed=7)
    node_ids = [
        node.id
        for node in world.nodes.values()
        if node.attributes.get("parent_network") == "ember-guard"
    ][:10]

    options = groundable_action_options(
        world,
        node_ids,
        ["movement", "combat", "speak"],
    )

    assert not world.active_actions
    assert {item["node_id"] for item in options} == set(node_ids)
    assert {item["rule"] for item in options} == {"speak"}
    assert all(item["target_id"] in world.nodes for item in options)
    assert all(action_option_is_groundable(world, item) for item in options)
