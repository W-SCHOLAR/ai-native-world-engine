import json

from ai_native_world_engine.core import (
    ACTIVE_NODE_LIMIT,
    RIPPLE_TARGETS_PER_ACTIVE,
    THOUGHT_SLICE_COUNT,
    DeterministicRelationshipRoundProvider,
    RelationshipNodeUpdate,
    RelationshipRoundApplier,
    RunConfig,
    World,
    project_run_for_viewer,
    run,
)
from ai_native_world_engine.core.relationship_round import (
    ACTIVE_BUBBLE_INTERVAL_BASE,
    ACTIVE_BUBBLE_TTL,
    _bubble_interval,
    _hash_fraction,
)


def test_relationship_round_caps_active_nodes_slices_thoughts_and_ripples() -> None:
    world = World("relationship-round")
    updates = []
    for index in range(ACTIVE_NODE_LIMIT + 3):
        node_id = f"node-{index:02d}"
        world.add_node(node_id, "organization_member", f"成员 {index}", (index, 0), {"agent_layer": "relationship_network_member"})
        world.set_movement_target(node_id, (index + 1, 0), 0.5)
        updates.append(
            RelationshipNodeUpdate(
                node_id=node_id,
                thought="我们需要先理解组织压力，再协调资源、行动节奏和成员之间的信任。",
                action_tendencies=[{"rule": "move", "weight": 0.6, "ttl": 4, "reason": "需要靠近协作目标"}],
            )
        )
    for active_index in range(ACTIVE_NODE_LIMIT):
        for ripple_index in range(RIPPLE_TARGETS_PER_ACTIVE):
            ripple_id = f"ripple-{active_index:02d}-{ripple_index}"
            world.add_node(ripple_id, "organization_member", f"响应 {active_index}-{ripple_index}", (active_index, ripple_index + 1))
            world.set_movement_target(ripple_id, (active_index + 1, ripple_index + 1), 0.5)
            world.add_relationship(f"node-{active_index:02d}", ripple_id, "influence", 0.8)

    result = RelationshipRoundApplier().build_effects(world, updates, source="test-round")
    effect_dicts = [item.to_dict() for item in result.effects]
    schedules = [item for item in effect_dicts if item["type"] == "thought_schedule_add"]
    active_schedules = [item for item in schedules if item["origin"] == "active_node"]
    ripple_schedules = [item for item in schedules if item["origin"] == "ripple_response"]
    active_actions = [item for item in effect_dicts if item["type"] == "action_bullet_add" and item.get("origin") == "active_node"]
    ripple_actions = [item for item in effect_dicts if item["type"] == "action_bullet_add" and item.get("origin") == "ripple_response"]
    rule_pressures = [item for item in effect_dicts if item["type"] == "rule_pressure_add"]

    assert result.active_node_ids == [f"node-{index:02d}" for index in range(ACTIVE_NODE_LIMIT)]
    assert "node-12" not in result.active_node_ids
    assert len(active_schedules) == ACTIVE_NODE_LIMIT
    assert len(ripple_schedules) == ACTIVE_NODE_LIMIT * RIPPLE_TARGETS_PER_ACTIVE
    assert sum(len(item["ripple_targets"]) for item in active_schedules) == ACTIVE_NODE_LIMIT * RIPPLE_TARGETS_PER_ACTIVE
    assert active_actions == []
    assert ripple_actions == []
    assert len(rule_pressures) == ACTIVE_NODE_LIMIT + ACTIVE_NODE_LIMIT * RIPPLE_TARGETS_PER_ACTIVE
    assert all(len(targets) == RIPPLE_TARGETS_PER_ACTIVE for targets in result.ripple_targets_by_active.values())
    assert active_schedules[0]["slice_count"] == THOUGHT_SLICE_COUNT
    assert active_schedules[0]["ttl"] == ACTIVE_BUBBLE_TTL
    active_interval = active_schedules[0]["interval"]
    assert active_interval == ACTIVE_BUBBLE_INTERVAL_BASE == 10.0
    assert 0.15 <= active_schedules[0]["delay"] <= 0.85
    assert 9.15 <= active_schedules[-1]["delay"] <= 9.85
    assert all(item["slice_count"] == 1 for item in ripple_schedules)
    assert all(item["ttl"] == 6.0 for item in ripple_schedules)
    assert all(item["ripple_from"] for item in ripple_schedules)
    assert all(
        [target["influence_order"] for target in item["ripple_targets"]]
        == [0, 1, 2]
        for item in active_schedules
    )
    assert next(item for item in rule_pressures if item.get("origin") == "ripple_response")["weight"] == 0.21
    json.dumps(effect_dicts, ensure_ascii=False)


def test_relationship_round_keeps_visible_output_but_suppresses_static_move_pressure() -> None:
    world = World("static-relationship-round")
    world.add_node("static", "organization_member", "静态成员", (0, 0))
    update = RelationshipNodeUpdate(
        node_id="static",
        thought="我会继续观察协作网络。",
        action_tendencies=[{"rule": "move", "weight": 0.6, "ttl": 4}],
    )

    result = RelationshipRoundApplier().build_effects(world, [update], source="test-round")
    effects = [item.to_dict() for item in result.effects]

    assert any(item["type"] == "memory_add" for item in effects)
    assert any(item["type"] == "thought_schedule_add" for item in effects)
    assert not any(item["type"] == "action_bullet_add" for item in effects)
    assert not any(item["type"] == "rule_pressure_add" for item in effects)


def test_relationship_interval_is_fixed_for_minute_pacing() -> None:
    source = "test-round"
    node_id = "node-00"
    fraction = _hash_fraction(f"{source}:{node_id}:gap")
    assert int(fraction * 1000) == 193
    assert _bubble_interval(node_id, source) == ACTIVE_BUBBLE_INTERVAL_BASE == 10.0


def test_relationship_round_projection_preserves_scheduled_metadata() -> None:
    result = run(
        RunConfig(
            scenario="enterprise_earth",
            seed=5,
            ticks=1,
            provider=DeterministicRelationshipRoundProvider(rule="move"),
        )
    )

    projection = project_run_for_viewer(result).to_dict()
    scheduled = [item for item in projection["thoughts"] if item.get("origin") == "active_node"]
    ripple = [item for item in projection["thoughts"] if item.get("origin") == "ripple_response"]
    scheduled_actions = [item for item in projection["actions"] if item.get("origin") == "active_node"]
    ripple_actions = [item for item in projection["actions"] if item.get("origin") == "ripple_response"]

    assert scheduled == []
    assert scheduled_actions == []
    assert ripple_actions == []
    assert ripple == []
    grounded_action_cues = [
        effect
        for action in projection["grounded_actions"]
        for effect in action["effects"]
        if effect["type"] == "action_bullet_add"
    ]
    assert grounded_action_cues
    assert all(item["text"] for item in grounded_action_cues)
    assert result.to_dict()["provider_outputs"][0]["relationship_round"]["active_node_count"] == ACTIVE_NODE_LIMIT
    json.dumps(projection, ensure_ascii=False)
