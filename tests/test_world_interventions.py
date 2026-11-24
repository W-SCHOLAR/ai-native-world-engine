from __future__ import annotations

from ai_native_world_engine.core import (
    AUDIENCE_WORLD_INPUT_SOURCE,
    WORLD_INTERVENTION_SCHEMA,
    InterventionValidator,
    InterventionVisibilityResolver,
    RunConfig,
    World,
    WorldIntervention,
    compile_world_intervention,
    run,
)


def _intervention(**overrides: object) -> WorldIntervention:
    values = {
        "id": "notice-1",
        "intervention_type": "public_notice",
        "scope": {"kind": "world", "world_id": "test-world"},
        "payload": {"text": "The bridge is closed.", "importance": 0.8},
        "visibility": {
            "mode": "public",
            "publisher_node_ids": ["notice-board"],
            "recipient_node_ids": ["mira"],
            "max_recipients": 2,
        },
        "duration": 2,
        "source": AUDIENCE_WORLD_INPUT_SOURCE,
    }
    values.update(overrides)
    return WorldIntervention(**values)  # type: ignore[arg-type]


def test_world_intervention_round_trips_as_json_contract() -> None:
    intervention = _intervention()

    payload = intervention.to_dict()
    restored = WorldIntervention.from_dict(payload)

    assert payload["schema"] == WORLD_INTERVENTION_SCHEMA
    assert payload["action"] == "world_intervention"
    assert restored.to_dict() == payload
    assert InterventionValidator().validate(restored).valid is True


def test_validator_rejects_direct_character_internal_control() -> None:
    intervention = _intervention(
        effects=[
            {
                "type": "key_character_state",
                "target": "node:mira",
                "value": {"emotion": "devoted"},
            }
        ]
    )

    report = InterventionValidator().validate(intervention)

    assert report.valid is False
    assert "directly controls character internals" in report.errors[0]


def test_relationship_visibility_is_deterministic_and_bounded() -> None:
    world = World("visibility-world")
    for node_id in ("source", "neighbor-a", "neighbor-b", "unrelated"):
        world.add_node(node_id, "person", node_id, (0, 0))
    world.add_relationship("source", "neighbor-b", "trust", 0.5)
    world.add_relationship("source", "neighbor-a", "trust", 0.8)
    world.add_relationship("neighbor-a", "unrelated", "trust", 0.2)
    intervention = _intervention(
        visibility={
            "mode": "relationship",
            "seed_node_ids": ["source"],
            "relationship_types": ["trust"],
            "max_hops": 1,
            "max_recipients": 2,
        }
    )

    recipients = InterventionVisibilityResolver().resolve(world, intervention)

    assert recipients == ["source", "neighbor-a"]


def test_location_and_organization_visibility_use_world_facts() -> None:
    world = World("visibility-world")
    world.add_node("clinic", "location", "Clinic", (0, 0))
    world.add_node("clinic-org", "organization", "Clinic Org", (0, 0))
    world.add_node("doctor", "person", "Doctor", (0, 0), {"home_location": "clinic"})
    world.add_node("nurse", "person", "Nurse", (0, 0))
    world.add_node("outsider", "person", "Outsider", (0, 0))
    world.add_relationship("nurse", "clinic-org", "member_of", 0.9)

    by_location = InterventionVisibilityResolver().resolve(
        world,
        _intervention(
            visibility={
                "mode": "location",
                "location_node_ids": ["clinic"],
                "max_recipients": 4,
            }
        ),
    )
    by_organization = InterventionVisibilityResolver().resolve(
        world,
        _intervention(
            visibility={
                "mode": "organization",
                "organization_node_ids": ["clinic-org"],
                "max_recipients": 4,
            }
        ),
    )

    assert by_location == ["clinic", "doctor"]
    assert by_organization == ["clinic-org", "nurse"]
    assert "outsider" not in by_location + by_organization


def test_compiler_adds_receipt_and_only_resolved_recipient_memories() -> None:
    world = World("compile-world")
    world.add_node("notice-board", "organization", "Notice Board", (0, 0))
    world.add_node("mira", "person", "Mira", (0, 0))
    world.add_node("atlas", "person", "Atlas", (0, 0))

    compiled = compile_world_intervention(world, _intervention())
    effects = [effect.to_dict() for effect in compiled.effects]

    assert compiled.recipient_node_ids == ("notice-board", "mira")
    assert effects[0]["type"] == "world_state"
    assert [
        effect["target"] for effect in effects if effect["type"] == "memory_add"
    ] == [
        "node:notice-board",
        "node:mira",
    ]
    assert all(effect.get("target") != "node:atlas" for effect in effects)


def test_run_harness_applies_structured_intervention_with_audit_and_trace() -> None:
    intervention = _intervention(
        visibility={
            "mode": "direct",
            "recipient_node_ids": ["mira"],
            "max_recipients": 1,
        },
        effects=[
            {
                "type": "rule_pressure_add",
                "target": "node:mira",
                "rule": "move",
                "weight": 0.4,
                "ttl": 1,
                "reason": "public notice changes travel plans",
            }
        ],
    ).to_dict()

    result = run(
        RunConfig(scenario="seed", seed=7, ticks=1, interventions=[intervention])
    ).to_dict()
    mira = next(node for node in result["snapshot"]["nodes"] if node["id"] == "mira")
    atlas = next(node for node in result["snapshot"]["nodes"] if node["id"] == "atlas")
    audit = result["intervention_audits"][0]
    trace = next(
        trace for trace in result["traces"] if trace["kind"] == "runtime_intervention"
    )

    assert audit["accepted"] is True
    assert audit["schema"] == WORLD_INTERVENTION_SCHEMA
    assert audit["intervention_type"] == "public_notice"
    assert audit["recipient_node_ids"] == ["mira"]
    assert any(
        memory["metadata"]["intervention_id"] == "notice-1"
        for memory in mira["memories"]
    )
    assert all(
        memory.get("metadata", {}).get("intervention_id") != "notice-1"
        for memory in atlas["memories"]
    )
    assert result["snapshot"]["attributes"]["world_intervention_notice_1"][
        "recipient_node_ids"
    ] == ["mira"]
    assert trace["observed"]["visibility_mode"] == "direct"
    assert trace["observed"]["recipient_count"] == 1


def test_legacy_raw_intervention_remains_supported() -> None:
    legacy = {
        "id": "legacy-1",
        "tick": 0,
        "source": "legacy-test",
        "effects": [
            {
                "type": "world_state",
                "field": "legacy_marker",
                "value": True,
            }
        ],
    }

    result = run(
        RunConfig(scenario="seed", seed=7, ticks=1, interventions=[legacy])
    ).to_dict()

    assert result["snapshot"]["attributes"]["legacy_marker"] is True
    assert result["intervention_audits"][0]["accepted"] is True
    assert "schema" not in result["intervention_audits"][0]
