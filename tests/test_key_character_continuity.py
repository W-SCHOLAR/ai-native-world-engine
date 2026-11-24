import json

from ai_native_world_engine.core import (
    ACTIVE_NODE_LIMIT,
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    DeterministicEnterpriseAgentProvider,
    DeterministicKeyCharacterContinuityProvider,
    FeedbackIngestor,
    INFLUENCE_CIRCLE_LIMIT,
    KEY_CHARACTER_MAX_ACTIVE,
    KeyCharacterContinuityApplier,
    ProviderContext,
    RunConfig,
    World,
    project_run_for_viewer,
    run,
)
from ai_native_world_engine.core.key_character_continuity import (
    KEY_CHARACTER_BUBBLE_TTL,
    KEY_CHARACTER_INFLUENCE_BUBBLE_MAX,
    KEY_CHARACTER_THOUGHT_SLICE_COUNT,
    KEY_CHARACTER_THOUGHT_SLICE_MIN_COUNT,
)


def test_key_character_continuity_uses_generic_salience_not_life_fields() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    key = world.node("key-albert-einstein")
    report = KeyCharacterContinuityApplier().salience_report(world, key)

    assert report["score"] >= 3.0
    assert "identity_anchor" in report["reasons"]

    key.attributes["health"] = 100
    assert KeyCharacterContinuityApplier().salience_report(world, key) == report


def test_key_character_provider_writes_continuity_without_static_influence_pressure() -> None:
    world = World.scenario("enterprise_earth", seed=11)
    provider = DeterministicKeyCharacterContinuityProvider()
    output = provider.observe(ProviderContext(world, world.tick, world.snapshot()))
    output_effects = [item.to_dict() for item in output.effects]
    visible_thoughts = [
        item
        for item in output_effects
        if item["type"] == "thought_bubble_add"
        and item.get("origin") == "key_character_continuity"
    ]
    visible_influence = [
        item
        for item in output_effects
        if item["type"] == "thought_bubble_add"
        and item.get("origin") == "key_character_influence"
    ]

    thought_groups: dict[str, list[dict]] = {}
    for item in visible_thoughts:
        thought_groups.setdefault(item["target"], []).append(item)
    for items in thought_groups.values():
        items.sort(key=lambda item: item["sequence_index"])
        assert len(items) in {
            KEY_CHARACTER_THOUGHT_SLICE_MIN_COUNT,
            KEY_CHARACTER_THOUGHT_SLICE_COUNT,
        }
        assert all(item["ttl"] == KEY_CHARACTER_BUBBLE_TTL for item in items)
        assert 0.0 <= items[0]["delay"] <= 10.0
        if len(items) > 1:
            interval = items[1]["delay"] - items[0]["delay"]
            assert 6.2 <= interval <= 7.8

    influence_groups: dict[str, list[dict]] = {}
    for item in visible_influence:
        influence_groups.setdefault(item["influenced_by"], []).append(item)
    for items in influence_groups.values():
        items.sort(key=lambda item: item["delay"])
        assert len(items) <= KEY_CHARACTER_INFLUENCE_BUBBLE_MAX
        for response_index, item in enumerate(items):
            assert 2.0 + response_index * 5.6 <= item["delay"] <= 4.4 + response_index * 5.6

    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source=output.source,
            actor_type="agent",
            actor_id=provider.name,
            action="key_character_continuity",
            summary=output.summary,
            effects=output.effects,
            apply_mode=APPLY_AUTHORITATIVE,
            metadata=output.metadata,
        ),
    )

    active = [
        node
        for node in world.nodes.values()
        if node.key_character.get("agent_layer") == "key_character" and node.key_character.get("status") == "active"
    ]
    influenced_ids = {
        str(event["payload"].get("node_id", ""))
        for event in world.presentation.recent()
            if event["payload"].get("origin") == "key_character_influence"
    }
    influenced = [node for node in world.nodes.values() if node.id in influenced_ids]
    influenced_actions = [
        bullet
        for event in world.presentation.recent()
        if event["payload"].get("origin") == "key_character_influence"
        and event["payload"].get("type") == "action_bullet"
        for bullet in [event["payload"]]
    ]
    active_actions = [
        bullet
        for event in world.presentation.recent()
        if event["payload"].get("origin") == "key_character_continuity"
        and event["payload"].get("type") == "action_bullet"
        for bullet in [event["payload"]]
    ]

    assert len(active) == KEY_CHARACTER_MAX_ACTIVE
    assert all(node.key_character.get("salience_score", 0) >= 3.0 for node in active)
    assert all(node.key_character.get("goal") for node in active)
    assert all(node.key_character.get("current_step") for node in active)
    assert all(node.key_character.get("peer_interactions") for node in active)
    assert all(node.key_character.get("commitments") for node in active)
    assert all(len(node.key_character.get("influence_circle", [])) <= INFLUENCE_CIRCLE_LIMIT for node in active)
    assert influenced
    assert active_actions == []
    assert influenced_actions == []
    assert all(node.type == "organization_member" for node in influenced)
    assert all(not node.key_character for node in influenced)
    assert any(
        pressure.get("origin") == "key_character_plan"
        for node in active
        for pressure in node.rule_pressures
    )
    assert not any(
        pressure.get("origin") == "key_character_influence"
        for node in influenced
        for pressure in node.rule_pressures
    )
    json.dumps(world.snapshot(), ensure_ascii=False)


def test_key_character_continuity_suppresses_move_pressure_after_targets_are_cleared() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    for node in world.nodes.values():
        if node.type == "key_character":
            node.movement_target = None
            node.movement_speed = 0.0

    result = KeyCharacterContinuityApplier().build_effects(world)
    effects = [item.to_dict() for item in result.effects]

    assert len(result.active_character_ids) == KEY_CHARACTER_MAX_ACTIVE
    assert any(item["type"] == "thought_bubble_add" for item in effects)
    assert not any(item["type"] == "action_bullet_add" for item in effects)
    assert not any(item["type"] == "rule_pressure_add" for item in effects)


def test_enterprise_agent_provider_combines_relationship_round_and_key_continuity_projection() -> None:
    result = run(
        RunConfig(
            scenario="enterprise_earth",
            seed=7,
            ticks=1,
            provider=DeterministicEnterpriseAgentProvider(),
        )
    )

    data = result.to_dict()
    provider_output = data["provider_outputs"][0]
    projection = project_run_for_viewer(result).to_dict()
    characters = projection["characters"]
    einstein = next(item for item in characters if item["id"] == "key-albert-einstein")
    influence_thoughts = [
        item
        for item in projection["thoughts"]
        if item.get("origin") == "key_character_influence"
    ]
    influence_actions = [
        item
        for item in projection["actions"]
        if item.get("origin") == "key_character_influence"
    ]

    assert provider_output["relationship_round"]["active_node_count"] == ACTIVE_NODE_LIMIT
    assert provider_output["key_character_continuity"]["active_character_count"] == KEY_CHARACTER_MAX_ACTIVE
    assert einstein["key_character"]["status"] == "active"
    assert einstein["key_character"]["goal"]
    assert einstein["key_character"]["current_step"]
    assert einstein["key_character"]["influence_circle_count"] <= INFLUENCE_CIRCLE_LIMIT
    assert influence_thoughts == []
    assert influence_actions == []
    json.dumps(projection, ensure_ascii=False)
