from __future__ import annotations

import pytest

from ai_native_world_engine.core import RunConfig, RuleEngineSet, World, project_run_for_viewer, run
from ai_native_world_engine.scenarios import TribeSurvivalRulePackage


REQUIRED_ACTIONS = [
    "combat_attack",
    "move",
    "food_assess",
    "defense_inspect",
    "injury_assess",
    "duty_patrol",
]


def test_tribe_survival_world_is_authoritative_and_governed() -> None:
    world = World.scenario("tribe_survival", seed=7)

    assert world.attributes["viewer_scene"] == "tribe_survival_world"
    assert world.attributes["scene_title"] == "蛮荒世界"
    assert world.attributes["viewer_title"] == "蛮荒世界"
    assert world.attributes["sovereign_scope"]["not_commandable"]
    assert world.node("chieftain-aya").key_character["agent_layer"] == "key_character"
    assert world.node("ember-guard").attributes["agent_layer"] == "relationship_network"
    assert world.node("black-hill-tribe").attributes["sovereign_command_scope"] == "not_commandable"
    assert world.node("injured-scout").attributes["synthetic"] is True
    assert len(world.nodes) == 634
    assert len(world.relationships) >= 50
    people = [
        node
        for node in world.nodes.values()
        if node.attributes.get("viewer_behavior_actor", False)
    ]
    assert len(people) == 623
    assert all(node.attributes.get("simulation_tier") == "active_individual" for node in people)
    assert all(node.attributes.get("viewer_background") is not True for node in people)


def test_tribe_survival_startup_does_not_seed_authored_thoughts() -> None:
    world = World.scenario("tribe_survival", seed=7)
    payloads = [event["payload"] for event in world.presentation.recent()]

    assert not any(payload.get("type") == "thought_bubble" for payload in payloads)
    assert any(
        payload.get("type") == "action_bullet"
        and payload.get("node_id") == "ember-guard"
        and payload.get("text") == "北门进入夜间警戒"
        for payload in payloads
    )


def test_tribe_survival_run_grounds_required_vertical_slice() -> None:
    result = run(
        RunConfig(
            scenario="tribe_survival",
            seed=7,
            ticks=8,
            capture_timeline=True,
            evaluation_goals={"required_actions": REQUIRED_ACTIONS},
        )
    ).to_dict()
    metrics = result["scorecard"]["metrics"]
    actions = {
        event["payload"].get("action")
        for event in result["events"]
        if event.get("kind") == "action_feedback"
    }

    assert set(REQUIRED_ACTIONS).issubset(actions)
    assert result["config"]["rules"] == [
        "movement",
        "combat",
        "speak",
    ]
    assert result["config"]["external_rule_packages"] == [
        "tribe_activity_actions",
        "tribe_survival_actions",
    ]
    assert metrics["required_action_coverage"] == 1.0
    assert metrics["missing_required_actions"] == []
    assert metrics["unmatched_pressures"] == 0
    assert metrics["world_errors"] == 0
    assert result["scorecard"]["score"] == 100.0
    # The target contributes eight primary frames. A bounded causal-settling
    # tail may add up to the configured three frames when many independent
    # actors publish observations at the final tick.
    assert 8 <= len(result["timeline"]) <= 11
    assert [frame["tick"] for frame in result["timeline"][:8]] == list(range(1, 9))


def test_tribe_survival_projection_selects_existing_flat_map_renderer() -> None:
    result = run(RunConfig(scenario="tribe_survival", seed=7, ticks=1)).to_dict()
    projection = project_run_for_viewer(result).to_dict()
    summary = projection["summary"]

    assert summary["scenario"] == "tribe_survival"
    assert summary["viewer_scene"] == "tribe_survival_world"
    assert summary["scene_title"] == "蛮荒世界"
    assert summary["sovereign_scope"]["commandable"]
    assert "food" in summary["survival_loops"]
    assert len(projection["organizations"]) == 11
    assert all(len(organization["members"]) == 56 for organization in projection["organizations"])
    assert len(projection["characters"]) == 6
    assert projection["grounded_actions"]
    assert not any(
        action.get("origin") in {"active_node", "ripple_response", "key_character_continuity", "key_character_influence"}
        for action in projection["actions"]
    )
    assert projection["current_actions"]
    assert all(action["label"] for action in projection["current_actions"])
    assert not any(
        action["actor_id"] in {organization["id"] for organization in projection["organizations"]}
        for action in projection["current_actions"]
    )


def test_tribe_timeline_projects_active_background_members_without_repeating_history() -> None:
    result = run(
        RunConfig(
            scenario="tribe_survival",
            seed=7,
            ticks=2,
            capture_timeline=True,
        )
    ).to_dict()
    first_projection = result["timeline"][0]["projection"]
    second_projection = result["timeline"][1]["projection"]
    relationship_thought_node_ids = {
        thought["node_id"]
        for thought in first_projection["thoughts"]
        if thought.get("origin") in {"active_node", "ripple_response"}
    }

    assert relationship_thought_node_ids == set()
    assert second_projection["thoughts"] == []


def test_tribe_survival_action_pack_is_not_a_builtin_core_rule() -> None:
    with pytest.raises(ValueError, match="未知规则包"):
        RuleEngineSet.from_scenario(["tribe_survival_actions"])


def test_tribe_survival_v2_actions_apply_consequences_only_on_completion() -> None:
    world = World.scenario("tribe_survival", seed=7)
    engine = RuleEngineSet.from_scenario(
        ["movement", "combat", "speak"],
        extra_packages=[TribeSurvivalRulePackage()],
    )
    world.node("dawn-hunters").rule_pressures.append(
        {
            "rule": "survival_forage",
            "resource": "food",
            "amount": 6,
            "weight": 0.9,
            "ttl": 4,
            "reason": "legacy compatibility check",
        }
    )

    world.step(engine)

    forage = next(
        action
        for action in world.active_actions.values()
        if action.actor_id == "dawn-hunters"
    )
    assert forage.definition_id == "survival_forage"
    assert forage.status == "running"
    assert world.node("dawn-hunters").attributes["resources"]["food"] == 2

    world.step(engine)
    assert world.node("dawn-hunters").attributes["resources"]["food"] == 2
    world.step(engine)

    assert world.node("dawn-hunters").attributes["resources"]["food"] == 8
    assert any(
        action.id == forage.id and action.status == "succeeded"
        for action in world.action_history
    )


def test_tribe_survival_regenerates_home_enemy_and_dialogue_loops_without_llm() -> None:
    result = run(
        RunConfig(
            scenario="tribe_survival",
            seed=7,
            ticks=8,
            provider=None,
        )
    ).to_dict()
    snapshot = result["snapshot"]
    actions = [
        event["payload"]
        for event in result["events"]
        if event.get("kind") == "action_feedback"
    ]
    nodes = {node["id"]: node for node in snapshot["nodes"]}

    assert nodes["chieftain-aya"]["attributes"]["health"] == 7
    assert nodes["young-chief-ren"]["attributes"]["fatigue"] == 5
    assert nodes["injured-scout"]["attributes"]["health"] >= 7
    assert nodes["ember-guard"]["attributes"]["defense_rating"] >= 7
    assert any(
        action["actor_id"].startswith(("black-hill-tribe-agent", "wolf-tooth-raiders-agent"))
        and action["action"].startswith("duty_")
        for action in actions
    )

    speech_events = snapshot["speech_events"]
    warning = next(
        event
        for event in speech_events
        if event["speaker_id"] == "scout-nara" and event["intent"] == "warn"
    )
    reply = next(
        event
        for event in speech_events
        if event["speaker_id"] == "captain-tor"
        and event["reply_to"] == warning["id"]
    )
    assert warning["content"] == "北门发现敌踪，先不要独自过河。"
    assert reply["root_causality_id"] == warning["root_causality_id"]
    assert warning["id"] in reply["caused_by"]
