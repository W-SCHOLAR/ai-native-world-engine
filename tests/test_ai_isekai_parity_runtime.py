from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    DeterministicRelationshipLensProvider,
    FeedbackIngestor,
    KeyCharacterContinuityApplier,
    ProviderContext,
    RunConfig,
    SocialRippleLedger,
    World,
    WorldArchive,
    effect,
    extract_json_provider_output,
    relationship_lens_ids,
    run,
)


def test_openai_compatible_response_extracts_provider_json() -> None:
    data = extract_json_provider_output(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"ok","node_updates":[{"id":"mira","thought":"move carefully"}]}',
                    }
                }
            ]
        }
    )

    assert data["summary"] == "ok"
    assert data["node_updates"][0]["id"] == "mira"


def test_ai_isekai_relationship_lens_provider_emits_structured_pressure() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    provider = DeterministicRelationshipLensProvider("war", max_targets=2)
    output = provider.observe(ProviderContext(world, world.tick, world.snapshot()))
    effects = [item.to_dict() for item in output.effects]

    assert "war" in relationship_lens_ids()
    assert output.metadata["relationship_lens"]["id"] == "war"
    assert {item["type"] for item in effects} == {
        "thought_bubble_add",
        "rule_pressure_add",
        "relationship_delta",
        "memory_add",
    }
    assert all(item.get("origin") == "ai_isekai_relationship_lens" for item in effects)


def test_key_character_lifecycle_marks_overdue_without_model_self_claims() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    world.tick = 5
    node = world.node("key-albert-einstein")
    node.key_character.update(
        {
            "agent_layer": "key_character",
            "commitments": [
                {
                    "target": "key-marie-curie",
                    "status": "pending",
                    "summary": "Share a clear research plan.",
                    "created_tick": 1,
                }
            ],
            "peer_interactions": [
                {
                    "target": "key-marie-curie",
                    "status": "unresolved",
                    "stance": "conflict",
                    "summary": "Disagree about evidence.",
                    "created_tick": 1,
                }
            ],
        }
    )

    result = KeyCharacterContinuityApplier().build_effects(world)
    effects = [item.to_dict() for item in result.effects]
    lifecycle = [item for item in effects if item.get("origin") == "key_character_lifecycle"]
    state = next(item for item in effects if item["type"] == "key_character_state" and item["target"] == "node:key-albert-einstein")

    assert any(change["status"] == "overdue" for change in state["value"]["lifecycle_changes"])
    assert any(change["status"] == "stale" for change in state["value"]["lifecycle_changes"])
    assert lifecycle


def test_social_ripples_and_world_archive_are_exported() -> None:
    world = World("ripple-test")
    world.add_node("mira", "person", "Mira", (0, 0))
    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="agent",
            actor_type="agent",
            actor_id="agent",
            action="pressure",
            summary="pressure",
            effects=[
                effect("thought_bubble_add", target="node:mira", text="I should move.", source="agent"),
                effect("rule_pressure_add", target="node:mira", rule="move", weight=0.8, ttl=2, source="agent"),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )
    world.tick = 1
    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="rule-engine",
            actor_type="node",
            actor_id="mira",
            action="move",
            summary="Mira performed move.",
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )

    ripples = SocialRippleLedger().build_report(world)
    archive = WorldArchive().export(world)

    assert ripples["totals"]["scatter_count"] >= 3
    assert ripples["totals"]["chain_count"] >= 1
    assert archive["schema"] == "world_archive_v1"
    assert archive["social_ripples"]["totals"]["chain_count"] >= 1
    assert archive["replay"]["consistency"]["node_count_matches"] is True


def test_run_result_includes_social_ripples_and_world_archive() -> None:
    data = run(RunConfig(scenario="enterprise_earth", seed=7, ticks=1)).to_dict()

    assert "social_ripples" in data
    assert "world_archive" in data
    assert data["world_archive"]["schema"] == "world_archive_v1"
