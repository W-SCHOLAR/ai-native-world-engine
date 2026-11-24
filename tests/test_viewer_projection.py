import json

from ai_native_world_engine.core import (
    DeterministicPressureProvider,
    RunConfig,
    project_run_for_viewer,
    run,
)


def test_project_run_for_viewer_outputs_json_compatible_projection() -> None:
    result = run(
        RunConfig(
            scenario="catalog",
            scenario_path="examples/catalogs/enterprise_earth_sample.json",
            ticks=1,
        )
    )

    projection = project_run_for_viewer(result).to_dict()

    assert projection["summary"]["scenario"] == "catalog"
    assert projection["organizations"]
    assert projection["characters"]
    assert projection["people"]
    assert projection["relationships"]
    assert projection["thoughts"] == []
    assert projection["actions"] == []
    assert "impact_ripples" in projection
    assert "key_character_trajectories" in projection
    json.dumps(projection, ensure_ascii=False)


def test_loading_cover_does_not_filter_or_resequence_grounded_actions() -> None:
    baseline = project_run_for_viewer(
        run(
            RunConfig(
                scenario="tribe_survival",
                ticks=3,
                provider=DeterministicPressureProvider(emit_thoughts=True),
            )
        )
    ).to_dict()
    covered = project_run_for_viewer(
        run(
            RunConfig(
                scenario="tribe_survival",
                ticks=3,
                provider=DeterministicPressureProvider(emit_thoughts=True),
                runtime_provider={"mode": "deterministic"},
                require_cognition_ready=True,
            )
        )
    ).to_dict()

    assert [
        (item["action"], item["actor_id"])
        for item in covered["grounded_actions"]
    ] == [
        (item["action"], item["actor_id"])
        for item in baseline["grounded_actions"]
    ]


def test_viewer_projection_preserves_agent_layer_classification() -> None:
    result = run(
        RunConfig(
            scenario="catalog",
            scenario_path="examples/catalogs/enterprise_earth_sample.json",
            ticks=0,
        )
    ).to_dict()

    projection = project_run_for_viewer(result).to_dict()
    organization = projection["organizations"][0]
    character = projection["characters"][0]
    cohort = next(item for item in projection["people"] if item["type"] == "population_cohort")

    assert organization["id"] == "org-science-council"
    assert organization["members"]
    assert character["id"] == "key-albert-einstein"
    assert character["key_character"]["agent_layer"] == "key_character"
    assert cohort["privacy"] == "anonymous_aggregate"
    assert cohort["synthetic"] is True


def test_viewer_projection_accepts_dict_input() -> None:
    result = run(
        RunConfig(
            scenario="catalog",
            scenario_path="examples/catalogs/enterprise_earth_sample.json",
            ticks=1,
        )
    ).to_dict()

    assert project_run_for_viewer(result).to_dict()["summary"]["world_id"] == result["snapshot"]["id"]


def test_viewer_projection_includes_grounded_action_summary() -> None:
    result = run(RunConfig(scenario="compound_crisis", seed=31, ticks=1)).to_dict()

    projection = project_run_for_viewer(result).to_dict()
    summary = projection["summary"]["grounded_action_summary"]
    run_health = projection["summary"]["run_health"]
    governance_notice = projection["summary"]["governance_notice"]
    grounded_actions = projection["grounded_actions"]
    action_visuals = projection["action_visuals"]
    current_actions = projection["current_actions"]
    actions_by_type = {action["action"]: action for action in grounded_actions}

    assert summary["counts_by_type"]["combat_attack"] == 1
    assert summary["counts_by_type"]["infection_spread"] == 1
    assert summary["counts_by_type"]["organization_decision"] == 1
    assert summary["counts_by_type"]["production"] == 1
    assert summary["counts_by_type"]["economic_exchange"] == 1
    assert summary["grounded_action_class_count"] >= 12
    assert "logistics_transfer" in summary["world_ecosystem_actions_hit"]
    assert "production" in summary["world_ecosystem_actions_hit"]
    assert "economic_exchange" in summary["world_ecosystem_actions_hit"]
    assert "production" not in summary["world_ecosystem_actions_missing"]
    assert "economic_exchange" not in summary["world_ecosystem_actions_missing"]
    assert summary["world_ecosystem_action_coverage"] == result["scorecard"]["metrics"]["world_ecosystem_action_coverage"]
    assert run_health["score"] == result["scorecard"]["score"]
    assert run_health["penalty_count"] == 0
    assert run_health["world_errors"] == 0
    assert run_health["governance_rejections"] == 0
    assert run_health["domain_state_issues"] == 0
    assert run_health["unmatched_pressures"] == 0
    assert run_health["missing_required_actions"] == []
    assert governance_notice == {
        "label": "场景模拟",
        "scenario": "compound_crisis",
        "message": "此运行是场景模拟和假设推演，不是对现实世界的确定性预测。",
        "risk_level": projection["summary"]["domain_risk"]["level"],
    }
    assert actions_by_type["production"]["actor_id"] == "workshop"
    assert actions_by_type["production"]["actor_name"] == "Emergency Repair Workshop"
    assert actions_by_type["production"]["decision"] == {
        "rule": "production",
        "reason": "replace damaged response gear",
        "score": 1.0,
        "candidate_count": 1,
    }
    assert "candidates" not in actions_by_type["production"]["decision"]
    production_effects = actions_by_type["production"]["effects"]
    assert actions_by_type["production"]["effect_count"] >= 3
    assert any(effect["type"] == "resource_delta" and "raw_material -2" in effect["label"] for effect in production_effects)
    assert any(effect["type"] == "resource_delta" and "repair_kits +2" in effect["label"] for effect in production_effects)
    raw_material_change = next(effect["change"] for effect in production_effects if effect["resource"] == "raw_material")
    repair_kit_change = next(effect["change"] for effect in production_effects if effect["resource"] == "repair_kits")
    assert raw_material_change["before"] == 5
    assert raw_material_change["after"] == 3
    assert repair_kit_change["before"] == 0
    assert repair_kit_change["after"] == 2
    assert actions_by_type["economic_exchange"]["actor_id"] == "market-buyer"
    assert actions_by_type["economic_exchange"]["actor_attributes"]["budget"] == 6
    assert actions_by_type["economic_exchange"]["actor_attributes"]["resources"]["repair_kits"] == 2
    assert actions_by_type["economic_exchange"]["targets"][0]["name"] == "Mutual Aid Market Seller"
    assert actions_by_type["economic_exchange"]["targets"][0]["attributes"]["budget"] == 5
    exchange_effects = actions_by_type["economic_exchange"]["effects"]
    assert any(effect["type"] == "resource_transfer" and "repair_kits" in effect["label"] for effect in exchange_effects)
    assert any(
        effect["type"] == "resource_transfer"
        and effect["from"]["attributes"]["resources"]["repair_kits"] == 2
        and effect["to"]["attributes"]["resources"]["repair_kits"] == 2
        for effect in exchange_effects
    )
    transfer_change = next(effect["change"] for effect in exchange_effects if effect["type"] == "resource_transfer")
    assert transfer_change["from"]["before"] == 4
    assert transfer_change["from"]["after"] == 2
    assert transfer_change["to"]["before"] == 0
    assert transfer_change["to"]["after"] == 2
    budget_change = next(effect["change"] for effect in exchange_effects if effect["type"] == "node_attribute_delta" and effect["field"] == "budget")
    assert budget_change["before"] == 10
    assert budget_change["after"] == 6
    assert all("x" in action and "y" in action for action in grounded_actions if action["actor_type"] == "node")
    assert len(action_visuals) == len({action["sequence"] for action in grounded_actions})
    assert len({visual["feedback_sequence"] for visual in action_visuals}) == len(action_visuals)
    production_visual = next(visual for visual in action_visuals if visual["action"] == "production")
    assert production_visual["actor_id"] == "workshop"
    assert production_visual["ttl"] == 2.4
    assert len(current_actions) == len({visual["actor_id"] for visual in current_actions})
    assert [visual["actor_id"] for visual in current_actions] == sorted(
        visual["actor_id"] for visual in current_actions
    )
    json.dumps(grounded_actions, ensure_ascii=False)


def test_viewer_projection_selects_latest_current_action_per_actor() -> None:
    result = {
        "snapshot": {
            "id": "current-action-world",
            "tick": 4,
            "attributes": {},
            "nodes": [
                {
                    "id": "actor-z",
                    "type": "person",
                    "name": "Actor Z",
                    "position": {"x": 1, "y": 1},
                    "attributes": {},
                },
                {
                    "id": "actor-a",
                    "type": "person",
                    "name": "Actor A",
                    "position": {"x": 2, "y": 2},
                    "attributes": {},
                },
            ],
            "relationships": [],
        },
        "events": [
            {
                "kind": "action_feedback",
                "tick": 1,
                "sequence": 10,
                "payload": {
                    "apply_mode": "authoritative",
                    "actor_type": "node",
                    "actor_id": "actor-z",
                    "action": "gather_wood",
                    "source": "rule:survival",
                    "summary": "Gathering wood",
                    "effects": [],
                },
            },
            {
                "kind": "action_feedback",
                "tick": 2,
                "sequence": 12,
                "payload": {
                    "apply_mode": "authoritative",
                    "actor_type": "person",
                    "actor_id": "actor-a",
                    "action": "guard_gate",
                    "source": "rule:defense",
                    "summary": "Guarding gate",
                    "effects": [],
                },
            },
            {
                "kind": "action_feedback",
                "tick": 3,
                "sequence": 14,
                "payload": {
                    "apply_mode": "authoritative",
                    "actor_type": "node",
                    "actor_id": "actor-z",
                    "action": "build_shelter",
                    "source": "rule:survival",
                    "summary": "Building shelter",
                    "effects": [],
                },
            },
            {
                "kind": "action_feedback",
                "tick": 4,
                "sequence": 16,
                "payload": {
                    "apply_mode": "authoritative",
                    "actor_type": "user",
                    "actor_id": "operator",
                    "action": "operator_signal",
                    "source": "web_operator",
                    "summary": "Operator signal",
                    "effects": [],
                },
            },
        ],
        "traces": [],
        "scorecard": {},
    }

    projection = project_run_for_viewer(result).to_dict()

    assert [item["actor_id"] for item in projection["current_actions"]] == [
        "actor-a",
        "actor-z",
    ]
    assert projection["current_actions"][0]["feedback_sequence"] == 12
    assert projection["current_actions"][1]["feedback_sequence"] == 14
    assert projection["current_actions"][1]["action"] == "build_shelter"
    assert projection["current_actions"][1]["tick"] == 3
    assert projection["current_actions"][1]["source"] == "rule:survival"
    assert len(projection["action_visuals"]) == 4


def test_viewer_projection_includes_runtime_intervention_grounded_action() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            interventions=[
                {
                    "id": "operator-visible-marker",
                    "tick": 0,
                    "source": "web_operator",
                    "actor_type": "user",
                    "actor_id": "web-operator",
                    "action": "operator_signal",
                    "summary": "Operator signal for Mira",
                    "effects": [
                        {
                            "type": "node_state",
                            "target": "node:mira",
                            "field": "operator_signal",
                            "value": "inspect-visible",
                        }
                    ],
                }
            ],
        )
    ).to_dict()

    projection = project_run_for_viewer(result).to_dict()
    intervention_action = next(action for action in projection["grounded_actions"] if action["action"] == "operator_signal")

    assert intervention_action["actor_type"] == "user"
    assert intervention_action["actor_id"] == "web-operator"
    assert intervention_action["intervention"] == {
        "id": "operator-visible-marker",
        "scheduled_tick": 0,
        "effect_count": 1,
    }
    assert intervention_action["targets"][0]["id"] == "mira"
    assert intervention_action["targets"][0]["attributes"]["operator_signal"] == "inspect-visible"
    assert intervention_action["effects"][0]["label"].endswith("operator_signal")


def test_viewer_projection_includes_bounded_node_memory_highlights() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            interventions=[
                {
                    "id": "visible-memory",
                    "tick": 0,
                    "effects": [
                        {
                            "type": "memory_add",
                            "target": "node:mira",
                            "text": f"memory highlight {index}",
                            "source": "field",
                            "importance": importance,
                        }
                        for index, importance in enumerate([0.2, 0.95, 0.6, 0.8])
                    ],
                }
            ],
        )
    ).to_dict()

    projection = project_run_for_viewer(result).to_dict()
    mira = next(item for item in projection["people"] if item["id"] == "mira")
    attributes = mira["attributes"]
    highlights = attributes["_memory_highlights"]

    assert attributes["_memory_count"] == 4
    assert len(highlights) == 3
    assert highlights[0]["text"] == "memory highlight 1"
    assert highlights[0]["importance"] == 0.95
    assert highlights[1]["text"] == "memory highlight 3"
    assert all(set(item).issubset({"kind", "text", "source", "tick", "importance", "memory_count"}) for item in highlights)
    json.dumps(highlights, ensure_ascii=False)


def test_viewer_projection_summarizes_memory_maintenance() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            interventions=[
                {
                    "id": "visible-memory-maintenance",
                    "tick": 0,
                    "effects": [
                        {
                            "type": "memory_add",
                            "target": "node:mira",
                            "text": f"memory maintenance note {index}",
                            "source": "field",
                            "importance": importance,
                        }
                        for index, importance in enumerate([0.1, 0.2, 0.9, 0.8, 0.7, 0.4, 0.6, 0.5])
                    ],
                }
            ],
            memory_consolidation={
                "enabled": True,
                "interval": 1,
                "max_memories": 5,
                "recent_keep": 2,
                "retention_importance_floor": 0.5,
            },
        )
    ).to_dict()

    projection = project_run_for_viewer(result).to_dict()
    maintenance = projection["summary"]["memory_maintenance"]

    assert maintenance["consolidated_nodes"] == 1
    assert maintenance["summary_count"] == 1
    assert maintenance["forgotten_count"] == 3
    assert len(maintenance["recent"]) == 1
    assert maintenance["recent"][0]["node_id"] == "mira"
    assert maintenance["recent"][0]["kind"] == "memory_summary"
    assert maintenance["recent"][0]["memory_count"] == 3
    assert maintenance["recent"][0]["forgotten_count"] == 3
    assert "memory maintenance note" in maintenance["recent"][0]["text"]
    assert len(maintenance["recent"][0]["keywords"]) <= 5
    json.dumps(maintenance, ensure_ascii=False)


def test_viewer_projection_exposes_impact_ripples_and_key_character_trajectories() -> None:
    result = run(RunConfig(scenario="enterprise_earth", seed=7, ticks=2)).to_dict()

    projection = project_run_for_viewer(result).to_dict()

    assert projection["impact_ripples"]
    assert all("node_id" in item for item in projection["impact_ripples"])
    assert projection["key_character_trajectories"]
    einstein = next(item for item in projection["key_character_trajectories"] if item["node_id"] == "key-albert-einstein")
    assert einstein["identity"] == "scientist"
    assert "thought_count" in einstein
    assert "action_bullet_count" in einstein
