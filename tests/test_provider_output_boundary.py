import json

import pytest

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    PROVIDER_OUTPUT_BOUNDARY_SCHEMA,
    FeedbackIngestor,
    ProviderOutput,
    ProviderOutputBoundary,
    World,
)


def make_world() -> World:
    world = World("boundary-test")
    world.add_node("mira", "person", "Mira", (0, 0))
    world.add_node("atlas", "person", "Atlas", (1, 0))
    return world


def test_raw_provider_output_is_normalized_to_provider_output() -> None:
    world = make_world()
    world.set_movement_target("mira", (2, 0), 1.0)
    boundary = ProviderOutputBoundary(
        source="llm-test",
        allowed_rule_names={"move"},
        allowed_relationship_types={"trust"},
    )

    output = boundary.parse(
        world,
        {
            "summary": "Mira is considering a careful move.",
            "effects": [
                {
                    "type": "thought_bubble_add",
                    "target": "node:mira",
                    "text": "I should coordinate before moving.",
                    "source": "llm-test",
                },
                {
                    "type": "rule_pressure_add",
                    "target": "node:mira",
                    "rule": "move",
                    "weight": 0.4,
                    "ttl": 2,
                    "source": "llm-test",
                },
                {
                    "type": "relationship_delta",
                    "source": "node:mira",
                    "target": "node:atlas",
                    "relation": "trust",
                    "delta": 0.1,
                },
            ],
            "metadata": {"model": "test-model"},
        },
    )

    assert output.source == "llm-test"
    assert output.summary == "Mira is considering a careful move."
    assert [effect.type for effect in output.effects] == [
        "thought_bubble_add",
        "rule_pressure_add",
        "relationship_delta",
    ]
    assert output.metadata["model"] == "test-model"
    assert output.metadata["provider_output_boundary"] == {
        "schema": PROVIDER_OUTPUT_BOUNDARY_SCHEMA,
        "raw_effect_count": 3,
        "accepted_effect_count": 3,
    }
    json.dumps(output.to_dict(), ensure_ascii=False)


def test_provider_metadata_cannot_override_canonical_output_fields() -> None:
    output = ProviderOutput(
        source="canonical-provider",
        summary="canonical summary",
        metadata={
            "source": "model-supplied-source",
            "summary": "model-supplied summary",
            "effects": [{"type": "world_state"}],
            "model": "test-model",
        },
    ).to_dict()

    assert output["source"] == "canonical-provider"
    assert output["summary"] == "canonical summary"
    assert output["effects"] == []
    assert output["model"] == "test-model"


def test_output_boundary_rejects_direct_fact_mutation() -> None:
    world = make_world()
    boundary = ProviderOutputBoundary(source="llm-test")

    with pytest.raises(ValueError, match="direct mutation"):
        boundary.parse(
            world,
            {
                "summary": "Move Mira directly.",
                "effects": [
                    {
                        "type": "node_position",
                        "target": "node:mira",
                        "position": {"x": 5, "y": 0},
                    }
                ],
            },
        )

    assert world.node("mira").position.to_dict() == {"x": 0.0, "y": 0.0}


def test_output_boundary_accepts_ai_isekai_node_and_edge_updates() -> None:
    world = make_world()
    world.set_movement_target("mira", (2, 0), 1.0)
    boundary = ProviderOutputBoundary(
        source="llm-test",
        allowed_rule_names={"move"},
        allowed_relationship_types={"trust"},
    )

    output = boundary.parse(
        world,
        {
            "summary": "Mira weighs trust and movement.",
            "node_updates": [
                {
                    "id": "mira",
                    "thought": "Atlas may help if I move carefully and keep the route visible.",
                    "action_tendencies": [
                        {
                            "rule": "move",
                            "weight": 0.6,
                            "ttl": 4,
                            "reason": "test route",
                        }
                    ],
                }
            ],
            "edge_updates": [
                {
                    "from": "mira",
                    "to": "atlas",
                    "relation": "trust",
                    "delta": 0.2,
                    "reason": "Atlas answered the signal.",
                }
            ],
            "metadata": {"model": "test-model"},
        },
    )

    effect_types = [effect.type for effect in output.effects]
    assert effect_types.count("thought_schedule_add") == 1
    assert "rule_pressure_add" in effect_types
    assert "relationship_delta" in effect_types
    assert "memory_add" in effect_types
    assert output.metadata["provider_output_boundary"]["node_update_count"] == 1
    assert output.metadata["provider_output_boundary"]["edge_update_count"] == 1
    assert output.metadata["relationship_round"]["edge_update_count"] == 1
    json.dumps(output.to_dict(), ensure_ascii=False)


def test_output_boundary_rejects_missing_node_references() -> None:
    world = make_world()

    with pytest.raises(ValueError, match="missing node"):
        ProviderOutputBoundary(source="llm-test").parse(
            world,
            {
                "summary": "Unknown target.",
                "effects": [
                    {
                        "type": "thought_bubble_add",
                        "target": "node:missing",
                        "text": "I should not exist.",
                    }
                ],
            },
        )


def test_output_boundary_rejects_unregistered_rule_and_relationship_names() -> None:
    world = make_world()
    boundary = ProviderOutputBoundary(
        source="llm-test",
        allowed_rule_names={"move"},
        allowed_relationship_types={"trust"},
    )

    with pytest.raises(ValueError, match="unregistered rule"):
        boundary.parse(
            world,
            {
                "summary": "Bad rule.",
                "effects": [
                    {
                        "type": "rule_pressure_add",
                        "target": "node:mira",
                        "rule": "attack",
                    }
                ],
            },
        )

    with pytest.raises(ValueError, match="unregistered relationship"):
        boundary.parse(
            world,
            {
                "summary": "Bad relationship.",
                "effects": [
                    {
                        "type": "relationship_delta",
                        "source": "node:mira",
                        "target": "node:atlas",
                        "relation": "hostility",
                    }
                ],
            },
        )


def test_accepted_output_still_requires_feedback_ingestion_to_affect_world() -> None:
    world = make_world()
    world.set_movement_target("mira", (2, 0), 1.0)
    output = ProviderOutputBoundary(
        source="llm-test", allowed_rule_names={"move"}
    ).parse(
        world,
        {
            "summary": "Pressure only.",
            "effects": [
                {
                    "type": "rule_pressure_add",
                    "target": "node:mira",
                    "rule": "move",
                    "weight": 0.4,
                    "ttl": 2,
                }
            ],
        },
    )

    assert world.node("mira").rule_pressures == []

    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source=output.source,
            actor_type="agent",
            actor_id=output.source,
            action="provider_pressure",
            summary=output.summary,
            effects=output.effects,
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )

    assert world.node("mira").rule_pressures[0]["rule"] == "movement"


def test_output_boundary_rejects_movement_pressure_without_movement_state() -> None:
    world = make_world()

    with pytest.raises(ValueError, match="cannot produce a grounded candidate"):
        ProviderOutputBoundary(
            source="llm-test",
            allowed_rule_names={"movement"},
        ).parse(
            world,
            {
                "summary": "Invented movement.",
                "effects": [
                    {
                        "type": "rule_pressure_add",
                        "target": "node:mira",
                        "rule": "move",
                        "weight": 0.4,
                        "ttl": 2,
                    }
                ],
            },
        )


def test_relationship_boundary_preserves_thought_and_normalizes_other_budgets() -> None:
    world = World("bounded-relationship")
    for index in range(40):
        world.add_node(f"node-{index:02d}", "person", f"Node {index}", (index, 0))
    active_ids = [f"node-{index:02d}" for index in range(10)]
    propagation_ids = [f"node-{index:02d}" for index in range(40)]
    long_thought = "这是一个明显超过四十八个字符的核心思考，它已经消耗了模型生成令牌，因此边界必须完整保留，不再做事后截断。"
    options = []
    updates = []
    for index, node_id in enumerate(active_ids):
        world.set_movement_target(node_id, (index + 1, 0), 0.5)
        option_id = f"option-{index}"
        options.append(
            {
                "option_id": option_id,
                "node_id": node_id,
                "rule": "movement",
                "action": "move",
                "target_id": "",
                "parameters": {},
                "expires_at_tick": 3,
            }
        )
        update = {
            "id": node_id,
            "thought": long_thought,
            "selected_action_option_id": option_id,
            "thought_bubbles": [{"text": f"模型气泡-{bubble}"} for bubble in range(6)],
            "rule_mods": [
                {
                    "rule": "move",
                    "weight": 4.0,
                    "ttl": 99,
                    "reason": "这个规则修改原因实在太长了",
                },
                {"rule": "ignored", "weight": 0.5, "ttl": 3},
            ],
            "action_tendencies": [
                {
                    "rule": "move",
                    "weight": -2.0,
                    "ttl": 1,
                    "reason": "这个行动倾向原因实在太长了",
                },
                {"rule": "ignored", "weight": 0.5, "ttl": 3},
            ],
        }
        updates.append(update)
    edges = [
        {
            "from": "node-00",
            "to": "node-01",
            "relation": "trust",
            "delta": 0.1,
            "reason": "这个关系变化原因也明显太长了",
        }
        for _ in range(20)
    ]

    output = ProviderOutputBoundary(
        source="bounded-test",
        required_active_node_count=10,
        expected_node_ids=set(active_ids),
        propagation_node_ids=set(propagation_ids),
        groundable_action_options=options,
    ).parse(
        world, {"summary": "摘要" * 100, "node_updates": updates, "edge_updates": edges}
    )

    boundary = output.metadata["provider_output_boundary"]
    assert len(output.summary) == 80
    assert boundary["node_update_count"] == 10
    assert boundary["edge_update_count"] == 12
    assert "thought_max_chars" not in boundary["relationship_text_limits"]
    assert boundary["required_action_node_count"] == 10
    assert boundary["accepted_action_node_count"] == 10
    assert output.metadata["relationship_round"]["observe_only_node_ids"] == []
    active_memories = [
        item
        for item in output.effects
        if item.type == "memory_add"
        and str(item.fields.get("text", "")).startswith("relationship thought: ")
    ]
    assert len(active_memories) >= 10
    assert (
        sum(
            str(item.fields["text"]).removeprefix("relationship thought: ")
            == long_thought
            for item in active_memories
        )
        == 10
    )
    assert not any(
        "模型气泡" in str(item.fields.get("text", "")) for item in output.effects
    )


def test_relationship_boundary_keeps_ten_thoughts_and_all_ten_actions() -> None:
    world = World("bounded-option-actions")
    active_ids = [f"node-{index:02d}" for index in range(10)]
    propagation_ids = [f"node-{index:02d}" for index in range(40)]
    options = []
    updates = []
    for index, node_id in enumerate(active_ids):
        world.add_node(node_id, "person", f"Node {index}", (index, 0))
        world.set_movement_target(node_id, (index + 1, 0), 0.5)
        option_id = f"option-{index}"
        options.append(
            {
                "option_id": option_id,
                "node_id": node_id,
                "rule": "movement",
                "action": "move",
                "target_id": "",
                "parameters": {},
                "expires_at_tick": 3,
            }
        )
        updates.append(
            {
                "id": node_id,
                "thought": f"我会先观察整体关系变化，同时评估自己下一步行动的真实影响-{index}",
                "selected_action_option_id": option_id,
                "action_weight": 0.5,
                "action_ttl": 3,
                "action_reason": "推进目标",
            }
        )
    for index in range(10, 40):
        world.add_node(f"node-{index:02d}", "person", f"Node {index}", (index, 0))

    output = ProviderOutputBoundary(
        source="bounded-test",
        required_active_node_count=10,
        expected_node_ids=set(active_ids),
        propagation_node_ids=set(propagation_ids),
        groundable_action_options=options,
        provider_job_id="relationship-job",
        source_tick=0,
    ).parse(world, {"summary": "bounded actions", "node_updates": updates})

    pressure_effects = [
        item for item in output.effects if item.type == "rule_pressure_add"
    ]
    boundary = output.metadata["provider_output_boundary"]
    assert len(pressure_effects) == 10
    assert boundary["required_action_node_count"] == 10
    assert boundary["accepted_action_node_count"] == 10
    assert "dropped_action_node_ids" not in boundary
    assert len(output.metadata["relationship_round"]["active_node_ids"]) == 10
    assert output.metadata["relationship_round"]["observe_only_node_ids"] == []


def test_relationship_boundary_rejects_one_observe_only_active_node() -> None:
    world = World("missing-active-action")
    active_ids = [f"node-{index:02d}" for index in range(10)]
    options = []
    updates = []
    for index, node_id in enumerate(active_ids):
        world.add_node(node_id, "person", f"Node {index}", (index, 0))
        world.set_movement_target(node_id, (index + 1, 0), 0.5)
        option_id = f"option-{index}"
        options.append(
            {
                "option_id": option_id,
                "node_id": node_id,
                "rule": "movement",
                "action": "move",
                "parameters": {},
                "expires_at_tick": 3,
            }
        )
        updates.append(
            {
                "id": node_id,
                "thought": f"节点 {index} 正在形成一个明确且可执行的本轮行动判断",
                "selected_action_option_id": option_id,
                "action_weight": 0.5,
                "action_ttl": 3,
                "action_reason": "执行计划",
            }
        )
    updates[-1].pop("selected_action_option_id")
    updates[-1]["observe_only_reason"] = "继续观察"

    with pytest.raises(ValueError, match="one selected action for every active node"):
        ProviderOutputBoundary(
            source="bounded-test",
            required_active_node_count=10,
            expected_node_ids=set(active_ids),
            propagation_node_ids=set(active_ids),
            groundable_action_options=options,
            provider_job_id="relationship-job",
            source_tick=0,
        ).parse(world, {"summary": "one action missing", "node_updates": updates})


@pytest.mark.parametrize(
    "missing_field", ["action_weight", "action_ttl", "action_reason"]
)
def test_relationship_boundary_rejects_incomplete_selected_action_fields(
    missing_field: str,
) -> None:
    world = World("incomplete-selected-action")
    active_ids = [f"node-{index:02d}" for index in range(10)]
    options = []
    updates = []
    for index, node_id in enumerate(active_ids):
        world.add_node(node_id, "person", f"Node {index}", (index, 0))
        world.set_movement_target(node_id, (index + 1, 0), 0.5)
        option_id = f"option-{index}"
        options.append(
            {
                "option_id": option_id,
                "node_id": node_id,
                "rule": "movement",
                "action": "move",
                "parameters": {},
                "expires_at_tick": 3,
            }
        )
        updates.append(
            {
                "id": node_id,
                "thought": f"节点 {index} 正在形成一个明确且可执行的本轮行动判断",
                "selected_action_option_id": option_id,
                "action_weight": 0.5,
                "action_ttl": 3,
                "action_reason": "执行计划",
            }
        )
    updates[-1].pop(missing_field)

    with pytest.raises(ValueError, match="without required fields"):
        ProviderOutputBoundary(
            source="bounded-test",
            required_active_node_count=10,
            expected_node_ids=set(active_ids),
            propagation_node_ids=set(active_ids),
            groundable_action_options=options,
            provider_job_id="relationship-job",
            source_tick=0,
        ).parse(world, {"summary": "one action field missing", "node_updates": updates})


def _repairable_relationship_round() -> tuple[World, list[str], list[dict], list[dict]]:
    world = World("repairable-option-round")
    active_ids = [f"node-{index:02d}" for index in range(10)]
    options = []
    updates = []
    for index, node_id in enumerate(active_ids):
        world.add_node(node_id, "person", f"Node {index}", (index, 0))
        world.set_movement_target(node_id, (index + 1, 0), 0.5)
        options.append(
            {
                "option_id": f"move-{index}",
                "node_id": node_id,
                "rule": "movement",
                "action": "move",
                "parameters": {},
                "expires_at_tick": 3,
            }
        )
        updates.append(
            {
                "id": node_id,
                "thought": f"节点 {index} 正在形成一个明确且可以执行的本轮行动判断",
                "selected_action_option_id": f"invented-{index}",
                "action_weight": 0.5,
                "action_ttl": 3,
                "action_reason": "向前侦察",
            }
        )
    for index in range(10, 40):
        world.add_node(f"node-{index:02d}", "person", f"Node {index}", (index, 0))
    return world, active_ids, options, updates


def test_relationship_boundary_repairs_invented_options_and_keeps_thoughts() -> None:
    world, active_ids, options, updates = _repairable_relationship_round()

    output = ProviderOutputBoundary(
        source="bounded-test",
        required_active_node_count=10,
        expected_node_ids=set(active_ids),
        propagation_node_ids=set(world.nodes),
        groundable_action_options=options,
        provider_job_id="relationship-job",
        source_tick=0,
    ).parse(world, {"summary": "repair invented ids", "node_updates": updates})

    boundary = output.metadata["provider_output_boundary"]
    repairs = boundary["action_option_repairs"]
    pressure_effects = [
        item for item in output.effects if item.type == "rule_pressure_add"
    ]
    thought_memories = [
        item
        for item in output.effects
        if item.type == "memory_add"
        and str(item.fields.get("text", "")).startswith("relationship thought: ")
    ]
    assert boundary["action_option_repair_count"] == 10
    assert len(repairs) == 10
    assert all(item["strategy"] == "invented_semantic_match" for item in repairs)
    assert {item["repaired_option_id"] for item in repairs} == {
        f"move-{index}" for index in range(10)
    }
    assert {item.fields["option_id"] for item in pressure_effects} == {
        f"move-{index}" for index in range(10)
    }
    assert len(thought_memories) >= 10


def test_relationship_boundary_never_transfers_a_cross_node_option() -> None:
    world, active_ids, options, updates = _repairable_relationship_round()
    updates[0]["selected_action_option_id"] = "move-1"

    output = ProviderOutputBoundary(
        source="bounded-test",
        required_active_node_count=10,
        expected_node_ids=set(active_ids),
        propagation_node_ids=set(world.nodes),
        groundable_action_options=options,
        provider_job_id="relationship-job",
        source_tick=0,
    ).parse(world, {"summary": "repair cross-node id", "node_updates": updates})

    repair = next(
        item
        for item in output.metadata["provider_output_boundary"]["action_option_repairs"]
        if item["node_id"] == "node-00"
    )
    pressures = [item for item in output.effects if item.type == "rule_pressure_add"]
    node_zero_pressure = next(
        item for item in pressures if item.fields.get("target") == "node:node-00"
    )
    assert repair["strategy"] == "cross_node_semantic_match"
    assert repair["foreign_option_node_ids"] == ["node-01"]
    assert repair["repaired_option_id"] == "move-0"
    assert node_zero_pressure.fields["option_id"] == "move-0"


def test_relationship_boundary_rejects_unrepairable_expired_node_options() -> None:
    world, active_ids, options, updates = _repairable_relationship_round()
    options[0]["expires_at_tick"] = -1

    with pytest.raises(ValueError, match="unavailable groundable action option"):
        ProviderOutputBoundary(
            source="bounded-test",
            required_active_node_count=10,
            expected_node_ids=set(active_ids),
            propagation_node_ids=set(world.nodes),
            groundable_action_options=options,
            provider_job_id="relationship-job",
            source_tick=0,
        ).parse(world, {"summary": "expired node option", "node_updates": updates})
