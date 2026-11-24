import json

from ai_native_world_engine.core import (
    DeterministicPressureProvider,
    ProviderContext,
    ProviderOutput,
    RunConfig,
    RunSession,
    World,
    effect,
    run,
)


class UnmatchedProvider:
    name = "unmatched-provider"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        return ProviderOutput(
            source=self.name,
            summary="emit pressure that cannot ground in this scenario",
            effects=[
                effect(
                    "rule_pressure_add",
                    target="node:mira",
                    rule="combat",
                    weight=1.0,
                    ttl=1,
                    source=self.name,
                    reason="no target means no combat candidate",
                    to="node:missing",
                )
            ],
        )


class ProfileAwareProvider:
    name = "profile-aware-provider"

    def __init__(self) -> None:
        self.observed_params: list[dict[str, object]] = []

    def observe(self, context: ProviderContext) -> ProviderOutput:
        self.observed_params.append(context.params)
        return ProviderOutput(
            source=self.name,
            summary="profile governed pressure",
            effects=[
                effect(
                    "rule_pressure_add",
                    target="node:mira",
                    rule="move",
                    weight=0.25,
                    ttl=1,
                    source=self.name,
                    reason="profile allowlist permits movement pressure",
                )
            ],
            metadata={
                "provider_runtime": {
                    "provider": self.name,
                    "attempts": 1,
                    "estimated_cost": 0.01,
                    "cost_unit": "credits",
                    "latency_ms": 1.0,
                }
            },
        )


class OverBudgetProvider:
    name = "over-budget-provider"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        return ProviderOutput(
            source=self.name,
            summary="runtime exceeds the configured budget",
            metadata={
                "provider_runtime": {
                    "provider": self.name,
                    "attempts": 2,
                    "estimated_cost": 0.5,
                    "cost_unit": "credits",
                    "latency_ms": 10.0,
                }
            },
        )


class ThoughtOnlyProvider:
    name = "thought-only-provider"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        return ProviderOutput(
            source=self.name,
            summary="thinking without proposing a grounded pressure",
            effects=[
                effect(
                    "thought_bubble_add",
                    target="node:scout-nara",
                    text="I am still considering the situation.",
                    source=self.name,
                )
            ],
        )


def test_deterministic_provider_output_is_stable_and_read_only() -> None:
    world = World.scenario("seed", seed=11)
    before = world.snapshot()
    provider = DeterministicPressureProvider()
    context = ProviderContext(world, world.tick, world.snapshot())

    first = provider.observe(context)
    second = provider.observe(context)

    assert first.to_dict() == second.to_dict()
    assert world.snapshot() == before
    assert any(item.type == "rule_pressure_add" for item in first.effects)
    assert any(item.type == "thought_bubble_add" for item in first.effects)
    json.dumps(first.to_dict(), ensure_ascii=False)


def test_run_harness_is_reproducible_and_json_serializable() -> None:
    config = RunConfig(scenario="seed", seed=17, ticks=3)

    first = run(config).to_dict()
    second = run(config).to_dict()

    assert first == second
    assert first["config"]["provider"] == "deterministic-pressure"
    assert first["snapshot"]["tick"] == 3
    assert first["events"]
    assert first["traces"]
    assert first["scorecard"]["score"] == 100.0
    assert first["pressure_view"]["totals"]["rule_pressures"] >= 1
    json.dumps(first, ensure_ascii=False)


def test_run_session_steps_match_one_shot_run() -> None:
    config = RunConfig(scenario="seed", seed=17, ticks=3, capture_timeline=True)
    session = RunSession(config)

    assert session.step() is True
    partial = session.result().to_dict()
    assert partial["snapshot"]["tick"] == 1
    assert len(partial["timeline"]) == 1
    assert partial["scorecard"]["metrics"]["ticks"] == 1

    session.run_to_end()
    assert session.completed is True
    assert session.step() is False
    assert session.result().to_dict() == run(config).to_dict()


def test_run_session_checkpoint_restores_and_continues() -> None:
    config = RunConfig(scenario="seed", seed=17, ticks=3, capture_timeline=True)
    session = RunSession(config)
    session.step()
    checkpoint = session.checkpoint()
    restored = RunSession.from_checkpoint(checkpoint)

    assert checkpoint["world_snapshot"]["tick"] == 1
    assert checkpoint["timeline"][0]["tick"] == 1
    assert checkpoint["timeline_event_count"] == len(checkpoint["world_snapshot"]["events"])
    assert checkpoint["timeline_trace_count"] == len(checkpoint["world_snapshot"]["traces"])
    assert checkpoint["timeline_sequence"] == 1
    assert restored.result().to_dict() == session.result().to_dict()

    restored.run_to_end()
    assert restored.result().to_dict() == run(config).to_dict()


def test_cognition_ready_uses_first_provider_thought_without_changing_rule_path() -> None:
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            provider=DeterministicPressureProvider(
                rule="move", weight=1.0, emit_thoughts=True
            ),
            runtime_provider={"mode": "deterministic"},
            require_cognition_ready=True,
            capture_timeline=True,
        )
    )

    assert session.world.tick == 0
    assert session.step() is True
    assert session.bootstrap_state["phase"] == "ready"
    assert session.world.tick == 1
    assert session.bootstrap_state["accepted_thought_sequences"]
    ready_projection = session.timeline[-1]["projection"]
    assert ready_projection["grounded_actions"]


def test_thought_only_provider_opens_cover_without_synthesizing_action() -> None:
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            provider=ThoughtOnlyProvider(),
            runtime_provider={"mode": "live"},
            require_cognition_ready=True,
        )
    )

    seeded_presentation = session.world.presentation.recent()
    assert seeded_presentation
    assert session.step() is True

    assert session.world.tick == 1
    assert session.phase == "running"
    assert session.bootstrap_state["phase"] == "ready"
    assert session.bootstrap_state["accepted_thought_sequences"]
    assert session.bootstrap_state["committed_pressure_ids"] == []
    assert session.bootstrap_state["grounded_action_sequences"] == []
    assert session.world.presentation.recent()[: len(seeded_presentation)] == seeded_presentation


def test_pressure_without_provider_thought_never_opens_loading_cover() -> None:
    session = RunSession(
        RunConfig(
            scenario="seed",
            ticks=3,
            rules=["movement", "combat"],
            provider=UnmatchedProvider(),
            runtime_provider={"mode": "live"},
            require_cognition_ready=True,
        )
    )

    while session.phase == "running" and session.bootstrap_state["phase"] != "failed":
        assert session.step() is True
    assert session.world.tick == 3
    assert session.phase == "stopped"
    assert session.bootstrap_state["phase"] == "failed"
    assert session.bootstrap_state["error_code"] == "initial_provider_no_visible_thought"
    assert session.bootstrap_state["accepted_thought_sequences"] == []
    assert session.bootstrap_state["grounded_action_sequences"] == []


def test_ready_checkpoint_restores_without_reapplying_first_thought() -> None:
    config = RunConfig(
        scenario="tribe_survival",
        ticks=3,
        provider=DeterministicPressureProvider(
            rule="move", weight=1.0, emit_thoughts=True
        ),
        runtime_provider={"mode": "deterministic"},
        require_cognition_ready=True,
    )
    session = RunSession(config)
    session.step()
    thought_sequences = list(session.bootstrap_state["accepted_thought_sequences"])
    checkpoint = session.checkpoint()

    restored = RunSession.from_checkpoint(checkpoint)

    assert restored.bootstrap_state == session.bootstrap_state
    assert restored.world.tick == 1
    assert restored.step() is True
    assert restored.world.tick == 2
    assert restored.bootstrap_state["accepted_thought_sequences"] == thought_sequences

    compact_restored = RunSession.from_compact_checkpoint(session.compact_checkpoint())
    assert compact_restored.bootstrap_state == session.bootstrap_state
    assert compact_restored.world.tick == 1
    assert compact_restored.step() is True
    assert compact_restored.world.tick == 2
    assert compact_restored.bootstrap_state["accepted_thought_sequences"] == thought_sequences


def test_bootstrap_checkpoint_recovers_first_thought_evidence_once() -> None:
    dispatching = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            runtime_provider={"mode": "deterministic"},
            require_cognition_ready=True,
        )
    )
    dispatching_restored = RunSession.from_checkpoint(dispatching.checkpoint())
    dispatching_restored.step()
    assert dispatching_restored.bootstrap_state["phase"] == "ready"
    restored = RunSession.from_checkpoint(dispatching_restored.checkpoint())
    accepted_before = int(restored.bootstrap_state["accepted_provider_output_count"])
    thought_sequences = list(restored.bootstrap_state["accepted_thought_sequences"])

    restored.step()

    assert restored.bootstrap_state["phase"] == "ready"
    assert restored.bootstrap_state["accepted_provider_output_count"] == accepted_before
    assert restored.bootstrap_state["accepted_thought_sequences"] == thought_sequences


def test_cancel_before_ready_closes_bootstrap_without_entering_world() -> None:
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            provider=ThoughtOnlyProvider(),
            require_cognition_ready=True,
        )
    )

    session.request_cancel("user left during cognition")

    assert session.world.tick == 0
    assert session.bootstrap_state["phase"] == "canceled"
    assert session.bootstrap_state["ready"] is False
    assert session.bootstrap_state["error_code"] == "initial_cognition_canceled"


def test_run_session_bounds_incremental_timeline_retention() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=17,
            ticks=5,
            capture_timeline=True,
            timeline_retention=2,
        )
    ).to_dict()

    assert result["config"]["timeline_retention"] == 2
    assert [frame["sequence"] for frame in result["timeline"]] == [4, 5]
    assert [frame["tick"] for frame in result["timeline"]] == [4, 5]
    assert all("snapshot" not in frame for frame in result["timeline"])
    earlier_events = {event["sequence"] for event in result["timeline"][0]["events"]}
    later_events = {event["sequence"] for event in result["timeline"][1]["events"]}
    assert earlier_events.isdisjoint(later_events)


def test_provider_pressure_is_matched_to_rule_action() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=1)).to_dict()

    report = result["pressure_action_report"]
    assert report["totals"]["pressures"] == 1
    assert report["totals"]["matched"] == 1
    assert report["recent"][0]["action"]["action"] == "move"
    outcome = result["provider_outcome_report"]
    assert outcome["totals"]["matched_pressures"] == 1
    assert outcome["providers"][0]["provider"] == "deterministic-pressure"
    assert outcome["providers"][0]["alignment_rate"] == 1.0
    profile = result["provider_execution_report"]
    assert profile["totals"]["providers"] == 1
    assert profile["totals"]["outputs"] == 1
    assert profile["totals"]["attempts"] == 1
    assert profile["totals"]["effect_count"] == 2
    assert profile["totals"]["outcome_alignment_rate"] == 1.0
    assert profile["providers"][0]["provider"] == "deterministic-pressure"
    assert profile["providers"][0]["outcome_matched_pressures"] == 1
    assert result["scorecard"]["metrics"]["provider_outcome_alignment_rate"] == 1.0
    assert result["scorecard"]["metrics"]["provider_profile_attempts"] == 1
    assert result["scorecard"]["metrics"]["provider_profile_effect_count"] == 2
    assert result["scorecard"]["metrics"]["provider_profile_alignment_rate"] == 1.0


def test_provider_execution_report_records_governance_rejection() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            provider=DeterministicPressureProvider(rule="attack"),
            govern_provider_output=True,
            provider_id="restricted",
            allowed_rule_names=["move"],
        )
    ).to_dict()

    profile = result["provider_execution_report"]

    assert result["provider_outputs"] == []
    assert result["provider_audits"][0]["accepted"] is False
    assert profile["totals"]["providers"] == 1
    assert profile["totals"]["outputs"] == 0
    assert profile["totals"]["rejected_audits"] == 1
    assert profile["totals"]["failures"] == 1
    assert profile["providers"][0]["provider"] == "deterministic-pressure"
    assert profile["providers"][0]["provider_ids"] == ["restricted"]
    assert result["scorecard"]["metrics"]["provider_profile_rejected_audits"] == 1
    assert result["scorecard"]["metrics"]["provider_profile_failures"] == 1


def test_provider_policy_profile_applies_allowlist_and_context_strategy() -> None:
    provider = ProfileAwareProvider()

    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            provider=provider,
            provider_profile={
                "id": "movement-profile",
                "label": "Movement Profile",
                "allowed_rule_names": ["move"],
                "context_strategy": {"mode": "focused", "memory_limit": 4},
                "tags": ["test", "governed"],
                "metadata": {"tier": "gold"},
            },
        )
    ).to_dict()

    audit = result["provider_audits"][0]

    assert result["provider_outputs"]
    assert audit["accepted"] is True
    assert audit["provider_id"] == "movement-profile"
    assert audit["metadata"]["policy_profile"]["id"] == "movement-profile"
    assert audit["metadata"]["policy_profile"]["metadata"] == {"tier": "gold"}
    assert provider.observed_params[0]["context_strategy"] == {"mode": "focused", "memory_limit": 4}
    assert provider.observed_params[0]["provider_profile"]["tags"] == ["test", "governed"]
    assert result["config"]["provider_profile"]["id"] == "movement-profile"
    assert result["provider_execution_report"]["providers"][0]["provider_ids"] == ["movement-profile"]


def test_provider_policy_profile_budget_rejects_excessive_runtime() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            provider=OverBudgetProvider(),
            provider_profile={
                "id": "cheap-profile",
                "allowed_rule_names": ["move"],
                "budget": {"max_attempts": 1, "max_estimated_cost": 0.1},
                "metadata": {"owner": "runtime-governance"},
            },
        )
    ).to_dict()

    audit = result["provider_audits"][0]

    assert result["provider_outputs"] == []
    assert audit["accepted"] is False
    assert audit["provider_id"] == "cheap-profile"
    assert "provider budget exceeded: attempts 2 > 1" in audit["error"]
    assert audit["metadata"]["policy_profile"]["id"] == "cheap-profile"
    assert audit["metadata"]["policy_profile"]["budget"]["max_attempts"] == 1
    assert result["provider_execution_report"]["totals"]["rejected_audits"] == 1
    assert result["scorecard"]["metrics"]["provider_profile_failures"] == 1


def test_provider_outcome_report_exposes_unmatched_provider_pressure() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            rules=["movement", "combat"],
            provider=UnmatchedProvider(),
        )
    ).to_dict()

    outcome = result["provider_outcome_report"]

    assert outcome["totals"]["pressures"] == 1
    assert outcome["totals"]["unmatched_pressures"] == 1
    assert outcome["providers"][0]["provider"] == "unmatched-provider"
    assert outcome["providers"][0]["alignment_rate"] == 0.0
    assert result["scorecard"]["metrics"]["provider_unmatched_pressures"] == 1


def test_zero_tick_run_does_not_invoke_provider_or_move_world() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=0)).to_dict()

    assert result["snapshot"]["tick"] == 0
    assert result["provider_outputs"] == []
    assert result["pressure_action_report"]["totals"]["pressures"] == 0
    mira = next(node for node in result["snapshot"]["nodes"] if node["id"] == "mira")
    assert mira["position"] == {"x": 0.0, "y": 0.0}


def test_runtime_intervention_applies_before_provider_and_rule_tick() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            capture_timeline=True,
            interventions=[
                {
                    "id": "operator-reposition",
                    "tick": 0,
                    "actor_id": "operator",
                    "summary": "move Mira near the destination before the tick",
                    "effects": [
                        {
                            "type": "node_position",
                            "target": "node:mira",
                            "position": {"x": 2.0, "y": 0.0},
                        }
                    ],
                }
            ],
        )
    ).to_dict()

    mira = next(node for node in result["snapshot"]["nodes"] if node["id"] == "mira")

    assert mira["position"] == {"x": 3.0, "y": 0.0}
    assert result["intervention_audits"][0]["accepted"] is True
    assert result["intervention_audits"][0]["applied_effect_count"] == 1
    assert result["scorecard"]["metrics"]["interventions"] == 1
    assert any(trace["kind"] == "runtime_intervention" for trace in result["traces"])
    assert "snapshot" not in result["timeline"][0]
    assert any(trace["kind"] == "runtime_intervention" for trace in result["timeline"][0]["traces"])


def test_invalid_runtime_intervention_is_audited_as_world_error() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            interventions=[
                {
                    "id": "bad-target",
                    "tick": 0,
                    "effects": [
                        {
                            "type": "health_delta",
                            "target": "node:missing",
                            "delta": -1,
                        }
                    ],
                }
            ],
        )
    ).to_dict()

    audit = result["intervention_audits"][0]

    assert audit["accepted"] is False
    assert audit["error_count"] == 1
    assert result["snapshot"]["errors"]
    assert result["scorecard"]["metrics"]["intervention_errors"] == 1
    assert result["scorecard"]["metrics"]["world_errors"] == 1
