from __future__ import annotations

from copy import deepcopy

from ai_native_world_engine.core import RuleEngineSet, World
from ai_native_world_engine.core.projection_delta import (
    apply_projection_delta,
    projection_delta_from_incremental,
    projection_keyframe,
)


def _speech_world(*, listener_position: tuple[float, float] = (1, 0)) -> World:
    world = World("speech-world", {"north_gate_enemy_trace": True})
    world.add_node(
        "speaker",
        "person",
        "托尔",
        (0, 0),
        {"language": "common", "role": "guard"},
    )
    world.add_node(
        "listener",
        "person",
        "娜拉",
        listener_position,
        {"language": "common"},
    )
    return world


def _add_speech_pressure(world: World, **overrides: object) -> None:
    pressure: dict[str, object] = {
        "rule": "speak",
        "pressure_id": "speech-pressure-1",
        "intent": "warn",
        "target": "listener",
        "facts": ["north_gate_enemy_trace"],
        "ttl": 8,
        "root_causality_id": "cause:north-gate",
        "caused_by": ["thought:warn-listener"],
    }
    pressure.update(overrides)
    world.node("speaker").rule_pressures.append(pressure)


def test_deterministic_warning_delivers_once_with_causal_listener_pressure() -> None:
    world = _speech_world()
    _add_speech_pressure(world)

    world.step(RuleEngineSet.from_scenario(["speak"]))

    action = next(iter(world.active_actions.values()))
    event = world.speech_events[0]
    assert action.definition_id == "speak"
    assert action.channel == "social"
    assert action.behavior_label == "正在向娜拉示警"
    assert action.root_causality_id == "cause:north-gate"
    assert event["content"] == "北门发现敌踪，先不要独自过河。"
    assert event["delivered_to"] == ["listener"]
    assert event["understood_by"] == ["listener"]
    assert event["root_causality_id"] == action.root_causality_id
    assert action.id in event["caused_by"]

    listener = world.node("listener")
    assert listener.attributes["received_messages"][0]["speech_event_id"] == event["id"]
    assert event["content"] in listener.memories[0]["text"]
    appraisal = next(
        item for item in listener.rule_pressures if item["rule"] == "speech_appraisal"
    )
    assert appraisal["root_causality_id"] == action.root_causality_id
    assert appraisal["caused_by"] == [event["id"]]

    bubbles = [
        item
        for item in world.presentation.recent()
        if item["payload"].get("type") == "speech_bubble"
    ]
    assert len(bubbles) == 1
    assert bubbles[0]["payload"]["text"] == event["content"]

    world.step(RuleEngineSet.from_scenario(["speak"]))
    bubbles_after_completion = [
        item
        for item in world.presentation.recent()
        if item["payload"].get("type") == "speech_bubble"
    ]
    assert bubbles_after_completion == bubbles
    assert world.active_actions == {}


def test_out_of_range_speech_records_failure_without_listener_consequence() -> None:
    world = _speech_world(listener_position=(20, 0))
    relationship_snapshot = deepcopy(world.snapshot()["relationships"])
    _add_speech_pressure(world, max_range=3)

    world.step(RuleEngineSet.from_scenario(["speak"]))

    event = world.speech_events[0]
    listener = world.node("listener")
    assert event["delivered_to"] == []
    assert event["failed_deliveries"][0]["reason"] == "out_of_range"
    assert "received_messages" not in listener.attributes
    assert listener.memories == []
    assert listener.rule_pressures == []
    assert world.snapshot()["relationships"] == relationship_snapshot
    assert any(
        item["payload"].get("type") == "speech_bubble"
        for item in world.presentation.recent()
    )


def test_unshared_language_delivers_sound_without_understanding_or_appraisal() -> None:
    world = _speech_world()
    world.node("listener").attributes["language"] = "river"
    _add_speech_pressure(world, language="common")

    world.step(RuleEngineSet.from_scenario(["speak"]))

    event = world.speech_events[0]
    listener = world.node("listener")
    assert event["delivered_to"] == ["listener"]
    assert event["understood_by"] == []
    assert "received_messages" not in listener.attributes
    assert listener.memories == []
    assert listener.rule_pressures == []


def test_witness_gets_independent_memory_and_appraisal_edges() -> None:
    world = _speech_world()
    witness = world.add_node(
        "witness", "person", "伊洛", (2, 0), {"language": "common"}
    )
    _add_speech_pressure(world, witness_range=3)

    world.step(RuleEngineSet.from_scenario(["speak"]))

    event = world.speech_events[0]
    assert event["witness_ids"] == ["witness"]
    assert witness.attributes["received_messages"][0]["witness"] is True
    assert witness.memories[0]["metadata"]["caused_by"] == [event["id"]]
    pressure = next(
        item for item in witness.rule_pressures if item["rule"] == "speech_appraisal"
    )
    assert pressure["witness"] is True
    assert pressure["root_causality_id"] == event["root_causality_id"]
    assert pressure["caused_by"] == [event["id"]]


def test_unauthorized_command_is_delivered_without_obedience_or_relationship_change() -> None:
    world = _speech_world()
    before_relationships = deepcopy(world.snapshot()["relationships"])
    _add_speech_pressure(
        world,
        intent="command",
        content="立即守住北门。",
        facts=[],
    )

    world.step(RuleEngineSet.from_scenario(["speak"]))

    event = world.speech_events[0]
    listener = world.node("listener")
    assert event["command_authority"]["listener"]["authorized"] is False
    assert world.snapshot()["relationships"] == before_relationships
    assert "obedience" not in listener.attributes
    assert any(
        item["rule"] == "speech_appraisal" for item in listener.rule_pressures
    )


def test_deceptive_claim_is_recorded_without_becoming_world_truth() -> None:
    world = _speech_world()
    false_claim = {
        "proposition": "north_gate_safe",
        "speaker_belief": "false",
        "deceptive": True,
    }
    _add_speech_pressure(
        world,
        intent="deceive",
        content="北门已经安全了。",
        claims=[false_claim],
        facts=[],
    )

    world.step(RuleEngineSet.from_scenario(["speak"]))

    assert world.speech_events[0]["claims"] == [false_claim]
    assert world.attributes == {
        "north_gate_enemy_trace": True,
    }


def test_duplicate_speech_is_suppressed_during_cooldown() -> None:
    world = _speech_world()
    _add_speech_pressure(world, pressure_id="", cooldown_ticks=4)
    engine = RuleEngineSet.from_scenario(["speak"])

    world.step(engine)
    world.step(engine)
    world.step(engine)

    assert len(world.speech_events) == 1
    assert len(
        [
            item
            for item in world.presentation.recent()
            if item["payload"].get("type") == "speech_bubble"
        ]
    ) == 1


def test_speech_bubble_is_retained_when_projection_delta_is_applied() -> None:
    world = _speech_world()
    keyframe = projection_keyframe(world, sequence=0)
    incremental = {
        "commit": {
            "sequence": 1,
            "resulting_tick": 1,
            "resulting_phase": "running",
            "state_delta": {"tick": 1},
        },
        "presentation_events": [
            {
                "sequence": 1,
                "tick": 1,
                "payload": {
                    "type": "speech_bubble",
                    "node_id": "speaker",
                    "text": "北门发现敌踪。",
                },
            }
        ],
    }

    delta = projection_delta_from_incremental(incremental).to_dict()
    projected = apply_projection_delta(keyframe, delta)

    assert delta["speech_bubbles"][0]["text"] == "北门发现敌踪。"
    assert projected["speech_bubbles"] == delta["speech_bubbles"]
