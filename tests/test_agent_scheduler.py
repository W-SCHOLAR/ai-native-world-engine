import json
from threading import Event, Lock
from time import perf_counter, sleep

from ai_native_world_engine.core import (
    ACTIVE_NODE_LIMIT,
    AI_ISEKAI_DISPATCH_SLOTS,
    AgentJob,
    AgentScheduler,
    AgentSchedulerConfig,
    DeterministicEnterpriseAgentProvider,
    DeterministicHighPressureResponseProvider,
    DeterministicKeyCharacterContinuityProvider,
    DeterministicPressureProvider,
    DeterministicRelationshipRoundProvider,
    ProviderContext,
    ProviderOutput,
    RunConfig,
    RunSession,
    World,
    enterprise_event_triggered_lens_jobs,
    enterprise_pressure_triggered_jobs,
    enterprise_agent_jobs,
    default_agent_scheduler_config,
    default_enterprise_scheduler_config,
    effect,
    run,
)


class BlockingBootstrapProvider:
    name = "blocking-bootstrap-provider"
    network_backed = True

    def __init__(self) -> None:
        self.release = Event()

    def observe(self, context: ProviderContext) -> ProviderOutput:
        self.release.wait(timeout=1.0)
        return ProviderOutput(
            source=self.name,
            summary="ground scout movement after release",
            effects=[
                effect(
                    "thought_bubble_add",
                    target="node:scout-nara",
                    text="I should move after reading the valley.",
                    source=self.name,
                ),
                effect(
                    "rule_pressure_add",
                    target="node:scout-nara",
                    rule="move",
                    weight=1.0,
                    ttl=3,
                    source=self.name,
                    reason="respond to the initial world snapshot",
                )
            ],
        )


class PartialBootstrapProvider:
    name = "partial-bootstrap-provider"
    network_backed = True

    def __init__(self) -> None:
        self.release_remaining = Event()
        self.lock = Lock()
        self.call_count = 0

    def observe(self, context: ProviderContext) -> ProviderOutput:
        with self.lock:
            self.call_count += 1
            call_number = self.call_count
        if call_number > 1:
            self.release_remaining.wait(timeout=2.0)
            return ProviderOutput(
                source=self.name,
                summary="later cognition remains asynchronous",
            )
        return ProviderOutput(
            source=self.name,
            summary="first causal pressure closes the entry gate",
            effects=[
                effect(
                    "thought_bubble_add",
                    target="node:scout-nara",
                    text="The first world response is now visible.",
                    source=self.name,
                ),
                effect(
                    "rule_pressure_add",
                    target="node:scout-nara",
                    rule="move",
                    weight=1.0,
                    ttl=3,
                    source=self.name,
                    reason="first valid causal closure",
                )
            ],
        )


def test_scheduler_dedupes_jobs_and_respects_dispatch_slot() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            max_concurrent=2,
            dispatch_slots=["relationship", "key_character"],
        )
    )
    job = AgentJob(
        id="relationship",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )

    assert scheduler.enqueue(job) is True
    assert scheduler.enqueue(job) is False
    assert scheduler.dispatch_tick(world, tick=1) == []
    assert scheduler.status_snapshot()["queue_length"] == 1

    outputs = scheduler.dispatch_tick(world, tick=0)

    assert len(outputs) == 1
    assert outputs[0].metadata["scheduler"]["job_id"] == "relationship"
    assert outputs[0].metadata["scheduler"]["slot"] == "relationship"
    assert scheduler.status_snapshot()["queue_length"] == 0
    assert scheduler.enqueue(job) is False
    json.dumps(outputs[0].to_dict(), ensure_ascii=False)


def test_scheduler_preserves_provider_boundary_repair_audit() -> None:
    class AuditedProvider:
        name = "audited-provider"

        def observe(self, context: ProviderContext) -> ProviderOutput:
            return ProviderOutput(
                source=self.name,
                summary=f"audited at {context.tick}",
                metadata={
                    "provider_output_boundary": {
                        "schema": "test-boundary-v1",
                        "action_option_repair_count": 1,
                        "action_option_repairs": [
                            {
                                "node_id": "node-a",
                                "original_option_id": "invented",
                                "repaired_option_id": "grounded",
                            }
                        ],
                    }
                },
            )

    world = World("scheduler-boundary-audit")
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True, max_concurrent=1, dispatch_slots=["relationship"]
        )
    )
    scheduler.enqueue(
        AgentJob(
            "audited", "relationship_round", AuditedProvider(), slot="relationship"
        )
    )

    output = scheduler.dispatch_tick(world, tick=0)[0]

    assert output.metadata["provider_boundary"]["schema"] == "test-boundary-v1"
    assert output.metadata["provider_boundary"]["action_option_repair_count"] == 1
    assert (
        output.metadata["provider_boundary"]["action_option_repairs"][0][
            "repaired_option_id"
        ]
        == "grounded"
    )
    assert output.metadata["provider_boundary"]["replaceable_provider"] is True


def test_scheduler_respects_max_concurrent_and_budget() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            max_concurrent=1,
            daily_budget=1,
            dispatch_slots=["relationship"],
        )
    )
    scheduler.enqueue(
        AgentJob(
            "relationship-a",
            "relationship_round",
            DeterministicRelationshipRoundProvider(),
            slot="relationship",
            priority=2,
        )
    )
    scheduler.enqueue(
        AgentJob(
            "relationship-b",
            "relationship_round",
            DeterministicRelationshipRoundProvider(),
            slot="relationship",
            priority=1,
        )
    )

    first = scheduler.dispatch_tick(world, tick=0)
    second = scheduler.dispatch_tick(world, tick=2)
    status = scheduler.status_snapshot()

    assert len(first) == 1
    assert second == []
    assert status["started_count"] == 1
    assert status["remaining_budget"] == 0
    assert status["queue_length"] == 1
    assert status["dispatched_job_ids"] == ["relationship-a"]


def test_network_backed_scheduler_job_is_pending_without_blocking_tick() -> None:
    class NetworkProvider:
        name = "network-provider"
        network_backed = True

        def __init__(self) -> None:
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.release.wait(timeout=1.0)
            return ProviderOutput(
                source=self.name, summary=f"completed from tick {context.tick}"
            )

    world = World.scenario("enterprise_earth", seed=7)
    provider = NetworkProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True, max_concurrent=1, dispatch_slots=["relationship"]
        )
    )
    scheduler.enqueue(
        AgentJob(
            "async-relationship", "relationship_round", provider, slot="relationship"
        )
    )
    started = perf_counter()

    first = scheduler.dispatch_tick(world, tick=0)

    assert perf_counter() - started < 0.2
    assert first == []
    assert scheduler.status_snapshot()["provider_pending_count"] == 1
    assert (
        scheduler.status_snapshot()["provider_pending"][0]["status"]
        == "provider_pending"
    )

    provider.release.set()
    deadline = perf_counter() + 1.0
    outputs = []
    while not outputs and perf_counter() < deadline:
        sleep(0.005)
        outputs = scheduler.collect_pending(world)

    assert len(outputs) == 1
    assert outputs[0].metadata["provider_pending"]["status"] == "completed"
    assert outputs[0].metadata["provider_pending"]["source_tick"] == 0
    assert scheduler.status_snapshot()["provider_pending_count"] == 0


def test_cognition_loading_cover_does_not_hold_world_ticks() -> None:
    provider = BlockingBootstrapProvider()
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            scheduler_provider=provider,
            runtime_provider={"mode": "live"},
            require_cognition_ready=True,
        )
    )
    seeded_actions = session.world.presentation.recent()

    assert session.step() is True
    assert session.world.tick == 1
    assert session.bootstrap_state["phase"] == "waiting_provider"
    assert session.bootstrap_state["ready"] is False
    assert session.world.presentation.recent()[: len(seeded_actions)] == seeded_actions
    assert len(session.world.presentation.recent()) > len(seeded_actions)

    provider.release.set()
    deadline = perf_counter() + 2.0
    while session.bootstrap_state["phase"] != "ready" and perf_counter() < deadline:
        sleep(0.005)
        session.step()

    assert session.bootstrap_state["phase"] == "ready"
    assert session.world.tick >= 2
    assert session.bootstrap_state["accepted_thought_sequences"]


def test_cognition_bootstrap_times_out_at_tick_zero_before_viewer_ready() -> None:
    provider = BlockingBootstrapProvider()
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            scheduler_provider=provider,
            runtime_provider={"mode": "live"},
            require_cognition_ready=True,
        )
    )
    session.bootstrap_state["deadline_at"] = "2000-01-01T00:00:00+00:00"

    assert session.step() is True
    assert session.world.tick == 0
    assert session.phase == "stopped"
    assert session.bootstrap_state["phase"] == "timed_out"
    assert session.bootstrap_state["ready"] is False
    assert session.bootstrap_state["error_code"] == "initial_provider_timeout"


def test_waiting_provider_checkpoint_recovers_while_world_keeps_ticking() -> None:
    provider = BlockingBootstrapProvider()
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=3,
            scheduler_provider=provider,
            runtime_provider={"mode": "live"},
            require_cognition_ready=True,
        )
    )
    assert session.step() is True
    assert session.bootstrap_state["phase"] == "waiting_provider"
    checkpoint = session.checkpoint()
    assert session.world.tick == 1
    session.close("simulate worker restart")

    restored = RunSession.from_checkpoint(
        checkpoint,
        scheduler_provider=provider,
    )
    assert restored.world.tick == 1
    assert restored.bootstrap_state["phase"] == "waiting_provider"
    provider.release.set()
    deadline = perf_counter() + 2.0
    while restored.bootstrap_state["phase"] != "ready" and perf_counter() < deadline:
        sleep(0.005)
        restored.step()

    assert restored.bootstrap_state["phase"] == "ready"
    assert restored.world.tick >= 2
    assert restored.bootstrap_state["accepted_provider_output_count"] > 0
    assert restored.bootstrap_state["accepted_thought_sequences"]
    restored.close("test cleanup")


def test_post_ready_world_ticks_while_later_provider_jobs_remain_pending() -> None:
    provider = PartialBootstrapProvider()
    scheduler = default_agent_scheduler_config("tribe_survival", 4)
    scheduler.epoch_soft_deadline_seconds = 0.01
    session = RunSession(
        RunConfig(
            scenario="tribe_survival",
            ticks=4,
            scheduler=scheduler,
            scheduler_provider=provider,
            runtime_provider={"mode": "live"},
            require_cognition_ready=True,
        )
    )
    try:
        assert session.step() is True
        assert session.world.tick == 1
        assert session.bootstrap_state["phase"] == "waiting_provider"

        deadline = perf_counter() + 1.0
        while session.bootstrap_state["phase"] != "ready" and perf_counter() < deadline:
            sleep(0.015)
            session.step()

        assert session.bootstrap_state["phase"] == "ready"
        assert session.world.tick >= 2
        assert session.scheduler is not None
        assert session.scheduler.has_pending_provider_jobs is True

        assert session.step() is True
        assert session.world.tick >= 3
        assert session.scheduler.has_pending_provider_jobs is True
    finally:
        provider.release_remaining.set()
        session.close("test cleanup")


def test_cognition_epoch_starts_ten_relationship_and_five_protagonist_jobs_from_one_snapshot() -> (
    None
):
    class EpochProvider:
        name = "epoch-provider"
        network_backed = True

        def __init__(self) -> None:
            self.release = Event()
            self.contexts: list[tuple[int, str]] = []

        def observe(self, context: ProviderContext) -> ProviderOutput:
            epoch = context.params["cognition_epoch"]
            self.contexts.append((context.tick, str(epoch["snapshot_hash"])))
            self.release.wait(timeout=2.0)
            return ProviderOutput(source=self.name, summary="epoch cognition")

    world = World.scenario("enterprise_earth", seed=7)
    provider = EpochProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            dispatch_mode="cognition_epoch",
            max_concurrent=15,
            max_starts_per_tick=1,
            lane_limits={"relationship": 10, "protagonist": 5, "auxiliary": 1},
            daily_budget=15,
        )
    )
    scheduler.enqueue_many(
        [
            AgentJob(
                f"relationship-{index}",
                "relationship_round",
                provider,
                priority=100 - index,
                slot="tribe",
            )
            for index in range(10)
        ]
        + [
            AgentJob(
                f"protagonist-{index}",
                "key_character_continuity",
                provider,
                priority=80 - index,
                slot="protagonist",
            )
            for index in range(5)
        ]
    )

    assert scheduler.dispatch_tick(world, tick=0) == []
    deadline = perf_counter() + 1.0
    while len(provider.contexts) < 15 and perf_counter() < deadline:
        sleep(0.005)

    status = scheduler.status_snapshot()
    assert status["provider_pending_count"] == 15
    assert status["active_epoch"]["expected_job_ids"] == [
        *[f"relationship-{index}" for index in range(10)],
        *[f"protagonist-{index}" for index in range(5)],
    ]
    assert {tick for tick, _ in provider.contexts} == {0}
    assert len({snapshot_hash for _, snapshot_hash in provider.contexts}) == 1
    assert {item["epoch_order"] for item in status["provider_pending"]} == set(
        range(15)
    )

    provider.release.set()
    deadline = perf_counter() + 2.0
    while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
        sleep(0.005)
        scheduler.collect_pending(world)
    assert scheduler.has_pending_provider_jobs is False


def test_cognition_epoch_prefetch_requeues_core_job_generations() -> None:
    class ImmediateNetworkProvider:
        name = "recurring-epoch-provider"
        network_backed = True

        def observe(self, context: ProviderContext) -> ProviderOutput:
            return ProviderOutput(
                source=self.name,
                summary=str(context.params["cognition_epoch"]["epoch_id"]),
            )

    world = World.scenario("enterprise_earth", seed=7)
    provider = ImmediateNetworkProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            dispatch_mode="cognition_epoch",
            max_concurrent=2,
            lane_limits={"relationship": 1, "protagonist": 1},
            epoch_relationship_limit=1,
            epoch_protagonist_limit=1,
            epoch_start_limit=2,
            epoch_prefetch_seconds=0.0,
            daily_budget=4,
        )
    )
    scheduler.enqueue_many(
        [
            AgentJob("relationship", "relationship_round", provider, slot="tribe"),
            AgentJob(
                "protagonist", "key_character_continuity", provider, slot="protagonist"
            ),
        ]
    )

    scheduler.dispatch_tick(world, 0)
    deadline = perf_counter() + 1.0
    while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
        sleep(0.005)
        scheduler.collect_pending(world)
    scheduler.dispatch_tick(world, 1)

    assert scheduler.status_snapshot()["started_count"] == 4
    assert (
        scheduler.status_snapshot()["active_epoch"]["epoch_id"] == "cognition-epoch-2"
    )
    assert scheduler.status_snapshot()["dispatched_job_ids"] == [
        "relationship",
        "protagonist",
        "relationship::epoch-2",
        "protagonist::epoch-2",
    ]


def test_repeated_cognition_epochs_keep_ten_relationship_and_five_protagonist_heartbeats() -> (
    None
):
    class RecordingNetworkProvider:
        name = "repeated-epoch-provider"
        network_backed = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int, str]] = []

        def observe(self, context: ProviderContext) -> ProviderOutput:
            epoch = context.params["cognition_epoch"]
            packet = context.params["agent_context_packet"]
            self.calls.append(
                (
                    str(epoch["epoch_id"]),
                    str(packet["job"]["kind"]),
                    context.tick,
                    str(epoch["snapshot_hash"]),
                )
            )
            return ProviderOutput(source=self.name, summary="recurring cognition")

    world = World.scenario("enterprise_earth", seed=7)
    provider = RecordingNetworkProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            dispatch_mode="cognition_epoch",
            max_concurrent=15,
            lane_limits={"relationship": 10, "protagonist": 5, "auxiliary": 1},
            epoch_relationship_limit=10,
            epoch_protagonist_limit=5,
            epoch_start_limit=15,
            epoch_prefetch_seconds=0.0,
            daily_budget=30,
        )
    )
    scheduler.enqueue_many(
        enterprise_agent_jobs(
            world,
            include_static_lenses=False,
            provider_override=provider,
        )
    )

    for tick in (0, 1):
        scheduler.dispatch_tick(world, tick)
        deadline = perf_counter() + 2.0
        while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
            sleep(0.005)
            scheduler.collect_pending(world)
        assert scheduler.has_pending_provider_jobs is False

    by_epoch: dict[str, list[tuple[str, str, int, str]]] = {}
    for call in provider.calls:
        by_epoch.setdefault(call[0], []).append(call)

    assert scheduler.config.max_concurrent == 15
    assert len(by_epoch) == 2
    assert scheduler.status_snapshot()["started_count"] == 30
    for calls in by_epoch.values():
        assert len(calls) == 15
        assert sum(item[1] == "relationship_round" for item in calls) == 10
        assert sum(item[1] == "key_character_continuity" for item in calls) == 5
        assert len({item[2] for item in calls}) == 1
        assert len({item[3] for item in calls}) == 1


def test_cognition_epoch_streams_completed_thoughts_but_releases_mutations_in_stable_order() -> (
    None
):
    class OrderedProvider:
        network_backed = True

        def __init__(self, name: str) -> None:
            self.name = name
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.release.wait(timeout=2.0)
            packet = context.params["agent_context_packet"]
            candidates = packet.get("active_candidates") or packet.get("coverage_nodes")
            node_id = candidates[0]["id"]
            return ProviderOutput(
                source=self.name,
                summary=self.name,
                effects=[
                    effect(
                        "thought_bubble_add",
                        target=f"node:{node_id}",
                        text=f"thought:{self.name}",
                    ),
                    effect(
                        "rule_pressure_add",
                        target=f"node:{node_id}",
                        rule="movement",
                        weight=0.1,
                        ttl=1,
                    ),
                ],
            )

    world = World.scenario("enterprise_earth", seed=7)
    relationship = OrderedProvider("relationship-provider")
    protagonist = OrderedProvider("protagonist-provider")
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            dispatch_mode="cognition_epoch",
            max_concurrent=2,
            lane_limits={"relationship": 1, "protagonist": 1},
            epoch_relationship_limit=1,
            epoch_protagonist_limit=1,
            epoch_start_limit=2,
            epoch_soft_deadline_seconds=18,
            daily_budget=2,
        )
    )
    scheduler.enqueue_many(
        [
            AgentJob(
                "relationship",
                "relationship_round",
                relationship,
                priority=2,
                slot="tribe",
            ),
            AgentJob(
                "protagonist",
                "key_character_continuity",
                protagonist,
                priority=1,
                slot="protagonist",
            ),
        ]
    )
    scheduler.dispatch_tick(world, 0)

    protagonist.release.set()
    deadline = perf_counter() + 1.0
    early_outputs: list[ProviderOutput] = []
    while not early_outputs and perf_counter() < deadline:
        sleep(0.005)
        early_outputs = scheduler.collect_pending(world)
    assert [output.metadata["epoch_phase"] for output in early_outputs] == ["cognition"]
    assert [item.type for item in early_outputs[0].effects] == ["thought_bubble_add"]

    relationship.release.set()
    deadline = perf_counter() + 1.0
    final_outputs: list[ProviderOutput] = []
    while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
        sleep(0.005)
        final_outputs.extend(scheduler.collect_pending(world))
    authoritative = [
        output
        for output in final_outputs
        if output.metadata.get("epoch_phase") == "authoritative"
    ]
    assert [output.metadata["scheduler"]["job_id"] for output in authoritative] == [
        "relationship",
        "protagonist",
    ]
    assert all(
        [item.type for item in output.effects] == ["rule_pressure_add"]
        for output in authoritative
    )


def test_cognition_epoch_streams_each_relationship_schedule_before_slow_siblings() -> (
    None
):
    class RelationshipProvider:
        network_backed = True

        def __init__(self, name: str) -> None:
            self.name = name
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.release.wait(timeout=2.0)
            packet = context.params["agent_context_packet"]
            candidates = packet.get("active_candidates") or packet.get("coverage_nodes")
            node_id = candidates[0]["id"]
            return ProviderOutput(
                source=self.name,
                summary=self.name,
                effects=[
                    effect(
                        "thought_schedule_add",
                        target=f"node:{node_id}",
                        text=f"thought:{self.name}",
                        explicit_slices=[f"thought:{self.name}"],
                        origin="active_node",
                    )
                ],
            )

    world = World.scenario("enterprise_earth", seed=7)
    first = RelationshipProvider("relationship-first")
    slow = RelationshipProvider("relationship-slow")
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            dispatch_mode="cognition_epoch",
            max_concurrent=2,
            lane_limits={"relationship": 2, "protagonist": 1},
            epoch_relationship_limit=2,
            epoch_protagonist_limit=0,
            epoch_start_limit=2,
            epoch_soft_deadline_seconds=18,
            daily_budget=2,
        )
    )
    scheduler.enqueue_many(
        [
            AgentJob(
                "relationship-first",
                "relationship_round",
                first,
                priority=2,
                slot="tribe",
            ),
            AgentJob(
                "relationship-slow",
                "relationship_round",
                slow,
                priority=1,
                slot="tribe",
            ),
        ]
    )
    scheduler.dispatch_tick(world, 0)

    first.release.set()
    deadline = perf_counter() + 1.0
    first_outputs: list[ProviderOutput] = []
    while not first_outputs and perf_counter() < deadline:
        sleep(0.005)
        first_outputs = scheduler.collect_pending(world)

    assert scheduler.status_snapshot()["provider_pending_count"] == 1
    assert len(first_outputs) == 1
    assert first_outputs[0].metadata["presentation_epoch"]["streamed"] is True
    assert first_outputs[0].metadata["presentation_epoch"]["graph_orders"] == [0]
    assert [item.type for item in first_outputs[0].effects] == ["thought_schedule_add"]
    first_occurrence_ids = {
        occurrence["occurrence_id"]
        for item in first_outputs[0].effects
        for occurrence in item.fields["occurrences"]
    }

    duplicate = scheduler._route_epoch_cognition(  # noqa: SLF001
        AgentJob("relationship-first", "relationship_round", first),
        0,
        first_outputs[0],
    )
    assert duplicate == []

    slow.release.set()
    deadline = perf_counter() + 1.0
    slow_outputs: list[ProviderOutput] = []
    while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
        sleep(0.005)
        slow_outputs.extend(scheduler.collect_pending(world))

    assert len(slow_outputs) == 1
    assert slow_outputs[0].metadata["presentation_epoch"]["graph_orders"] == [1]
    slow_occurrence_ids = {
        occurrence["occurrence_id"]
        for item in slow_outputs[0].effects
        for occurrence in item.fields["occurrences"]
    }
    assert first_occurrence_ids.isdisjoint(slow_occurrence_ids)
    assert scheduler.status_snapshot()["provider_pending_count"] == 0


def test_stale_async_provider_output_retains_observation_memory() -> None:
    class NetworkProvider:
        name = "stale-network-provider"
        network_backed = True

        def __init__(self) -> None:
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.release.wait(timeout=1.0)
            target_id = context.params["agent_context_packet"]["active_candidates"][0][
                "id"
            ]
            return ProviderOutput(
                source=self.name,
                summary="stale pressure",
                effects=[
                    effect(
                        "memory_add", target=f"node:{target_id}", text="stale memory"
                    )
                ],
            )

    world = World("async-stale")
    world.add_node(
        "active",
        "person",
        "Active",
        (0, 0),
        {"agent_layer": "relationship_network_member"},
    )
    world.add_node(
        "peer", "person", "Peer", (1, 0), {"agent_layer": "relationship_network_member"}
    )
    edge = world.add_relationship("active", "peer", "trust", 0.8)
    provider = NetworkProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True, max_concurrent=1, dispatch_slots=["relationship"]
        )
    )
    scheduler.enqueue(
        AgentJob(
            "stale-relationship", "relationship_round", provider, slot="relationship"
        )
    )
    scheduler.dispatch_tick(world, tick=0)
    edge.weight = 0.1
    provider.release.set()
    deadline = perf_counter() + 1.0
    outputs = []
    while not outputs and perf_counter() < deadline:
        sleep(0.005)
        outputs = scheduler.collect_pending(world)

    assert len(outputs) == 1
    assert [effect.type for effect in outputs[0].effects] == ["memory_add"]
    assert outputs[0].metadata["provider_pending"]["status"] == "expired"


def test_run_harness_scheduler_mode_is_reproducible_and_auditable() -> None:
    config = RunConfig(
        scenario="enterprise_earth",
        seed=7,
        ticks=2,
        scheduler=AgentSchedulerConfig(enabled=True, max_concurrent=1, daily_budget=2),
    )

    first = run(config).to_dict()
    second = run(config).to_dict()

    assert first == second
    assert first["scheduler_status"]["enabled"] is True
    assert first["scheduler_status"]["started_count"] == 2
    assert first["scheduler_status"]["queue_length"] == 24
    assert first["scheduler_status"]["dispatched_job_ids"] == [
        "enterprise-tribe-round-1-org-science-council",
        "enterprise-protagonist-continuity-1-key-albert-einstein",
    ]
    assert len(first["provider_outputs"]) == 2
    assert (
        first["provider_outputs"][0]["scheduler"]["job_id"]
        == "enterprise-tribe-round-1-org-science-council"
    )
    assert (
        first["provider_outputs"][1]["scheduler"]["job_id"]
        == "enterprise-protagonist-continuity-1-key-albert-einstein"
    )
    assert any(
        event["payload"].get("scheduler")
        for event in first["events"]
        if event["kind"] == "action_feedback"
    )
    json.dumps(first, ensure_ascii=False)


def test_default_enterprise_scheduler_uses_readme_ai_isekai_loop() -> None:
    config = default_enterprise_scheduler_config(8)

    assert config.enabled is True
    assert config.dispatch_slots == AI_ISEKAI_DISPATCH_SLOTS
    assert config.dispatch_mode == "cognition_epoch"
    assert config.daily_budget == 15
    assert config.max_concurrent == 15
    assert config.epoch_start_limit == 15
    assert config.lane_limits == {"relationship": 10, "protagonist": 5, "auxiliary": 1}
    assert config.event_triggered_lenses is True
    assert config.pressure_triggered_jobs is True


def test_default_tribe_scheduler_uses_cognition_epoch_for_all_core_jobs() -> None:
    config = default_agent_scheduler_config("tribe_survival", 8)

    assert config.enabled is True
    assert config.dispatch_slots == AI_ISEKAI_DISPATCH_SLOTS
    assert config.dispatch_mode == "cognition_epoch"
    assert config.daily_budget == 16
    assert config.max_concurrent == 16
    assert config.epoch_relationship_limit == 11
    assert config.epoch_protagonist_limit == 5
    assert config.epoch_start_limit == 16
    assert config.lane_limits == {"relationship": 11, "protagonist": 5, "auxiliary": 1}
    assert config.event_triggered_lenses is False
    assert config.pressure_triggered_jobs is False


def test_scheduler_config_round_trip_preserves_every_cognition_epoch_field() -> None:
    config = AgentSchedulerConfig(
        enabled=True,
        dispatch_mode="cognition_epoch",
        max_concurrent=15,
        max_starts_per_tick=7,
        lane_limits={"relationship": 9, "protagonist": 4, "auxiliary": 2},
        epoch_relationship_limit=9,
        epoch_protagonist_limit=4,
        epoch_start_limit=13,
        epoch_soft_deadline_seconds=12.5,
        epoch_prefetch_seconds=22.5,
        daily_budget=61,
        dispatch_slots=["relationship", "key_character"],
        event_triggered_lenses=True,
        max_triggered_lenses_per_tick=3,
        trigger_feedback_limit=17,
        pressure_triggered_jobs=True,
        max_pressure_triggered_jobs_per_tick=4,
        pressure_trigger_threshold=1.75,
    )

    restored = AgentSchedulerConfig.from_dict(config.to_dict())
    run_restored = RunConfig.from_dict(
        RunConfig(scenario="enterprise_earth", scheduler=config).to_dict()
    ).scheduler

    assert restored.to_dict() == config.to_dict()
    assert run_restored is not None
    assert run_restored.to_dict() == config.to_dict()


def test_cancel_pending_cooperatively_stops_provider_and_discards_effects() -> None:
    class CancelableProvider:
        name = "cancelable-provider"
        network_backed = True

        def __init__(self) -> None:
            self.started = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.started.set()
            while True:
                assert context.cancellation is not None
                context.cancellation.raise_if_cancelled()
                sleep(0.002)

    world = World.scenario("enterprise_earth", seed=7)
    provider = CancelableProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            max_concurrent=1,
            dispatch_slots=["relationship"],
        )
    )
    scheduler.enqueue(
        AgentJob(
            "cancelable-relationship",
            "relationship_round",
            provider,
            slot="relationship",
        )
    )
    scheduler.dispatch_tick(world, 0)
    assert provider.started.wait(timeout=1.0)

    scheduler.cancel_pending("operator canceled")
    outputs: list[ProviderOutput] = []
    deadline = perf_counter() + 1.0
    while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
        sleep(0.002)
        outputs.extend(scheduler.lifecycle_step(world))

    assert scheduler.lifecycle_state == "canceled"
    assert scheduler.has_pending_provider_jobs is False
    assert (
        scheduler.enqueue(AgentJob("too-late", "relationship_round", provider)) is False
    )
    assert outputs
    assert all(not output.effects for output in outputs)
    assert outputs[0].metadata["provider_pending"]["status"] == "canceled"
    scheduler.close()


def test_graceful_drain_finishes_current_job_without_starting_another() -> None:
    class DrainProvider:
        name = "drain-provider"
        network_backed = True

        def __init__(self) -> None:
            self.calls = 0
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.calls += 1
            self.release.wait(timeout=1.0)
            return ProviderOutput(source=self.name, summary=str(context.tick))

    world = World.scenario("enterprise_earth", seed=7)
    provider = DrainProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            max_concurrent=1,
            dispatch_slots=["relationship"],
        )
    )
    scheduler.enqueue_many(
        [
            AgentJob(
                "drain-current", "relationship_round", provider, slot="relationship"
            ),
            AgentJob("drain-next", "relationship_round", provider, slot="relationship"),
        ]
    )
    scheduler.dispatch_tick(world, 0)
    scheduler.begin_drain(1.0, "graceful stop")
    provider.release.set()
    deadline = perf_counter() + 1.0
    while not scheduler.drained and perf_counter() < deadline:
        sleep(0.002)
        scheduler.lifecycle_step(world)

    assert scheduler.lifecycle_state == "drained"
    assert provider.calls == 1
    assert scheduler.dispatch_tick(world, 1) == []
    assert provider.calls == 1
    scheduler.close()


def test_enterprise_core_run_defaults_to_readme_loop_scheduler() -> None:
    result = run(RunConfig(scenario="enterprise_earth", seed=7, ticks=2)).to_dict()

    assert result["config"]["scheduler"]["dispatch_slots"] == AI_ISEKAI_DISPATCH_SLOTS
    assert result["config"]["scheduler"]["event_triggered_lenses"] is True
    assert result["config"]["scheduler"]["pressure_triggered_jobs"] is True
    dispatched = result["scheduler_status"]["dispatched_job_ids"]
    assert len(dispatched) == 15
    assert len([job_id for job_id in dispatched if "tribe-round" in job_id]) == 10
    assert (
        len([job_id for job_id in dispatched if "protagonist-continuity" in job_id])
        == 5
    )
    assert result["scheduler_status"]["active_epoch"]["relationship_count"] == 10
    assert result["scheduler_status"]["active_epoch"]["protagonist_count"] == 5
    assert (
        result["provider_outputs"][0]["provider_boundary"]["replaceable_provider"]
        is True
    )
    assert (
        result["provider_outputs"][0]["context_packet"][
            "pressure_action_reflection_count"
        ]
        >= 0
    )


def test_existing_provider_modes_still_work() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    context = ProviderContext(world, world.tick, world.snapshot())

    assert (
        DeterministicPressureProvider().observe(context).source
        == "deterministic-pressure"
    )
    assert (
        DeterministicEnterpriseAgentProvider()
        .observe(context)
        .metadata["relationship_round"]["active_node_count"]
        == ACTIVE_NODE_LIMIT
    )
    assert (
        DeterministicKeyCharacterContinuityProvider()
        .observe(context)
        .metadata["key_character_continuity"]["active_character_count"]
        == 5
    )


def test_event_triggered_lens_jobs_score_recent_feedback() -> None:
    world = World.scenario("enterprise_earth", seed=7)

    static_jobs = enterprise_agent_jobs(world, include_static_lenses=False)
    triggered_jobs = enterprise_event_triggered_lens_jobs(world, tick=0, limit=2)

    assert [job.kind for job in static_jobs].count("relationship_round") == 10
    assert [job.kind for job in static_jobs].count("key_character_continuity") == 5
    assert static_jobs[0].slot == "tribe"
    assert static_jobs[10].slot == "protagonist"
    assert (
        len({job.graph_key for job in static_jobs if job.kind == "relationship_round"})
        == 10
    )
    assert (
        len(
            {
                job.metadata["target_node_id"]
                for job in static_jobs
                if job.kind == "key_character_continuity"
            }
        )
        == 5
    )
    assert triggered_jobs
    assert all(job.kind == "commercial_lens" for job in triggered_jobs)
    assert all(job.metadata["triggered"] is True for job in triggered_jobs)
    assert all(job.metadata["trigger_score"] > 0 for job in triggered_jobs)
    assert all(job.metadata["trigger_reasons"] for job in triggered_jobs)


def test_enterprise_scheduler_jobs_accept_provider_override_for_model_backed_jobs() -> (
    None
):
    class OverrideProvider:
        name = "override-json-llm-provider"

        def observe(self, context: ProviderContext) -> ProviderOutput:
            return ProviderOutput(source=self.name, summary="override observed")

    world = World.scenario("enterprise_earth", seed=7)
    override_target = world.node("org-science-council:policy-node-01")
    world.set_movement_target(
        override_target.id,
        (override_target.position.x + 1, override_target.position.y),
        0.5,
    )
    override_target.rule_pressures.append(
        {"rule": "move", "weight": 1.0, "ttl": 1, "reason": "test pressure"}
    )
    provider = OverrideProvider()

    jobs = enterprise_agent_jobs(
        world, include_static_lenses=True, provider_override=provider
    )
    pressure_jobs = enterprise_pressure_triggered_jobs(
        world, tick=0, threshold=0.0, limit=1, provider_override=provider
    )

    model_jobs = [
        job
        for job in jobs
        if job.kind in {"relationship_round", "key_character_continuity"}
    ]
    lens_jobs = [
        job for job in jobs if job.kind in {"commercial_lens", "relationship_lens"}
    ]

    assert model_jobs
    assert all(job.provider is provider for job in model_jobs)
    assert lens_jobs
    assert all(job.provider is not provider for job in lens_jobs)
    assert pressure_jobs[0].provider is provider


def test_run_harness_event_triggered_lenses_are_reproducible_and_auditable() -> None:
    config = RunConfig(
        scenario="enterprise_earth",
        seed=7,
        ticks=4,
        scheduler=AgentSchedulerConfig(
            enabled=True,
            max_concurrent=1,
            daily_budget=4,
            dispatch_slots=["relationship", "key_character", "lens", "lens"],
            event_triggered_lenses=True,
            max_triggered_lenses_per_tick=2,
        ),
    )

    first = run(config).to_dict()
    second = run(config).to_dict()
    lens_outputs = [
        item for item in first["provider_outputs"] if item.get("commercial_lens")
    ]

    assert first == second
    assert first["config"]["scheduler"]["event_triggered_lenses"] is True
    assert first["scheduler_status"]["started_count"] == 4
    assert lens_outputs
    assert all(
        item["scheduler"]["job_metadata"]["triggered"] is True for item in lens_outputs
    )
    assert all(
        item["scheduler"]["job_metadata"]["trigger_score"] > 0 for item in lens_outputs
    )


def test_pressure_triggered_jobs_focus_high_pressure_nodes() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    target = world.node("org-science-council:policy-node-01")
    world.set_movement_target(
        target.id, (target.position.x + 1, target.position.y), 0.5
    )
    target.rule_pressures.append(
        {"rule": "move", "weight": 1.5, "ttl": 2, "reason": "urgent pressure"}
    )

    jobs = enterprise_pressure_triggered_jobs(world, tick=2, limit=1, threshold=1.0)
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True, max_concurrent=1, dispatch_slots=["relationship"]
        )
    )
    scheduler.enqueue_many(jobs)
    outputs = scheduler.dispatch_tick(world, tick=2)

    assert len(jobs) == 1
    assert jobs[0].id == f"enterprise-high-pressure-{target.id}"
    assert jobs[0].kind == "high_pressure_response"
    assert jobs[0].metadata["trigger_node_ids"] == [target.id]
    assert outputs[0].metadata["context_packet"]["active_candidate_count"] == 1
    assert (
        outputs[0].metadata["scheduler"]["job_metadata"]["trigger_type"]
        == "pressure_threshold"
    )
    assert outputs[0].metadata["high_pressure_response"]["active_node_ids"] == [
        target.id
    ]
    assert outputs[0].metadata["high_pressure_response"][
        "grounded_pressure_node_ids"
    ] == [target.id]


def test_pressure_triggered_jobs_ignore_stale_move_pressure() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    target = world.node("org-science-council:policy-node-01")
    target.rule_pressures.append(
        {"rule": "move", "weight": 3.0, "ttl": 4, "reason": "arrived"}
    )

    assert (
        enterprise_pressure_triggered_jobs(world, tick=2, limit=1, threshold=1.0) == []
    )


def test_run_harness_pressure_triggered_jobs_are_reproducible_and_auditable() -> None:
    config = RunConfig(
        scenario="enterprise_earth",
        seed=7,
        ticks=3,
        scheduler=AgentSchedulerConfig(
            enabled=True,
            max_concurrent=2,
            daily_budget=5,
            dispatch_slots=["key_character", "pressure", "pressure"],
            pressure_triggered_jobs=True,
            max_pressure_triggered_jobs_per_tick=2,
            pressure_trigger_threshold=0.4,
        ),
    )

    first = run(config).to_dict()
    second = run(config).to_dict()
    high_pressure_outputs = [
        item for item in first["provider_outputs"] if item.get("high_pressure_response")
    ]

    assert first == second
    assert first["config"]["scheduler"]["pressure_triggered_jobs"] is True
    assert high_pressure_outputs
    assert all(
        item["scheduler"]["job_kind"] == "high_pressure_response"
        for item in high_pressure_outputs
    )
    assert all(
        item["scheduler"]["job_metadata"]["trigger_score"] >= 0.4
        for item in high_pressure_outputs
    )
    dispatched_pressure_ids = [
        job_id
        for job_id in first["scheduler_status"]["dispatched_job_ids"]
        if job_id.startswith("enterprise-high-pressure-")
    ]
    assert len(dispatched_pressure_ids) == len(set(dispatched_pressure_ids))


def test_high_pressure_provider_without_candidates_is_empty() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    output = DeterministicHighPressureResponseProvider().observe(
        ProviderContext(
            world,
            world.tick,
            world.snapshot(),
            {"agent_context_packet": {"active_candidates": []}},
        )
    )

    assert output.effects == []
    assert output.metadata["high_pressure_response"]["active_node_count"] == 0


def test_high_pressure_provider_preserves_visible_output_without_static_move_pressure() -> (
    None
):
    world = World.scenario("enterprise_earth", seed=7)
    target = world.node("org-science-council:policy-node-01")
    target.rule_pressures.append(
        {"rule": "move", "weight": 2.0, "ttl": 3, "reason": "stale"}
    )
    output = DeterministicHighPressureResponseProvider().observe(
        ProviderContext(
            world,
            world.tick,
            world.snapshot(),
            {"agent_context_packet": {"active_candidates": [{"id": target.id}]}},
        )
    )
    effects = [item.to_dict() for item in output.effects]

    assert any(item["type"] == "thought_bubble_add" for item in effects)
    assert any(item["type"] == "memory_add" for item in effects)
    assert not any(item["type"] == "rule_pressure_add" for item in effects)
    assert output.metadata["high_pressure_response"]["active_node_ids"] == [target.id]
    assert output.metadata["high_pressure_response"]["grounded_pressure_node_ids"] == []


def test_default_enterprise_run_meets_grounding_and_backlog_acceptance() -> None:
    ticks = 7
    result = run(RunConfig(scenario="enterprise_earth", seed=7, ticks=ticks)).to_dict()
    metrics = result["scorecard"]["metrics"]
    scheduler = result["scheduler_status"]
    queued_jobs = scheduler["queued_jobs"]
    queued_pressure_ids = [
        job["id"] for job in queued_jobs if job["kind"] == "high_pressure_response"
    ]
    initial_wheel_size = len(
        enterprise_agent_jobs(
            World.scenario("enterprise_earth", seed=7), include_static_lenses=False
        )
    )
    max_unique_triggered_work = ticks * result["config"]["scheduler"][
        "max_triggered_lenses_per_tick"
    ] + len(result["snapshot"]["nodes"])

    assert metrics["pressure_match_rate"] >= 0.8
    assert result["scorecard"]["score"] >= 80
    assert metrics["world_errors"] == 0
    assert len(queued_pressure_ids) == len(set(queued_pressure_ids))
    assert not set(queued_pressure_ids) & set(scheduler["dispatched_job_ids"])
    assert scheduler["queue_length"] <= initial_wheel_size + max_unique_triggered_work
