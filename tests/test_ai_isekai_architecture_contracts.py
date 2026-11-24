import json

import pytest

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    APPLY_OBSERVED,
    ActionFeedback,
    AgentRegistry,
    FeedbackIngestor,
    KeyCharacterAgentOutput,
    KeyCharacterPressure,
    MemoryPressure,
    MemoryQuery,
    PressureActionTraceLedger,
    RelationshipAgentOutput,
    RelationshipPressure,
    RuleCandidate,
    RuleEngineSet,
    RulePressure,
    StructuredPressureView,
    World,
    effect,
    target,
)


def make_world() -> World:
    world = World("contracts")
    world.add_node("mira", "person", "米拉", (0, 0), {"alive": True})
    world.add_node("atlas", "organization", "阿特拉斯", (2, 0))
    return world


def test_feedback_normalization_serialization_and_observed_mode_do_not_change_facts() -> None:
    world = make_world()
    before = world.node("mira").position.to_dict()

    result = FeedbackIngestor().ingest(
        world,
        {
            "action": "claim_move",
            "effects": [
                {
                    "type": "node_position",
                    "target": "node:mira",
                    "position": {"x": 9, "y": 9},
                }
            ],
        },
    )

    assert result["source"] == "unknown"
    assert result["actor_type"] == "system"
    assert result["targets"] == []
    assert result["apply_mode"] == APPLY_OBSERVED
    assert world.node("mira").position.to_dict() == before
    assert world.events.recent()[0]["kind"] == "action_feedback"
    json.dumps(result, ensure_ascii=False)


def test_authoritative_feedback_applies_effects_and_records_delta_errors() -> None:
    world = make_world()
    feedback = ActionFeedback(
        source="test",
        actor_type="system",
        actor_id="tester",
        action="apply_effects",
        summary="应用多种效果",
        targets=[target("node", "mira")],
        effects=[
            effect("node_state", target="node:mira", field="mood", value="focused"),
            effect("node_position", target="node:mira", position={"x": 1, "y": 1}),
            effect("relationship_delta", source="node:mira", target="node:atlas", relation="member_of", delta=0.4),
            effect("memory_add", target="node:mira", text="记住一次测试", source="test"),
            effect("rule_pressure_add", target="node:mira", rule="move", weight=0.5, ttl=3, source="test"),
            effect("thought_bubble_add", target="node:mira", text="先观察", source="test"),
            effect("action_bullet_add", target="node:mira", text="记录动作", source="test"),
            effect("key_character_state", target="node:mira", value={"goal": "学习"}),
            effect("world_state", field="weather", value="clear"),
            effect("unknown_effect", target="node:mira"),
        ],
        apply_mode=APPLY_AUTHORITATIVE,
    )

    result = FeedbackIngestor().ingest(world, feedback)

    assert world.node("mira").attributes["mood"] == "focused"
    assert world.node("mira").position.to_dict() == {"x": 1.0, "y": 1.0}
    assert world.node("mira").memories[0]["text"] == "记住一次测试"
    assert world.node("mira").rule_pressures[0]["rule"] == "movement"
    assert [event["payload"]["text"] for event in world.presentation.recent()] == ["先观察", "记录动作"]
    assert "thought_bubbles" not in world.snapshot()["nodes"][0]
    assert world.node("mira").key_character["goal"] == "学习"
    assert world.attributes["weather"] == "clear"
    assert next(iter(world.relationships.values())).weight == 0.4
    assert result["applied_effects"] == list(range(9))
    assert result["errors"]
    assert world.events.recent_deltas()[-1]["payload"]["errors"]


def test_structured_pressure_to_effects_and_view_do_not_directly_move_node() -> None:
    world = make_world()
    effects = [
        RulePressure("mira", "move", 0.8, 4, "agent", "靠近组织").to_effect(),
        RelationshipPressure("mira", "atlas", "trust", 0.2, 3, "agent", "建立信任").to_effect(),
        MemoryPressure("mira", "阿特拉斯值得关注", "agent", 0.6).to_effect(),
        KeyCharacterPressure("mira", {"goal": "加入学院"}).to_effect(),
        effect("thought_bubble_add", target="node:mira", text="需要行动", source="agent").to_dict(),
        effect("action_bullet_add", target="node:mira", text="准备出发", source="agent").to_dict(),
    ]

    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="agent",
            actor_type="agent",
            actor_id="mock",
            action="emit_pressure",
            summary="写入结构化压力",
            targets=[target("node", "mira")],
            effects=[effect(item.pop("type"), **item) for item in effects],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )

    node = world.node("mira")
    assert node.position.to_dict() == {"x": 0.0, "y": 0.0}
    assert node.rule_pressures[0]["rule"] == "movement"
    assert node.memories[0]["text"] == "阿特拉斯值得关注"

    view = StructuredPressureView().build(world)
    assert view["totals"]["rule_pressures"] == 1
    assert "thought_bubbles" not in view["totals"]
    assert "action_bullets" not in view["totals"]
    assert view["top_nodes"][0]["id"] == "mira"


class StaticRulePackage:
    name = "static"

    def __init__(self, candidate: RuleCandidate) -> None:
        self.candidate = candidate

    def candidates(self, world: World, node):  # type: ignore[no-untyped-def]
        if node.id != self.candidate.node_id:
            return []
        return [self.candidate]


def test_rule_engine_combines_candidates_obeys_hard_facts_and_emits_feedback() -> None:
    world = make_world()
    world.set_movement_target("mira", (2, 0), 1)
    world.node("mira").rule_pressures.append({"rule": "move", "weight": 2.0, "ttl": 1})
    engine = RuleEngineSet(
        [
            StaticRulePackage(RuleCandidate("mira", "wait", 1.5, "custom", "等待")),
            StaticRulePackage(RuleCandidate("mira", "move", 1.0, "custom", "移动")),
        ]
    )

    decision = engine.decide(world, world.node("mira"))

    assert decision is not None
    assert decision.action == "wait"
    assert world.traces.recent()[-1]["candidates"]

    world.node("mira").attributes["alive"] = False
    assert engine.decide(world, world.node("mira")) is None

    world.node("mira").attributes["alive"] = True
    RuleEngineSet.from_scenario(["movement"]).step(world)
    assert world.node("mira").position.to_dict() == {"x": 1.0, "y": 0.0}
    assert any(event["payload"].get("action") == "move" for event in world.events.recent())


def test_agent_outputs_are_validated_before_becoming_pressure() -> None:
    world = make_world()
    registry = AgentRegistry()
    registry.register_relationship_graph_type("research_org")
    registry.register_rule_name("move")
    registry.register_relationship_type("trust")

    relationship_output = RelationshipAgentOutput(
        graph_type="research_org",
        strategy="加强协作",
        rule_pressures=[RulePressure("mira", "move", 0.3, 2, "agent")],
        relationship_pressures=[RelationshipPressure("mira", "atlas", "trust", 0.1, 2, "agent")],
        memory_pressures=[MemoryPressure("mira", "组织关系增强", "agent")],
    )
    key_output = KeyCharacterAgentOutput(
        node_id="mira",
        self_narrative="我要靠近学院",
        goal="加入学院",
        plan="前往学院",
        grounded_rule="move",
        key_pressure=KeyCharacterPressure("mira", {"goal": "加入学院"}),
        rule_pressures=[RulePressure("mira", "move", 0.2, 2, "agent")],
    )

    registry.validate_relationship_output(world, relationship_output)
    registry.validate_key_character_output(world, key_output)

    with pytest.raises(ValueError):
        registry.validate_relationship_output(
            world,
            RelationshipAgentOutput(
                graph_type="research_org",
                rule_pressures=[RulePressure("mira", "attack", 1.0, 1, "agent")],
            ),
        )
    with pytest.raises(ValueError):
        registry.validate_key_character_output(
            world,
            KeyCharacterAgentOutput(node_id="missing", key_pressure=KeyCharacterPressure("missing", {})),
        )

    FeedbackIngestor().ingest(
        world,
        {
            "source": "agent",
            "actor_type": "agent",
            "actor_id": "mock",
            "action": "agent_pressure",
            "summary": "智能体输出压力",
            "effects": relationship_output.effects() + key_output.effects(),
            "apply_mode": APPLY_AUTHORITATIVE,
        },
    )

    assert world.node("mira").position.to_dict() == {"x": 0.0, "y": 0.0}
    assert len(world.node("mira").rule_pressures) == 2
    assert world.node("mira").key_character["goal"] == "加入学院"


def test_memory_retrieval_is_read_only_and_pressure_action_report_matches_actions() -> None:
    world = make_world()
    ingestor = FeedbackIngestor()
    ingestor.ingest(
        world,
        {
            "source": "agent",
            "actor_type": "agent",
            "actor_id": "mock",
            "action": "pressure",
            "summary": "施加移动压力",
            "targets": [{"type": "node", "id": "mira"}],
            "effects": [
                {
                    "type": "rule_pressure_add",
                    "target": "node:mira",
                    "rule": "move",
                    "weight": 1,
                    "ttl": 4,
                    "source": "agent",
                },
                {"type": "memory_add", "target": "node:mira", "text": "想去学院"},
            ],
            "apply_mode": APPLY_AUTHORITATIVE,
        },
    )
    world.set_movement_target("mira", (1, 0), 1)
    before = world.snapshot()

    result = world.memory.retrieve(world, MemoryQuery("mira")) if hasattr(world, "memory") else None
    assert result is None

    from ai_native_world_engine.core import WorldMemoryRetriever

    retrieved = WorldMemoryRetriever().retrieve(world, MemoryQuery("mira")).to_dict()
    assert retrieved["memories"][0]["text"] == "想去学院"
    assert retrieved["pressures"][0]["rule"] == "movement"
    assert world.snapshot() == before

    world.step()
    report = PressureActionTraceLedger().build_report(world, window=4)
    assert report["totals"]["pressures"] == 1
    assert report["totals"]["matched"] == 1
    assert report["totals"]["unmatched"] == 0
    assert report["recent"][0]["action"]["action"] == "move"
    json.dumps(report, ensure_ascii=False)
