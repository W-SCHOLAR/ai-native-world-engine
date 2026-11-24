from __future__ import annotations

from dataclasses import dataclass

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    ActionInstance,
    ActionRuntime,
    ActionTransition,
    MovementRulePackage,
    RuleCandidate,
    RuleEngineSet,
    World,
    apply_world_state_delta,
    compact_world_snapshot,
    project_run_for_viewer,
    world_state_delta,
)


def _projection(world: World) -> dict[str, object]:
    return project_run_for_viewer(
        {
            "snapshot": world.snapshot(),
            "events": world.events.recent(),
            "traces": world.traces.recent(),
            "scorecard": {},
        }
    ).to_dict()


def test_movement_is_authoritative_until_arrival_and_survives_restore() -> None:
    world = World("movement-v2")
    world.add_node("walker", "person", "行者", (0, 0))
    world.set_movement_target("walker", (3, 0), 1)
    engine = RuleEngineSet([MovementRulePackage()])

    world.step(engine)

    action = next(iter(world.active_actions.values()))
    assert action.definition_id == "move"
    assert action.status == "running"
    assert action.channel == "physical"
    assert action.locks == ["locomotion"]
    assert world.node("walker").position.x == 1
    assert _projection(world)["current_actions"][0]["label"] == "移动"  # type: ignore[index]

    restored = World.from_snapshot(world.snapshot())
    restored.step(engine)
    assert next(iter(restored.active_actions)) == action.id
    assert restored.node("walker").position.x == 2

    restored.step(engine)
    assert restored.node("walker").position.x == 3
    assert restored.active_actions == {}
    assert restored.action_history[-1].status == "succeeded"
    assert restored.action_history[-1].status_reason == "arrived"
    assert _projection(restored)["current_actions"] == []


def test_active_action_state_round_trips_through_compact_delta() -> None:
    world = World("movement-delta")
    world.add_node("walker", "person", "行者", (0, 0))
    world.set_movement_target("walker", (4, 0), 1)
    before = compact_world_snapshot(world)

    world.step(RuleEngineSet([MovementRulePackage()]))
    after = compact_world_snapshot(world)
    replayed = apply_world_state_delta(before, world_state_delta(before, after))

    assert replayed == after
    restored = World.from_snapshot(replayed)
    assert compact_world_snapshot(restored) == after
    assert next(iter(restored.active_actions.values())).progress == 0.25


def test_social_action_temporarily_overrides_running_physical_caption() -> None:
    world = World("parallel-actions")
    speaker = world.add_node("speaker", "person", "托尔", (0, 0))
    world.add_node("listener", "person", "娜拉", (1, 0))
    world.set_movement_target("speaker", (5, 0), 1)
    movement_only = RuleEngineSet.from_scenario(["movement"])
    movement_and_speech = RuleEngineSet.from_scenario(["movement", "speak"])

    world.step(movement_only)
    speaker.rule_pressures.append(
        {
            "rule": "speak",
            "pressure_id": "warn-1",
            "intent": "warn",
            "target": "listener",
            "facts": ["north_gate_enemy_trace"],
            "ttl": 5,
        }
    )
    world.step(movement_and_speech)

    assert {item.channel for item in world.active_actions.values()} == {
        "physical",
        "social",
    }
    assert _projection(world)["current_actions"][0]["channel"] == "social"  # type: ignore[index]

    world.step(movement_and_speech)

    assert [item.channel for item in world.active_actions.values()] == ["physical"]
    assert _projection(world)["current_actions"][0]["channel"] == "physical"  # type: ignore[index]


@dataclass
class _PriorityPackage:
    name: str
    priority: float
    action_runtime_version: int = 2
    version: str = "2"

    def candidates(self, world: World, node: object) -> list[RuleCandidate]:
        node_id = str(getattr(node, "id"))
        pressures = getattr(node, "rule_pressures")
        if not any(item.get("rule") == self.name for item in pressures):
            return []
        return [
            RuleCandidate(
                node_id=node_id,
                action=self.name,
                score=self.priority,
                rule=self.name,
                metadata={
                    "channel": "physical",
                    "locks": ["hands"],
                    "interrupt_priority": self.priority,
                },
            )
        ]

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        return ActionTransition(
            status="running",
            summary=f"start {self.name}",
            channel="physical",
            locks=["hands"],
            interrupt_priority=self.priority,
            behavior_label=self.name,
        )

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        return ActionTransition(
            status="running",
            summary=f"continue {self.name}",
            channel="physical",
            progress=action.progress,
            locks=["hands"],
            interrupt_priority=self.priority,
            behavior_label=self.name,
        )

    def interrupt(
        self, world: World, action: ActionInstance, reason: str
    ) -> ActionTransition:
        return ActionTransition(
            status="interrupted",
            summary=f"interrupt {self.name}",
            channel="physical",
            progress=action.progress,
            locks=["hands"],
            interrupt_priority=self.priority,
            behavior_label=self.name,
            status_reason=reason,
        )


def test_higher_priority_action_interrupts_channel_and_lock_holder() -> None:
    low = _PriorityPackage("low_work", 1)
    high = _PriorityPackage("urgent_rescue", 2)
    world = World("preemption")
    actor = world.add_node("actor", "person", "Actor", (0, 0))
    actor.rule_pressures.append({"rule": "low_work", "ttl": 5})
    engine = RuleEngineSet([low, high])  # type: ignore[list-item]

    world.step(engine)
    low_id = next(iter(world.active_actions))
    actor.rule_pressures.append({"rule": "urgent_rescue", "ttl": 5})
    world.step(engine)

    assert world.action_history[-1].id == low_id
    assert world.action_history[-1].status == "interrupted"
    assert world.action_history[-1].status_reason.startswith("preempted_by")
    assert next(iter(world.active_actions.values())).definition_id == "urgent_rescue"


class _InstantV2Package:
    name = "instant_v2"
    version = "2"
    action_runtime_version = 2

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        return ActionTransition(status="succeeded", summary="done")


def test_terminal_history_is_bounded_and_terminal_transition_is_idempotent() -> None:
    world = World("bounded-history")
    world.add_node("actor", "person", "Actor", (0, 0))
    runtime = ActionRuntime()
    package = _InstantV2Package()
    for index in range(260):
        recorded = runtime.start(
            world,
            package,  # type: ignore[arg-type]
            RuleCandidate("actor", f"instant-{index}", 1, package.name),
        )
        assert recorded is not None and recorded["errors"] == []

    assert len(world.action_history) == 256
    assert world.action_history[0].definition_id == "instant-4"
    assert world.action_history[-1].definition_id == "instant-259"


class _LegacyPackage:
    name = "legacy"

    def candidates(self, world: World, node: object) -> list[RuleCandidate]:
        if world.tick != 1:
            return []
        node_id = str(getattr(node, "id"))
        return [
            RuleCandidate(
                node_id,
                "legacy_action",
                1,
                self.name,
                feedback=ActionFeedback(
                    source="legacy",
                    actor_type="node",
                    actor_id=node_id,
                    action="legacy_action",
                    summary="legacy action",
                    apply_mode=APPLY_AUTHORITATIVE,
                ),
            )
        ]


def test_v1_adapter_remains_instantaneous_and_never_becomes_active() -> None:
    world = World("legacy-adapter")
    world.add_node("actor", "person", "Actor", (0, 0))

    world.step(RuleEngineSet([_LegacyPackage()]))  # type: ignore[list-item]

    assert world.active_actions == {}
    assert world.action_history == []
    feedback = next(
        item["payload"]
        for item in world.events.recent()
        if item["kind"] == "action_feedback"
    )
    assert feedback["action_lifecycle"]["runtime"] == "v1-adapter"
    assert feedback["action_lifecycle"]["instantaneous"] is True
