import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import perf_counter, sleep

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    AgentJob,
    AgentScheduler,
    AgentSchedulerConfig,
    FeedbackIngestor,
    OpenAICompatibleJsonClient,
    PressureActionTraceLedger,
    ProviderContext,
    ProviderOutcomeLedger,
    ProviderOutput,
    RunConfig,
    RunSession,
    RuleEngineSet,
    World,
    evaluate_run,
    effect,
    run,
)
from ai_native_world_engine.core.action_grounding import (
    ENTERPRISE_AGENT_RULES,
    action_option_is_groundable,
    groundable_action_options,
)
from ai_native_world_engine.core.provider_telemetry import (
    accumulate_provider_usage,
    merge_provider_attempts,
    provider_attempt_totals,
    provider_attempts_from_output,
)


def test_cumulative_attempt_usage_survives_bounded_recent_sample() -> None:
    attempts = [
        {
            "attempt_id": f"attempt-{index}",
            "status": "completed",
            "prompt_tokens": index + 1,
            "completion_tokens": 2,
            "estimated_cost": 0.1,
            "total_latency_ms": 1.5,
        }
        for index in range(101)
    ]
    retained, dropped = merge_provider_attempts([], attempts, retention=100)
    report = provider_attempt_totals(
        retained,
        dropped,
        accumulate_provider_usage(None, attempts),
    )

    assert report["attempts"] == 101
    assert report["retained_attempts"] == 100
    assert report["prompt_tokens"] == sum(range(1, 102))
    assert report["completion_tokens"] == 202
    assert report["estimated_cost"] == 10.1


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_two_http_calls_keep_call_local_transport_telemetry(monkeypatch) -> None:
    from ai_native_world_engine.core import llm_provider

    rendezvous = Barrier(2)
    idempotency_keys: dict[str, str | None] = {}

    def fake_urlopen(http_request, timeout):
        del timeout
        request_payload = json.loads(http_request.data.decode("utf-8"))
        envelope = json.loads(request_payload["messages"][1]["content"])
        label = envelope["label"]
        idempotency_keys[label] = http_request.get_header("Idempotency-key")
        rendezvous.wait(timeout=1.0)
        prompt_tokens = 11 if label == "relationship" else 29
        return _JsonResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"summary": label, "effects": []}
                            )
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": prompt_tokens + 1,
                    "completion_tokens_details": {
                        "reasoning_tokens": prompt_tokens + 2
                    },
                },
            }
        )

    monkeypatch.setattr(llm_provider.request, "urlopen", fake_urlopen)
    clients = {
        label: OpenAICompatibleJsonClient(
            api_key=f"secret-{label}",
            base_url="https://example.test/v1",
            model=f"model-{label}",
        )
        for label in ("relationship", "protagonist")
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            label: executor.submit(
                client.complete,
                {
                    "label": label,
                    "_provider_request_id": f"request-{label}",
                },
            )
            for label, client in clients.items()
        }
        results = {label: future.result() for label, future in futures.items()}

    assert results["relationship"].output["summary"] == "relationship"
    assert results["protagonist"].output["summary"] == "protagonist"
    assert results["relationship"].runtime_metadata["prompt_tokens"] == 11
    assert results["protagonist"].runtime_metadata["prompt_tokens"] == 29
    assert results["relationship"].runtime_metadata["reasoning_tokens"] == 13
    assert results["protagonist"].runtime_metadata["reasoning_tokens"] == 31
    assert idempotency_keys == {
        "relationship": "request-relationship",
        "protagonist": "request-protagonist",
    }
    assert "secret-" not in str(results)


def test_attempt_ledger_is_allowlisted_deduplicated_and_bounded() -> None:
    output = {
        "source": "deepseek-live",
        "scheduler": {
            "job_id": "relationship-1",
            "job_kind": "relationship_round",
            "graph_key": "graph-1",
            "dispatched_tick": 2,
        },
        "provider_runtime": {
            "provider": "deepseek-live",
            "model": "deepseek-v4-flash",
            "api_key": "must-not-persist",
            "prompt": "must-not-persist",
            "attempt_phases": [
                {
                    "attempt": 1,
                    "status": "failed",
                    "request_bytes": 100,
                    "prompt_tokens": 20,
                    "prompt_cache_hit_tokens": 4,
                    "prompt_cache_miss_tokens": 16,
                    "prompt_template_version": "layered-agent-context-v2",
                    "stable_prefix_sha256": "a" * 64,
                    "model_context_projection": "relationship_model_context_v2",
                    "model_context_bytes": 64,
                    "model_context_l0_bytes": 32,
                    "model_context_l1_bytes": 16,
                    "model_context_l2_bytes": 16,
                    "evidence_candidate_count": 3,
                    "evidence_selected_count": 2,
                    "evidence_duplicate_suppressed_count": 1,
                    "authorization": "Bearer must-not-persist",
                    "response_body": "must-not-persist",
                },
                {
                    "attempt": 2,
                    "status": "completed",
                    "request_bytes": 80,
                    "completion_tokens": 9,
                    "total_latency_ms": 12.5,
                },
            ],
        },
    }

    additions = provider_attempts_from_output(output)
    retained, dropped = merge_provider_attempts([], additions + additions, retention=1)

    assert len(additions) == 2
    assert additions[0]["repair"] is False
    assert additions[1]["repair"] is True
    assert additions[0]["prompt_cache_hit_tokens"] == 4
    assert additions[0]["model_context_l0_bytes"] == 32
    assert additions[0]["evidence_duplicate_suppressed_count"] == 1
    assert additions[0]["stable_prefix_sha256"] == "a" * 64
    assert len(retained) == 1
    assert dropped == 1
    serialized = json.dumps(additions)
    assert "must-not-persist" not in serialized
    assert "authorization" not in serialized
    assert "response_body" not in serialized


def test_default_scheduler_overlaps_core_lanes_and_carries_overdue_work() -> None:
    class BlockingProvider:
        network_backed = True

        def __init__(self, name: str) -> None:
            self.name = name
            self.started = Event()
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.started.set()
            self.release.wait(timeout=2.0)
            return ProviderOutput(
                source=self.name,
                summary=f"{self.name} from {context.tick}",
            )

    world = World.scenario("enterprise_earth", seed=7)
    relationship_1 = BlockingProvider("relationship-1")
    protagonist = BlockingProvider("protagonist")
    relationship_2 = BlockingProvider("relationship-2")
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True,
            max_concurrent=2,
            max_starts_per_tick=1,
            lane_limits={"relationship": 1, "protagonist": 1},
            dispatch_slots=["relationship", "protagonist"],
        )
    )
    scheduler.enqueue_many(
        [
            AgentJob(
                "relationship-1",
                "relationship_round",
                relationship_1,
                slot="relationship",
                priority=2,
            ),
            AgentJob(
                "relationship-2",
                "relationship_round",
                relationship_2,
                slot="relationship",
                priority=1,
            ),
            AgentJob(
                "protagonist-1",
                "key_character_continuity",
                protagonist,
                slot="protagonist",
            ),
        ]
    )

    scheduler.dispatch_tick(world, 0)
    scheduler.dispatch_tick(world, 1)
    scheduler.dispatch_tick(world, 2)

    assert relationship_1.started.wait(timeout=1.0)
    assert protagonist.started.wait(timeout=1.0)
    assert relationship_2.started.is_set() is False
    assert scheduler.status_snapshot()["provider_pending_count"] == 2
    assert scheduler.status_snapshot()["eligible_jobs"][0]["job_id"] == "relationship-2"

    relationship_1.release.set()
    deadline = perf_counter() + 1.0
    while scheduler.status_snapshot()["provider_pending_count"] == 2 and perf_counter() < deadline:
        sleep(0.005)
        scheduler.collect_pending(world)
    scheduler.dispatch_tick(world, 3)

    assert relationship_2.started.wait(timeout=1.0)
    assert protagonist.release.is_set() is False
    assert scheduler.status_snapshot()["provider_pending_count"] == 2

    protagonist.release.set()
    relationship_2.release.set()
    deadline = perf_counter() + 1.0
    while scheduler.has_pending_provider_jobs and perf_counter() < deadline:
        sleep(0.005)
        scheduler.collect_pending(world)
    assert scheduler.has_pending_provider_jobs is False


def test_cognition_epoch_keeps_rule_world_advancing_while_provider_is_pending() -> None:
    class BlockingEpochProvider:
        name = "blocking-epoch-provider"
        network_backed = True

        def __init__(self) -> None:
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            self.release.wait(timeout=2.0)
            return ProviderOutput(source=self.name, summary="epoch completed")

    provider = BlockingEpochProvider()
    session = RunSession(
        RunConfig(
            scenario="enterprise_earth",
            seed=7,
            ticks=1,
            scheduler=AgentSchedulerConfig(
                enabled=True,
                dispatch_mode="cognition_epoch",
                max_concurrent=1,
                lane_limits={"relationship": 1},
                epoch_relationship_limit=1,
                epoch_protagonist_limit=0,
                epoch_start_limit=1,
                daily_budget=1,
            ),
            scheduler_provider=provider,
        )
    )

    session.step()
    assert session.phase == "provider_draining"
    assert session.world.tick == 1
    session.step()
    assert session.phase == "provider_draining"
    assert session.world.tick == 2

    provider.release.set()
    deadline = perf_counter() + 2.0
    while not session.completed and perf_counter() < deadline:
        session.step()
    assert session.completed is True
    assert session.world.tick >= 3


def test_restored_pending_generation_is_applied_at_most_once() -> None:
    class ReplayableProvider:
        name = "replayable-provider"
        network_backed = True

        def __init__(self) -> None:
            self.calls = 0
            self.lock = Lock()
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            with self.lock:
                self.calls += 1
            self.release.wait(timeout=2.0)
            return ProviderOutput(
                source=self.name,
                summary=f"attempt from {context.tick}",
            )

    world = World.scenario("enterprise_earth", seed=7)
    provider = ReplayableProvider()
    config = AgentSchedulerConfig(
        enabled=True,
        max_concurrent=1,
        dispatch_slots=["relationship"],
    )
    original = AgentScheduler(config)
    job = AgentJob(
        "restored-relationship",
        "relationship_round",
        provider,
        slot="relationship",
    )
    original.enqueue(job)
    original.dispatch_tick(world, 0)
    checkpoint = original.checkpoint_state()

    restored = AgentScheduler(config)
    restored.enqueue(job)
    restored.restore_state(world, checkpoint)
    deadline = perf_counter() + 1.0
    while provider.calls < 2 and perf_counter() < deadline:
        sleep(0.005)
    provider.release.set()
    deadline = perf_counter() + 1.0
    outputs = []
    while not outputs and perf_counter() < deadline:
        sleep(0.005)
        outputs = restored.collect_pending(world)

    assert provider.calls == 2
    assert len(outputs) == 1
    assert restored.collect_pending(world) == []
    assert [item["job_id"] for item in restored.completed_provider_jobs] == [
        "restored-relationship"
    ]


def test_cognition_epoch_checkpoint_restores_snapshot_and_request_identity() -> None:
    class EpochRecoveryProvider:
        name = "epoch-recovery-provider"
        network_backed = True

        def __init__(self) -> None:
            self.calls = 0
            self.lock = Lock()
            self.release = Event()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            with self.lock:
                self.calls += 1
            self.release.wait(timeout=2.0)
            return ProviderOutput(source=self.name, summary="epoch retry")

    def jobs(provider: EpochRecoveryProvider) -> list[AgentJob]:
        return [
            AgentJob(
                "recover-relationship",
                "relationship_round",
                provider,
                slot="tribe",
            ),
            AgentJob(
                "recover-protagonist",
                "key_character_continuity",
                provider,
                slot="protagonist",
            ),
        ]

    world = World.scenario("enterprise_earth", seed=7)
    provider = EpochRecoveryProvider()
    config = AgentSchedulerConfig(
        enabled=True,
        dispatch_mode="cognition_epoch",
        max_concurrent=2,
        lane_limits={"relationship": 1, "protagonist": 1},
        epoch_relationship_limit=1,
        epoch_protagonist_limit=1,
        epoch_start_limit=2,
    )
    original = AgentScheduler(config)
    original.enqueue_many(jobs(provider))
    original.dispatch_tick(world, 0)
    checkpoint = original.checkpoint_state()
    original_pending = {
        item["job_id"]: item
        for item in checkpoint["pending_provider_jobs"]
    }

    restored = AgentScheduler(config)
    restored.enqueue_many(jobs(provider))
    restored.restore_state(world, checkpoint)
    restored_state = restored.checkpoint_state()
    restored_pending = {
        item["job_id"]: item
        for item in restored_state["pending_provider_jobs"]
    }

    assert restored_state["active_epoch_snapshot"] == checkpoint[
        "active_epoch_snapshot"
    ]
    assert restored_state["active_epoch"]["snapshot_hash"] == checkpoint[
        "active_epoch"
    ]["snapshot_hash"]
    assert set(restored_pending) == set(original_pending)
    assert all(
        restored_pending[job_id]["request_id"]
        == original_pending[job_id]["request_id"]
        for job_id in restored_pending
    )
    assert {
        item["transport_attempt"] for item in restored_pending.values()
    } == {2}

    provider.release.set()
    deadline = perf_counter() + 1.0
    while (
        (original.has_pending_provider_jobs or restored.has_pending_provider_jobs)
        and perf_counter() < deadline
    ):
        sleep(0.002)
        original.collect_pending(world)
        restored.collect_pending(world)
    original.close()
    restored.close()


def test_pending_observation_is_visible_but_not_scored_as_unmatched() -> None:
    world = World("pending-observation")
    world.add_node("a", "person", "A", (0, 0))
    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="deepseek-live",
            actor_type="agent",
            actor_id="relationship-job",
            action="provider_pressure",
            summary="late intention",
            effects=[
                effect(
                    "rule_pressure_add",
                    target="node:a",
                    rule="movement",
                    action="move",
                    weight=0.7,
                    ttl=3,
                    pressure_id="pressure-pending-1",
                    observation_deadline_tick=3,
                )
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )
    pressure_report = PressureActionTraceLedger().build_report(world)
    base = run(RunConfig(scenario="seed", ticks=0)).to_dict()
    base["snapshot"] = world.snapshot()
    base["events"] = world.events.recent()
    base["pressure_action_report"] = pressure_report
    base["provider_outcome_report"] = ProviderOutcomeLedger().build_report(world)

    scorecard = evaluate_run(base).to_dict()

    assert pressure_report["totals"]["pending_observation"] == 1
    assert pressure_report["totals"]["unmatched"] == 0
    assert scorecard["metrics"]["pending_pressure_observations"] == 1
    assert scorecard["metrics"]["provider_pending_observations"] == 1
    assert not any(
        penalty["kind"] == "unmatched_pressure"
        for penalty in scorecard["penalties"]
    )


def test_enterprise_action_options_are_candidate_proven_and_static_nodes_do_not_move() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    static_node_ids = [
        node.id
        for node in world.nodes.values()
        if node.attributes.get("agent_layer") == "relationship_network_member"
    ][:10]

    options = groundable_action_options(
        world,
        static_node_ids,
        ENTERPRISE_AGENT_RULES,
    )

    assert options
    assert all(action_option_is_groundable(world, option) for option in options)
    assert not any(option["rule"] == "movement" for option in options)
    assert {option["rule"] for option in options} <= set(ENTERPRISE_AGENT_RULES)


def test_exact_pressure_id_flows_to_authoritative_action_feedback() -> None:
    world = World("causal-action")
    world.add_node("a", "person", "A", (0, 0))
    world.add_node("b", "person", "B", (1, 0))
    world.add_relationship("a", "b", "trust", 0.8)
    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="deepseek-live",
            actor_type="agent",
            actor_id="relationship-job",
            action="provider_pressure",
            summary="choose collaboration",
            effects=[
                effect(
                    "rule_pressure_add",
                    target="node:a",
                    rule="collaboration",
                    action="collaboration",
                    expected_action="collaboration",
                    weight=0.8,
                    ttl=3,
                    pressure_id="pressure-exact-1",
                    provider_job_id="relationship-job",
                    option_id="option-1",
                    observation_deadline_tick=3,
                    **{"with": "b"},
                )
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )
    world.step(RuleEngineSet.from_scenario(["collaboration"]))

    action_event = next(
        event
        for event in world.events.recent()
        if event["kind"] == "action_feedback"
        and event["payload"].get("actor_id") == "a"
        and event["payload"].get("action") == "collaboration"
    )
    assert action_event["payload"]["caused_by_pressure_ids"] == [
        "pressure-exact-1"
    ]
    assert world.node("a").rule_pressures == []
    world.step(RuleEngineSet.from_scenario(["collaboration"]))
    correlated_actions = [
        event
        for event in world.events.recent()
        if event["kind"] == "action_feedback"
        and "pressure-exact-1" in event["payload"].get("caused_by_pressure_ids", [])
    ]
    assert len(correlated_actions) == 1
    report = PressureActionTraceLedger().build_report(world)
    provider_report = ProviderOutcomeLedger().build_report(world)
    assert report["totals"]["matched"] == 1
    assert report["recent"][0]["status"] == "matched"
    assert provider_report["totals"]["alignment_rate"] == 1.0


def test_late_network_pressure_drains_and_settles_without_new_provider_dispatch() -> None:
    class LateMovementProvider:
        name = "late-movement-provider"
        network_backed = True

        def __init__(self) -> None:
            self.release = Event()
            self.calls = 0
            self.lock = Lock()

        def observe(self, context: ProviderContext) -> ProviderOutput:
            with self.lock:
                self.calls += 1
            self.release.wait(timeout=2.0)
            node_id = context.params["agent_context_packet"]["active_candidates"][0]["id"]
            return ProviderOutput(
                source=self.name,
                summary="late grounded movement",
                effects=[
                    effect(
                        "rule_pressure_add",
                        target=f"node:{node_id}",
                        rule="movement",
                        action="move",
                        expected_action="move",
                        weight=0.9,
                        ttl=3,
                        pressure_id="pressure-late-1",
                        provider_job_id="late-relationship",
                        option_id="option-late-1",
                        source_tick=context.tick,
                        observation_deadline_tick=context.tick + 3,
                    )
                ],
            )

    provider = LateMovementProvider()
    session = RunSession(
        RunConfig(
            scenario="enterprise_earth",
            seed=7,
            ticks=1,
            rules=["movement"],
            scheduler=AgentSchedulerConfig(
                enabled=True,
                max_concurrent=1,
                max_starts_per_tick=1,
                lane_limits={"relationship": 1},
                daily_budget=1,
                dispatch_slots=["relationship"],
            ),
            scheduler_provider=provider,
            causal_settle_ticks=3,
        )
    )
    for node in session.world.nodes.values():
        if node.attributes.get("agent_layer") == "relationship_network_member":
            session.world.set_movement_target(
                node.id,
                (node.position.x + 10, node.position.y),
                0.25,
            )

    session.step()
    assert session.phase == "provider_draining"
    assert session.world.tick == 1
    provider.release.set()
    deadline = perf_counter() + 2.0
    while not session.completed and perf_counter() < deadline:
        session.step()

    result = session.result().to_dict()
    assert session.completed is True
    assert session.phase == "completed"
    assert session.world.tick == 2
    assert session.settle_ticks_completed == 1
    assert provider.calls == 1
    assert result["provider_outcome_report"]["totals"]["matched_pressures"] == 1
    assert result["provider_outcome_report"]["totals"]["pending_observation"] == 0
    assert result["scorecard"]["metrics"]["provider_unmatched_pressures"] == 0
