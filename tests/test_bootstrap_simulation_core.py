import json

import pytest

from ai_native_world_engine.core import (
    ActionBullet,
    MovementRulePackage,
    Position,
    RuleEngineSet,
    ThoughtBubble,
    TraceRecord,
    World,
)
from ai_native_world_engine.scenarios import create_seed_world


def test_world_nodes_ticks_and_snapshot_are_json_compatible() -> None:
    world = World("test-world", {"mode": "unit"})

    node = world.add_node("node-1", "person", "节点一", (1, 2), {"hp": 10})

    assert world.snapshot()["id"] == "test-world"
    assert world.snapshot()["tick"] == 0
    assert node.position.to_dict() == {"x": 1.0, "y": 2.0}
    with pytest.raises(ValueError):
        world.add_node("node-1", "person", "重复节点", (0, 0))

    world.step(RuleEngineSet([]))

    snapshot = world.snapshot()
    assert snapshot["tick"] == 1
    assert snapshot["nodes"][0]["id"] == "node-1"
    json.dumps(snapshot, ensure_ascii=False)


def test_world_snapshot_can_be_restored_with_ledgers_and_continue_sequences() -> None:
    world = World("restore-world", {"mode": "restore"})
    world.add_node("node-1", "person", "Node", (1, 2), {"health": 5})
    world.events.record(0, "custom", "test", {"value": 1})
    world.events.record_delta(0, "test", {"kind": "custom_delta"})
    world.traces.record(TraceRecord(0, "custom_trace", "test", observed={"node_id": "node-1"}))
    world.errors.append({"message": "demo"})

    restored = World.from_snapshot(world.snapshot())
    restored.events.record(1, "after_restore", "test", {})
    restored.traces.record(TraceRecord(1, "after_restore", "test"))

    snapshot = restored.snapshot()
    assert snapshot["id"] == "restore-world"
    assert snapshot["nodes"][0]["attributes"] == {"health": 5}
    assert snapshot["events"][0]["sequence"] == 1
    assert snapshot["events"][1]["sequence"] == 2
    assert snapshot["events"][-1]["sequence"] == 3
    assert snapshot["deltas"][0]["payload"]["kind"] == "custom_delta"
    assert snapshot["traces"][0]["kind"] == "custom_trace"
    assert snapshot["traces"][-1]["kind"] == "after_restore"
    assert snapshot["errors"] == [{"message": "demo"}]


def test_relationship_graph_validates_nodes_and_updates_weight() -> None:
    world = World("relationships")
    world.add_node("a", "person", "A", (0, 0))
    world.add_node("b", "person", "B", (1, 0))

    edge = world.add_relationship("a", "b", "trust", 0.25, {"source": "test"})
    assert edge.source == "a"
    assert edge.target == "b"
    assert edge.type == "trust"
    assert edge.weight == 0.25

    with pytest.raises(KeyError):
        world.add_relationship("a", "missing", "trust")

    world.update_relationship_weight("a", "b", "trust", 0.75)
    world.adjust_relationship_weight("a", "b", "trust", -0.25)

    snapshot = world.snapshot()
    assert snapshot["relationships"][0]["weight"] == 0.5
    json.dumps(snapshot["relationships"], ensure_ascii=False)


def test_movement_rule_moves_without_overshoot_and_clears_arrival_target() -> None:
    world = World("movement")
    world.add_node("runner", "person", "行者", (0, 0))
    world.set_movement_target("runner", (3, 0), 1.0)

    world.step()

    runner = world.node("runner")
    assert runner.position.to_dict() == {"x": 1.0, "y": 0.0}
    assert runner.movement_target == Position(3.0, 0.0)
    assert any(event["payload"].get("action") == "move" for event in world.events.recent())
    assert any(trace["kind"] == "movement" for trace in world.traces.recent())

    world.step()
    world.step()

    assert runner.position.to_dict() == {"x": 3.0, "y": 0.0}
    assert runner.movement_target is None
    assert runner.movement_speed == 0.0
    assert runner.attributes["movement_arrived"] is True


def test_event_stream_display_payloads_and_trace_serialization() -> None:
    world = World("events")
    world.add_node("speaker", "person", "说话者", (0, 0))

    before = world.snapshot()
    world.emit_thought_bubble(ThoughtBubble("speaker", "正在思考", "test"))
    world.emit_action_bullet(ActionBullet("speaker", "开始行动", "test"))
    after = world.snapshot()

    assert after["nodes"][0]["position"] == before["nodes"][0]["position"]
    assert world.events.recent() == []
    assert [event["sequence"] for event in world.presentation.recent()] == [1, 2]
    assert "thought_bubbles" not in after["nodes"][0]
    assert "action_bullets" not in after["nodes"][0]
    json.dumps(world.traces.recent(), ensure_ascii=False)


def test_seed_scenario_is_reproducible_and_runs_locally() -> None:
    first = create_seed_world(seed=42)
    second = create_seed_world(seed=42)

    assert first.snapshot() == second.snapshot()
    assert len(first.nodes) >= 2
    assert first.relationships
    assert any(
        event["payload"].get("type") == "thought_bubble"
        for event in first.presentation.recent()
    )
    assert any(
        event["payload"].get("type") == "action_bullet"
        for event in first.presentation.recent()
    )

    first.step()
    snapshot = first.snapshot()
    assert snapshot["tick"] == 1
    assert snapshot["events"]
    assert snapshot["traces"]
    json.dumps(snapshot, ensure_ascii=False)


def test_scenario_rule_engine_loader_selects_movement_package() -> None:
    engine = RuleEngineSet.from_scenario(["movement"])

    assert isinstance(engine.packages[0], MovementRulePackage)
    with pytest.raises(ValueError):
        RuleEngineSet.from_scenario(["unknown"])
