from ai_native_world_engine.core import RuleEngineSet, World
from ai_native_world_engine.core.action_grounding import ENTERPRISE_AGENT_RULES
from ai_native_world_engine.scenarios import planet_rule_packages


def test_planet_activity_packages_complete_a_no_llm_world_loop() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    engine = RuleEngineSet.from_scenario(
        ENTERPRISE_AGENT_RULES,
        extra_packages=planet_rule_packages(),  # type: ignore[arg-type]
    )

    for _ in range(9):
        world.step(engine)

    action_payloads = [
        event["payload"]
        for event in world.events.recent()
        if event.get("kind") == "action_feedback"
    ]
    action_names = {str(item.get("action", "")) for item in action_payloads}

    assert {
        "planet_observe",
        "speak",
        "planet_organization",
        "planet_work",
        "planet_relationship",
        "planet_economy",
        "planet_knowledge",
    }.issubset(action_names)
    assert world.attributes["planet_activity_cycle"] == 1
    assert world.node("org-science-council").attributes["latest_decision"]
    assert world.node("org-science-council:laboratory-network").attributes[
        "work_output"
    ] == "cross_domain_evidence_packet"
    assert world.node("org-logistics-grid").attributes["economy"][
        "latest_allocation"
    ]
    assert world.node("key-albert-einstein").attributes["publications"]


def test_planet_communication_uses_shared_speech_event_and_causality() -> None:
    world = World.scenario("enterprise_earth", seed=11)
    engine = RuleEngineSet.from_scenario(
        ENTERPRISE_AGENT_RULES,
        extra_packages=planet_rule_packages(),  # type: ignore[arg-type]
    )

    for _ in range(3):
        world.step(engine)

    event = next(
        item
        for item in world.speech_events
        if item["speaker_id"] == "key-wangari-maathai"
    )
    assert event["recipient_ids"] == ["key-marie-curie"]
    assert event["delivered_to"] == ["key-marie-curie"]
    assert event["content"] == "气候与公共健康信号出现关联异常，需要共同验证。"
    assert event["root_causality_id"] == "planet-cycle:0"
    listener = world.node("key-marie-curie")
    pressure = next(
        item for item in listener.rule_pressures if item["rule"] == "speech_appraisal"
    )
    assert pressure["caused_by"] == [event["id"]]
