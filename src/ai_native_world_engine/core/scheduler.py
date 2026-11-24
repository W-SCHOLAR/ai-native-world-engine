"""Deterministic in-process agent scheduler."""

from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from hashlib import sha256
import json
from time import perf_counter
from typing import Any

from .action_grounding import groundable_action_options
from .agent_context import AgentContextPacketBuilder
from .events import json_copy
from .feedback import WorldEffect
from .providers import (
    AgentProvider,
    CancellationToken,
    ProviderAttemptBudget,
    ProviderCancelled,
    ProviderContext,
    ProviderOutput,
)
from .pressure_grounding import rule_pressure_is_groundable
from .thought_presentation import (
    plan_incremental_relationship_presentation,
    plan_normal_relationship_presentation,
)
from .world import World


JsonDict = dict[str, Any]

AI_ISEKAI_DISPATCH_SLOTS = [
    "tribe_1",
    "protagonist_1",
    "tribe_2",
    "protagonist_2",
    "tribe_3",
    "protagonist_3",
    "tribe_4",
    "protagonist_4",
    "tribe_5",
    "protagonist_5",
    "tribe_6",
    "event_lens",
]

SCHEDULED_AGENT_SCENARIOS = frozenset({"enterprise_earth", "tribe_survival"})


@dataclass(slots=True)
class AgentJob:
    id: str
    kind: str
    provider: AgentProvider
    graph_key: str = ""
    priority: int = 0
    slot: str = "any"
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "kind": self.kind,
            "provider": self.provider.name,
            "graph_key": self.graph_key,
            "priority": self.priority,
            "slot": self.slot,
            "metadata": json_copy(self.metadata),
        }


@dataclass(slots=True)
class AgentSchedulerConfig:
    enabled: bool = False
    dispatch_mode: str = "wheel"
    max_concurrent: int = 2
    max_starts_per_tick: int = 0
    lane_limits: dict[str, int] = field(default_factory=dict)
    epoch_relationship_limit: int = 10
    epoch_protagonist_limit: int = 5
    epoch_start_limit: int = 15
    epoch_soft_deadline_seconds: float = 18.0
    epoch_prefetch_seconds: float = 60.0
    daily_budget: int = 0
    dispatch_slots: list[str] = field(
        default_factory=lambda: list(AI_ISEKAI_DISPATCH_SLOTS)
    )
    event_triggered_lenses: bool = False
    max_triggered_lenses_per_tick: int = 2
    trigger_feedback_limit: int = 32
    pressure_triggered_jobs: bool = False
    max_pressure_triggered_jobs_per_tick: int = 2
    pressure_trigger_threshold: float = 1.0
    max_transport_attempts: int = 0
    max_prompt_tokens: int = 0
    max_completion_tokens: int = 0
    max_estimated_cost: float = 0.0

    @classmethod
    def from_dict(cls, value: JsonDict) -> "AgentSchedulerConfig":
        """Decode every persisted scheduler field through one versioned boundary."""

        dispatch_mode = str(value.get("dispatch_mode", "wheel") or "wheel")
        if dispatch_mode not in {"wheel", "cognition_epoch"}:
            raise ValueError(f"unsupported scheduler dispatch_mode: {dispatch_mode}")

        def integer(name: str, default: int) -> int:
            raw = value.get(name, default)
            return int(default if raw is None else raw)

        def number(name: str, default: float) -> float:
            raw = value.get(name, default)
            return float(default if raw is None else raw)

        config = cls(
            enabled=bool(value.get("enabled", False)),
            dispatch_mode=dispatch_mode,
            max_concurrent=integer("max_concurrent", 2),
            max_starts_per_tick=integer("max_starts_per_tick", 0),
            lane_limits={
                str(key): int(item or 0)
                for key, item in _dict(value.get("lane_limits")).items()
            },
            epoch_relationship_limit=integer("epoch_relationship_limit", 10),
            epoch_protagonist_limit=integer("epoch_protagonist_limit", 5),
            epoch_start_limit=integer("epoch_start_limit", 15),
            epoch_soft_deadline_seconds=number("epoch_soft_deadline_seconds", 18.0),
            epoch_prefetch_seconds=number("epoch_prefetch_seconds", 60.0),
            daily_budget=integer("daily_budget", 0),
            dispatch_slots=[str(item) for item in value.get("dispatch_slots", [])]
            if isinstance(value.get("dispatch_slots"), list)
            else list(AI_ISEKAI_DISPATCH_SLOTS),
            event_triggered_lenses=bool(value.get("event_triggered_lenses", False)),
            max_triggered_lenses_per_tick=integer("max_triggered_lenses_per_tick", 2),
            trigger_feedback_limit=integer("trigger_feedback_limit", 32),
            pressure_triggered_jobs=bool(value.get("pressure_triggered_jobs", False)),
            max_pressure_triggered_jobs_per_tick=integer(
                "max_pressure_triggered_jobs_per_tick", 2
            ),
            pressure_trigger_threshold=number("pressure_trigger_threshold", 1.0),
            max_transport_attempts=integer("max_transport_attempts", 0),
            max_prompt_tokens=integer("max_prompt_tokens", 0),
            max_completion_tokens=integer("max_completion_tokens", 0),
            max_estimated_cost=number("max_estimated_cost", 0.0),
        )
        if not config.dispatch_slots:
            config.dispatch_slots = list(AI_ISEKAI_DISPATCH_SLOTS)
        if config.max_concurrent < 0:
            raise ValueError("scheduler max_concurrent cannot be negative")
        if config.dispatch_mode == "cognition_epoch":
            if (
                min(
                    config.epoch_relationship_limit,
                    config.epoch_protagonist_limit,
                    config.epoch_start_limit,
                )
                < 0
            ):
                raise ValueError("cognition-epoch limits cannot be negative")
            required = config.epoch_relationship_limit + config.epoch_protagonist_limit
            if config.epoch_start_limit < required:
                raise ValueError(
                    "epoch_start_limit must cover relationship plus protagonist jobs"
                )
        return config

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": 1,
            "enabled": self.enabled,
            "dispatch_mode": self.dispatch_mode,
            "max_concurrent": self.max_concurrent,
            "max_starts_per_tick": self.max_starts_per_tick,
            "lane_limits": json_copy(self.lane_limits),
            "epoch_relationship_limit": self.epoch_relationship_limit,
            "epoch_protagonist_limit": self.epoch_protagonist_limit,
            "epoch_start_limit": self.epoch_start_limit,
            "epoch_soft_deadline_seconds": self.epoch_soft_deadline_seconds,
            "epoch_prefetch_seconds": self.epoch_prefetch_seconds,
            "daily_budget": self.daily_budget,
            "dispatch_slots": list(self.dispatch_slots),
            "event_triggered_lenses": self.event_triggered_lenses,
            "max_triggered_lenses_per_tick": self.max_triggered_lenses_per_tick,
            "trigger_feedback_limit": self.trigger_feedback_limit,
            "pressure_triggered_jobs": self.pressure_triggered_jobs,
            "max_pressure_triggered_jobs_per_tick": self.max_pressure_triggered_jobs_per_tick,
            "pressure_trigger_threshold": self.pressure_trigger_threshold,
            "max_transport_attempts": self.max_transport_attempts,
            "max_prompt_tokens": self.max_prompt_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "max_estimated_cost": self.max_estimated_cost,
        }


@dataclass(slots=True)
class PendingProviderJob:
    job: AgentJob
    slot: str
    source_tick: int
    context_packet: JsonDict
    context_params: JsonDict
    context_fingerprint: str
    started_at: float
    future: Future[ProviderOutput]
    eligible_since_tick: int = 0
    missed_slot_count: int = 0
    epoch_id: str = ""
    epoch_order: int = -1
    epoch_generation: int = 0
    epoch_snapshot_hash: str = ""
    control_revision: int = 0
    request_id: str = ""
    transport_attempt: int = 1


def default_agent_scheduler_config(scenario: str, ticks: int) -> AgentSchedulerConfig:
    """Default cognition-epoch scheduler for a supported authoritative scenario."""

    scenario_id = str(scenario)
    scheduled = scenario_id in SCHEDULED_AGENT_SCENARIOS
    enterprise_content = scenario_id == "enterprise_earth"
    relationship_limit = 11 if scenario_id == "tribe_survival" else 10
    protagonist_limit = 5
    core_start_limit = relationship_limit + protagonist_limit
    return AgentSchedulerConfig(
        enabled=True,
        dispatch_mode="cognition_epoch" if scheduled else "wheel",
        max_concurrent=core_start_limit if scheduled else 2,
        max_starts_per_tick=1,
        lane_limits=(
            {
                "relationship": relationship_limit,
                "protagonist": protagonist_limit,
                "auxiliary": 1,
            }
            if scheduled
            else {"relationship": 1, "protagonist": 1}
        ),
        epoch_relationship_limit=relationship_limit,
        epoch_protagonist_limit=protagonist_limit,
        epoch_start_limit=core_start_limit,
        epoch_prefetch_seconds=60.0,
        daily_budget=(
            max(int(ticks), core_start_limit)
            if scheduled
            else max(int(ticks), len(AI_ISEKAI_DISPATCH_SLOTS))
        ),
        dispatch_slots=list(AI_ISEKAI_DISPATCH_SLOTS),
        event_triggered_lenses=enterprise_content,
        max_triggered_lenses_per_tick=2,
        pressure_triggered_jobs=enterprise_content,
        max_pressure_triggered_jobs_per_tick=2,
        pressure_trigger_threshold=1.0,
    )


def default_enterprise_scheduler_config(ticks: int) -> AgentSchedulerConfig:
    """Compatibility wrapper for the Enterprise Earth scheduler configuration."""

    return default_agent_scheduler_config("enterprise_earth", ticks)


class AgentScheduler:
    def __init__(self, config: AgentSchedulerConfig | None = None) -> None:
        self.config = config or AgentSchedulerConfig()
        self.context_builder = AgentContextPacketBuilder()
        self.queue: list[AgentJob] = []
        self.started_count = 0
        self.dispatched_job_ids: list[str] = []
        self.last_slot = ""
        self._executor: ThreadPoolExecutor | None = None
        self.pending_provider_jobs: dict[str, PendingProviderJob] = {}
        self.completed_provider_jobs: list[JsonDict] = []
        self.eligible_since_tick: dict[str, int] = {}
        self.released_slot_by_job: dict[str, str] = {}
        self.missed_slot_count: dict[str, int] = {}
        self.active_epoch: JsonDict = {}
        self._active_epoch_snapshot: JsonDict | None = None
        self._next_epoch_sequence = 1
        self._epoch_authoritative_buffer: dict[
            str, list[tuple[int, ProviderOutput]]
        ] = {}
        self._epoch_relationship_cognition_buffer: dict[
            str, list[tuple[int, ProviderOutput]]
        ] = {}
        self._released_presentation_epoch_ids: set[str] = set()
        self._released_epoch_ids: set[str] = set()
        self._epoch_templates: dict[str, AgentJob] = {}
        self.lifecycle_state = "accepting"
        self.lifecycle_reason = ""
        self.control_revision = 0
        self._drain_deadline_at: float | None = None
        self._cancellation = CancellationToken()
        self._attempt_budget = ProviderAttemptBudget(
            self.config.max_transport_attempts,
            max_prompt_tokens=self.config.max_prompt_tokens,
            max_completion_tokens=self.config.max_completion_tokens,
            max_estimated_cost=self.config.max_estimated_cost,
        )
        self._accepted_generation_ids: set[str] = set()

    def enqueue(self, job: AgentJob) -> bool:
        if self.lifecycle_state != "accepting":
            return False
        if job.id in self.dispatched_job_ids or any(
            existing.id == job.id for existing in self.queue
        ):
            return False
        self.queue.append(job)
        self.queue.sort(key=lambda item: (-item.priority, item.id))
        if (
            self.config.dispatch_mode == "cognition_epoch"
            and _job_lane(job) in {"relationship", "protagonist"}
            and not job.metadata.get("epoch_template_id")
        ):
            self._epoch_templates.setdefault(
                job.id,
                AgentJob(
                    id=job.id,
                    kind=job.kind,
                    provider=job.provider,
                    graph_key=job.graph_key,
                    priority=job.priority,
                    slot=job.slot,
                    metadata=json_copy(job.metadata),
                ),
            )
        return True

    def enqueue_many(self, jobs: list[AgentJob]) -> int:
        return sum(1 for job in jobs if self.enqueue(job))

    def dispatch_tick(
        self, world: World, tick: int, params: JsonDict | None = None
    ) -> list[ProviderOutput]:
        slot = self.current_slot(tick)
        self.last_slot = slot
        outputs = self._collect_pending(world)
        if self.lifecycle_state != "accepting":
            self._advance_lifecycle_after_collect()
            return outputs
        epoch_launch = self._release_cognition_epoch_jobs(world, tick)
        if not epoch_launch:
            self._release_slot_job(slot, tick)
        self._release_any_jobs(tick)
        runnable = self._eligible_jobs(tick)
        start_limit = self._start_limit(epoch_launch=epoch_launch)
        started_this_tick = 0
        for job in runnable:
            if started_this_tick >= start_limit:
                break
            if self._budget_exhausted():
                break
            if not self._can_dispatch_lane(job):
                self.missed_slot_count[job.id] = (
                    self.missed_slot_count.get(job.id, 0) + 1
                )
                continue
            self.queue.remove(job)
            eligible_since_tick = self.eligible_since_tick.pop(job.id, tick)
            released_slot = self.released_slot_by_job.pop(job.id, slot)
            missed_slots = self.missed_slot_count.pop(job.id, 0)
            context_world = world
            epoch_data = _dict(job.metadata.get("cognition_epoch"))
            if epoch_data and self._active_epoch_snapshot is not None:
                context_world = World.from_snapshot(self._active_epoch_snapshot)
            context_packet = self.context_builder.build(context_world, job)
            context_params = json_copy(params or {})
            enabled_rule_names = (
                [str(value) for value in context_params.get("enabled_rule_names", [])]
                if isinstance(context_params.get("enabled_rule_names"), list)
                else []
            )
            active_node_ids = [
                str(item.get("id", ""))
                for item in context_packet.get("active_candidates", [])
                if isinstance(item, dict) and str(item.get("id", ""))
            ]
            context_packet["groundable_action_options"] = groundable_action_options(
                context_world,
                active_node_ids,
                enabled_rule_names,
            )
            context_params["agent_context_packet"] = json_copy(context_packet)
            if epoch_data:
                context_params["cognition_epoch"] = json_copy(epoch_data)
            request_id = _provider_request_id(job, epoch_data, tick)
            context_params["provider_request_id"] = request_id
            context_params["provider_transport_attempt"] = 1
            context = ProviderContext(
                world=context_world,
                tick=int(epoch_data.get("source_tick", tick) or tick),
                snapshot=context_world.snapshot(),
                params=context_params,
                cancellation=self._cancellation,
                attempt_budget=self._attempt_budget,
            )
            self.started_count += 1
            started_this_tick += 1
            self.dispatched_job_ids.append(job.id)
            if bool(getattr(job.provider, "network_backed", False)):
                isolated_world = World.from_snapshot(context.snapshot)
                isolated_context = ProviderContext(
                    world=isolated_world,
                    tick=tick,
                    snapshot=isolated_world.snapshot(),
                    params=context_params,
                    cancellation=self._cancellation,
                    attempt_budget=self._attempt_budget,
                )
                executor = self._provider_executor()
                self.pending_provider_jobs[job.id] = PendingProviderJob(
                    job=job,
                    slot=released_slot,
                    source_tick=tick,
                    context_packet=json_copy(context_packet),
                    context_params=json_copy(context_params),
                    context_fingerprint=_context_fingerprint(world, context_packet),
                    started_at=perf_counter(),
                    future=executor.submit(job.provider.observe, isolated_context),
                    eligible_since_tick=eligible_since_tick,
                    missed_slot_count=missed_slots,
                    epoch_id=str(epoch_data.get("epoch_id", "")),
                    epoch_order=int(epoch_data.get("order", -1)),
                    epoch_generation=int(epoch_data.get("generation", 0) or 0),
                    epoch_snapshot_hash=str(epoch_data.get("snapshot_hash", "")),
                    control_revision=self.control_revision,
                    request_id=request_id,
                )
                continue
            completed_output = self._with_scheduler_metadata(
                job.provider.observe(context),
                job,
                released_slot,
                context_packet,
                eligible_since_tick=eligible_since_tick,
                dispatched_tick=tick,
                missed_slots=missed_slots,
            )
            if epoch_data:
                if job.kind == "relationship_round":
                    schedules = [
                        item
                        for item in completed_output.effects
                        if item.type == "thought_schedule_add"
                    ]
                    if schedules:
                        outputs.extend(
                            self._route_epoch_cognition(
                                job,
                                int(epoch_data.get("order", -1)),
                                ProviderOutput(
                                    source=completed_output.source,
                                    summary=completed_output.summary,
                                    effects=schedules,
                                    metadata=json_copy(completed_output.metadata),
                                ),
                            )
                        )
                        completed_output = ProviderOutput(
                            source=completed_output.source,
                            summary=completed_output.summary,
                            effects=[
                                item
                                for item in completed_output.effects
                                if item.type != "thought_schedule_add"
                            ],
                            metadata=json_copy(completed_output.metadata),
                        )
                outputs.append(completed_output)
            else:
                outputs.append(completed_output)
        outputs.extend(self._release_epoch_relationship_cognition())
        outputs.extend(self._release_epoch_authoritative_outputs())
        return outputs

    @property
    def has_pending_provider_jobs(self) -> bool:
        return bool(self.pending_provider_jobs)

    @property
    def accepting_jobs(self) -> bool:
        return self.lifecycle_state == "accepting"

    @property
    def drained(self) -> bool:
        return self.lifecycle_state in {"drained", "canceled", "closed"}

    def stop_accepting(self, reason: str = "scheduler stop requested") -> None:
        if self.lifecycle_state != "accepting":
            return
        self.lifecycle_state = "quiescing"
        self.lifecycle_reason = str(reason)

    def begin_drain(
        self,
        deadline_seconds: float = 5.0,
        reason: str = "scheduler drain requested",
    ) -> None:
        if self.lifecycle_state in {"canceled", "closed"}:
            return
        self.stop_accepting(reason)
        self.lifecycle_state = "draining"
        self.lifecycle_reason = str(reason)
        self._drain_deadline_at = perf_counter() + max(float(deadline_seconds), 0.0)
        self._advance_lifecycle_after_collect()

    def resume_accepting(self) -> None:
        """Resume a fully drained scheduler after a recoverable Worker stop."""

        if self.lifecycle_state not in {"quiescing", "draining", "drained"}:
            return
        if self.pending_provider_jobs:
            raise RuntimeError(
                "cannot resume scheduler while provider jobs are pending"
            )
        self.lifecycle_state = "accepting"
        self.lifecycle_reason = ""
        self._drain_deadline_at = None

    def cancel_pending(self, reason: str = "scheduler canceled") -> None:
        if self.lifecycle_state in {"canceled", "closed"}:
            return
        self.lifecycle_state = "canceling"
        self.lifecycle_reason = str(reason)
        self.control_revision += 1
        self._cancellation.cancel(reason)
        self.queue.clear()
        self.eligible_since_tick.clear()
        self.released_slot_by_job.clear()
        self.missed_slot_count.clear()
        for pending in self.pending_provider_jobs.values():
            pending.future.cancel()
        self._advance_lifecycle_after_collect()

    def lifecycle_step(self, world: World) -> list[ProviderOutput]:
        outputs = self._collect_pending(world)
        if (
            self.lifecycle_state == "draining"
            and self._drain_deadline_at is not None
            and perf_counter() >= self._drain_deadline_at
            and self.pending_provider_jobs
        ):
            self.cancel_pending("scheduler drain deadline exceeded")
        self._advance_lifecycle_after_collect()
        return outputs

    def close(self, reason: str = "scheduler closed") -> None:
        if self.lifecycle_state == "closed":
            return
        if self.pending_provider_jobs:
            self.cancel_pending(reason)
        for job_id, pending in list(self.pending_provider_jobs.items()):
            self.completed_provider_jobs.append(
                {
                    "job_id": job_id,
                    "status": "abandoned_on_close",
                    "source_tick": pending.source_tick,
                    "request_id": pending.request_id,
                    "possible_external_completion": not pending.future.cancelled(),
                }
            )
        self.pending_provider_jobs.clear()
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        self.lifecycle_state = "closed"
        self.lifecycle_reason = str(reason)

    def _advance_lifecycle_after_collect(self) -> None:
        if self.pending_provider_jobs:
            return
        if self.lifecycle_state in {"quiescing", "draining"}:
            self.lifecycle_state = "drained"
        elif self.lifecycle_state == "canceling":
            self.lifecycle_state = "canceled"

    def wait_for_pending(self, timeout: float = 0.01) -> None:
        futures = [pending.future for pending in self.pending_provider_jobs.values()]
        if not futures:
            return
        wait(futures, timeout=max(float(timeout), 0.0))

    def collect_pending(self, world: World) -> list[ProviderOutput]:
        return self._collect_pending(world)

    def checkpoint_state(self) -> JsonDict:
        now = perf_counter()
        epoch_started_at = float(self.active_epoch.get("started_at", now) or now)
        request_contexts: JsonDict = {}
        pending_rows: list[JsonDict] = []
        for pending in self.pending_provider_jobs.values():
            request_id = (
                pending.request_id or f"pending:{pending.job.id}:{pending.source_tick}"
            )
            context_body = {
                "context_packet": json_copy(pending.context_packet),
                "context_params": {
                    key: json_copy(value)
                    for key, value in pending.context_params.items()
                    if key != "agent_context_packet"
                },
            }
            integrity_hash = _json_fingerprint(context_body)
            request_contexts[request_id] = {
                **context_body,
                "integrity_hash": integrity_hash,
            }
            pending_rows.append(
                {
                    "job_id": pending.job.id,
                    "slot": pending.slot,
                    "source_tick": pending.source_tick,
                    "job": pending.job.to_dict(),
                    "context_ref": request_id,
                    "context_integrity_hash": integrity_hash,
                    "context_fingerprint": pending.context_fingerprint,
                    "eligible_since_tick": pending.eligible_since_tick,
                    "missed_slot_count": pending.missed_slot_count,
                    "epoch_id": pending.epoch_id,
                    "epoch_order": pending.epoch_order,
                    "epoch_generation": pending.epoch_generation,
                    "epoch_snapshot_hash": pending.epoch_snapshot_hash,
                    "control_revision": pending.control_revision,
                    "request_id": pending.request_id,
                    "transport_attempt": pending.transport_attempt,
                }
            )
        return {
            "schema_version": 2,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_reason": self.lifecycle_reason,
            "control_revision": self.control_revision,
            "drain_remaining_seconds": (
                max(self._drain_deadline_at - now, 0.0)
                if self._drain_deadline_at is not None
                else None
            ),
            "started_count": self.started_count,
            "transport_attempt_budget": self._attempt_budget.snapshot(),
            "dispatched_job_ids": list(self.dispatched_job_ids),
            "queued_job_ids": [job.id for job in self.queue],
            "queued_jobs": [job.to_dict() for job in self.queue],
            "last_slot": self.last_slot,
            "active_epoch": json_copy(self.active_epoch),
            "active_epoch_snapshot": json_copy(self._active_epoch_snapshot or {}),
            "active_epoch_elapsed_seconds": max(now - epoch_started_at, 0.0),
            "next_epoch_sequence": self._next_epoch_sequence,
            "epoch_templates": [
                job.to_dict() for _, job in sorted(self._epoch_templates.items())
            ],
            "epoch_authoritative_buffer": {
                epoch_id: [
                    {"order": order, "output": output.to_dict()}
                    for order, output in buffered
                ]
                for epoch_id, buffered in self._epoch_authoritative_buffer.items()
            },
            "epoch_relationship_cognition_buffer": {
                epoch_id: [
                    {"order": order, "output": output.to_dict()}
                    for order, output in buffered
                ]
                for epoch_id, buffered in self._epoch_relationship_cognition_buffer.items()
            },
            "released_presentation_epoch_ids": sorted(
                self._released_presentation_epoch_ids
            ),
            "released_epoch_ids": sorted(self._released_epoch_ids),
            "accepted_generation_ids": sorted(self._accepted_generation_ids),
            "completed_provider_jobs": json_copy(self.completed_provider_jobs),
            "eligible_jobs": [
                {
                    "job_id": job_id,
                    "eligible_since_tick": eligible_tick,
                    "released_slot": self.released_slot_by_job.get(job_id, ""),
                    "missed_slot_count": self.missed_slot_count.get(job_id, 0),
                }
                for job_id, eligible_tick in sorted(self.eligible_since_tick.items())
            ],
            "request_contexts": request_contexts,
            "pending_provider_jobs": pending_rows,
        }

    def restore_state(self, world: World, state: JsonDict) -> None:
        base_jobs = {job.id: job for job in self.queue}
        queued_specs = [
            item for item in state.get("queued_jobs", []) if isinstance(item, dict)
        ]
        if queued_specs:
            self.queue = [
                job
                for item in queued_specs
                if (job := _restore_job_spec(item, base_jobs)) is not None
            ]
        else:
            queued_ids = {str(value) for value in state.get("queued_job_ids", [])}
            self.queue = [job for job in self.queue if job.id in queued_ids]
        jobs_by_id = {**base_jobs, **{job.id: job for job in self.queue}}
        restored_templates: dict[str, AgentJob] = {}
        for item in state.get("epoch_templates", []):
            if not isinstance(item, dict):
                continue
            template = _restore_job_spec(item, base_jobs)
            if template is not None:
                restored_templates[template.id] = template
        if restored_templates:
            self._epoch_templates = restored_templates
        self.started_count = int(state.get("started_count", 0) or 0)
        self.dispatched_job_ids = [
            str(value) for value in state.get("dispatched_job_ids", [])
        ]
        self.last_slot = str(state.get("last_slot", ""))
        self.active_epoch = json_copy(state.get("active_epoch", {}))
        if self.active_epoch:
            elapsed = max(
                float(state.get("active_epoch_elapsed_seconds", 0.0) or 0.0),
                0.0,
            )
            self.active_epoch["started_at"] = perf_counter() - elapsed
        self._next_epoch_sequence = max(
            int(state.get("next_epoch_sequence", 1) or 1), 1
        )
        active_snapshot = state.get("active_epoch_snapshot")
        self._active_epoch_snapshot = (
            json_copy(active_snapshot)
            if isinstance(active_snapshot, dict) and active_snapshot
            else None
        )
        self.lifecycle_state = str(
            state.get("lifecycle_state", "accepting") or "accepting"
        )
        if self.lifecycle_state not in {
            "accepting",
            "quiescing",
            "draining",
            "drained",
            "canceling",
            "canceled",
            "closed",
        }:
            self.lifecycle_state = "accepting"
        self.lifecycle_reason = str(state.get("lifecycle_reason", ""))
        self.control_revision = int(state.get("control_revision", 0) or 0)
        remaining = state.get("drain_remaining_seconds")
        self._drain_deadline_at = (
            perf_counter() + max(float(remaining), 0.0)
            if isinstance(remaining, (int, float))
            else None
        )
        self._cancellation = CancellationToken()
        budget_state = _dict(state.get("transport_attempt_budget"))
        self._attempt_budget = ProviderAttemptBudget(
            limit=self.config.max_transport_attempts,
            used=int(budget_state.get("used", 0) or 0),
            max_prompt_tokens=self.config.max_prompt_tokens,
            max_completion_tokens=self.config.max_completion_tokens,
            max_estimated_cost=self.config.max_estimated_cost,
            prompt_tokens=int(budget_state.get("prompt_tokens", 0) or 0),
            completion_tokens=int(budget_state.get("completion_tokens", 0) or 0),
            estimated_cost=float(budget_state.get("estimated_cost", 0.0) or 0.0),
        )
        if self.lifecycle_state in {"canceling", "canceled", "closed"}:
            self._cancellation.cancel(
                self.lifecycle_reason or "restored canceled scheduler"
            )
        self._released_epoch_ids = {
            str(item) for item in state.get("released_epoch_ids", [])
        }
        self._accepted_generation_ids = {
            str(item) for item in state.get("accepted_generation_ids", [])
        }
        self._epoch_authoritative_buffer = {}
        raw_buffer = state.get("epoch_authoritative_buffer", {})
        if isinstance(raw_buffer, dict):
            for epoch_id, rows in raw_buffer.items():
                restored_rows: list[tuple[int, ProviderOutput]] = []
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    output = _provider_output_from_dict(row.get("output"))
                    if output is not None:
                        restored_rows.append((int(row.get("order", -1)), output))
                if restored_rows:
                    self._epoch_authoritative_buffer[str(epoch_id)] = restored_rows
        self._epoch_relationship_cognition_buffer = {}
        raw_cognition_buffer = state.get("epoch_relationship_cognition_buffer", {})
        if isinstance(raw_cognition_buffer, dict):
            for epoch_id, rows in raw_cognition_buffer.items():
                restored_rows = []
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    output = _provider_output_from_dict(row.get("output"))
                    if output is not None:
                        restored_rows.append((int(row.get("order", -1)), output))
                if restored_rows:
                    self._epoch_relationship_cognition_buffer[str(epoch_id)] = (
                        restored_rows
                    )
        self._released_presentation_epoch_ids = {
            str(item) for item in state.get("released_presentation_epoch_ids", [])
        }
        self.completed_provider_jobs = json_copy(
            state.get("completed_provider_jobs", [])
        )
        self.eligible_since_tick = {}
        self.released_slot_by_job = {}
        self.missed_slot_count = {}
        for item in state.get("eligible_jobs", []):
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id", ""))
            if not job_id or not any(job.id == job_id for job in self.queue):
                continue
            self.eligible_since_tick[job_id] = int(
                item.get("eligible_since_tick", world.tick) or world.tick
            )
            self.released_slot_by_job[job_id] = str(item.get("released_slot", ""))
            self.missed_slot_count[job_id] = int(item.get("missed_slot_count", 0) or 0)
        aborted_epoch_on_restore = False
        request_contexts = _dict(state.get("request_contexts"))
        for item in state.get("pending_provider_jobs", []):
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id", ""))
            job_spec = item.get("job")
            job = jobs_by_id.get(job_id)
            if job is None and isinstance(job_spec, dict):
                job = _restore_job_spec(job_spec, base_jobs)
            context_ref = str(item.get("context_ref", ""))
            context_record = _dict(request_contexts.get(context_ref))
            context_body = {
                "context_packet": context_record.get("context_packet"),
                "context_params": context_record.get("context_params"),
            }
            if context_record and str(
                item.get("context_integrity_hash", "")
            ) != _json_fingerprint(context_body):
                context_record = {}
            context_packet = context_record.get(
                "context_packet", item.get("context_packet")
            )
            if job is None or not isinstance(context_packet, dict):
                self.completed_provider_jobs.append(
                    {"job_id": job_id, "status": "expired_on_restore"}
                )
                continue
            epoch_id = str(item.get("epoch_id", ""))
            generation_id = _generation_id(
                epoch_id,
                job_id,
                int(item.get("epoch_generation", 0) or 0),
            )
            if generation_id in self._accepted_generation_ids:
                self.completed_provider_jobs.append(
                    {"job_id": job_id, "status": "accepted_before_restore"}
                )
                continue
            if self.lifecycle_state in {"canceling", "canceled", "closed"}:
                self.completed_provider_jobs.append(
                    {"job_id": job_id, "status": "abandoned_terminal_restore"}
                )
                continue
            if epoch_id and self._active_epoch_snapshot is None:
                self.completed_provider_jobs.append(
                    {"job_id": job_id, "status": "epoch_aborted_on_restore"}
                )
                aborted_epoch_on_restore = True
                continue
            self.queue = [queued for queued in self.queue if queued.id != job_id]
            source_snapshot = self._active_epoch_snapshot or world.snapshot()
            isolated_world = World.from_snapshot(source_snapshot)
            context_params = (
                json_copy(
                    context_record.get("context_params", item.get("context_params"))
                )
                if isinstance(
                    context_record.get("context_params", item.get("context_params")),
                    dict,
                )
                else {"agent_context_packet": json_copy(context_packet)}
            )
            context_params["agent_context_packet"] = json_copy(context_packet)
            transport_attempt = max(
                int(item.get("transport_attempt", 1) or 1) + 1,
                2,
            )
            context_params["provider_transport_attempt"] = transport_attempt
            context_params["possible_duplicate_transport"] = True
            request_id = str(item.get("request_id", "")) or _provider_request_id(
                job,
                _dict(job.metadata.get("cognition_epoch")),
                int(item.get("source_tick", world.tick) or world.tick),
            )
            context_params["provider_request_id"] = request_id
            context = ProviderContext(
                world=isolated_world,
                tick=int(item.get("source_tick", world.tick) or world.tick),
                snapshot=isolated_world.snapshot(),
                params=context_params,
                cancellation=self._cancellation,
                attempt_budget=self._attempt_budget,
            )
            self.pending_provider_jobs[job_id] = PendingProviderJob(
                job=job,
                slot=str(item.get("slot", job.slot)),
                source_tick=int(item.get("source_tick", world.tick) or world.tick),
                context_packet=json_copy(context_packet),
                context_params=json_copy(context_params),
                context_fingerprint=str(item.get("context_fingerprint", ""))
                or _context_fingerprint(world, context_packet),
                started_at=perf_counter(),
                future=self._provider_executor().submit(job.provider.observe, context),
                eligible_since_tick=int(
                    item.get("eligible_since_tick", world.tick) or world.tick
                ),
                missed_slot_count=int(item.get("missed_slot_count", 0) or 0),
                epoch_id=epoch_id,
                epoch_order=int(item.get("epoch_order", -1)),
                epoch_generation=int(item.get("epoch_generation", 0) or 0),
                epoch_snapshot_hash=str(item.get("epoch_snapshot_hash", "")),
                control_revision=int(
                    item.get("control_revision", self.control_revision)
                    or self.control_revision
                ),
                request_id=request_id,
                transport_attempt=transport_attempt,
            )
        if aborted_epoch_on_restore:
            aborted_epoch_id = str(self.active_epoch.get("epoch_id", ""))
            if aborted_epoch_id:
                self._epoch_authoritative_buffer.pop(aborted_epoch_id, None)
            self.active_epoch = {}
            self._active_epoch_snapshot = None
            if self.lifecycle_state == "accepting":
                self._enqueue_next_epoch_generation()
        self._advance_lifecycle_after_collect()

    def current_slot(self, tick: int) -> str:
        slots = self.config.dispatch_slots or list(AI_ISEKAI_DISPATCH_SLOTS)
        return slots[int(tick) % len(slots)]

    def status_snapshot(self) -> JsonDict:
        now = perf_counter()
        return {
            "enabled": self.config.enabled,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_reason": self.lifecycle_reason,
            "control_revision": self.control_revision,
            "accepting_jobs": self.accepting_jobs,
            "drain_remaining_seconds": (
                round(max(self._drain_deadline_at - now, 0.0), 3)
                if self._drain_deadline_at is not None
                else None
            ),
            "dispatch_mode": self.config.dispatch_mode,
            "max_concurrent": self.config.max_concurrent,
            "max_starts_per_tick": self.config.max_starts_per_tick,
            "lane_limits": json_copy(self.config.lane_limits),
            "daily_budget": self.config.daily_budget,
            "max_transport_attempts": self.config.max_transport_attempts,
            "transport_attempt_budget": self._attempt_budget.snapshot(),
            "started_count": self.started_count,
            "remaining_budget": self.remaining_budget(),
            "queue_length": len(self.queue),
            "last_slot": self.last_slot,
            "dispatch_slots": list(self.config.dispatch_slots),
            "active_epoch": json_copy(self.active_epoch),
            "dispatched_job_ids": list(self.dispatched_job_ids),
            "queued_jobs": [job.to_dict() for job in self.queue],
            "eligible_jobs": [
                {
                    "job_id": job.id,
                    "job_kind": job.kind,
                    "lane": _job_lane(job),
                    "eligible_since_tick": self.eligible_since_tick[job.id],
                    "released_slot": self.released_slot_by_job.get(job.id, ""),
                    "missed_slot_count": self.missed_slot_count.get(job.id, 0),
                }
                for job in self.queue
                if job.id in self.eligible_since_tick
            ],
            "provider_pending_count": len(self.pending_provider_jobs),
            "provider_pending": [
                {
                    "job_id": pending.job.id,
                    "job_kind": pending.job.kind,
                    "graph_key": pending.job.graph_key,
                    "source_tick": pending.source_tick,
                    "status": "provider_pending",
                    "elapsed_ms": round((now - pending.started_at) * 1000, 3),
                    "epoch_id": pending.epoch_id,
                    "epoch_order": pending.epoch_order,
                }
                for pending in self.pending_provider_jobs.values()
            ],
            "provider_completed": json_copy(self.completed_provider_jobs[-12:]),
        }

    def remaining_budget(self) -> int | None:
        if self.config.daily_budget <= 0:
            return None
        return max(self.config.daily_budget - self.started_count, 0)

    def _release_slot_job(self, slot: str, tick: int) -> None:
        waiting = [
            job
            for job in self.queue
            if job.id not in self.eligible_since_tick
            and job.slot != "any"
            and (job.slot == slot or _slot_matches(slot, job))
        ]
        if not waiting:
            return
        waiting.sort(key=lambda job: (-job.priority, job.id))
        released = waiting[0]
        self.eligible_since_tick[released.id] = int(tick)
        self.released_slot_by_job[released.id] = slot

    def _release_any_jobs(self, tick: int) -> None:
        for job in self.queue:
            if job.slot == "any" and job.id not in self.eligible_since_tick:
                self.eligible_since_tick[job.id] = int(tick)
                self.released_slot_by_job[job.id] = "any"

    def _eligible_jobs(self, tick: int) -> list[AgentJob]:
        eligible = [job for job in self.queue if job.id in self.eligible_since_tick]
        eligible.sort(
            key=lambda job: (
                0 if _dict(job.metadata.get("cognition_epoch")) else 1,
                int(_dict(job.metadata.get("cognition_epoch")).get("order", 0)),
                0 if _job_lane(job) in {"relationship", "protagonist"} else 1,
                self.eligible_since_tick.get(job.id, tick),
                -job.priority,
                job.id,
            )
        )
        return eligible

    def _start_limit(self, *, epoch_launch: bool = False) -> int:
        capacity = self._remaining_capacity()
        if epoch_launch:
            configured_epoch = max(int(self.config.epoch_start_limit), 0)
            return min(capacity, configured_epoch) if configured_epoch > 0 else capacity
        configured = int(self.config.max_starts_per_tick)
        return min(capacity, configured) if configured > 0 else capacity

    def _release_cognition_epoch_jobs(self, world: World, tick: int) -> bool:
        if self.config.dispatch_mode != "cognition_epoch":
            return False
        if self.active_epoch:
            started_at = float(
                self.active_epoch.get("started_at", perf_counter()) or perf_counter()
            )
            prefetch_due = perf_counter() - started_at >= max(
                float(self.config.epoch_prefetch_seconds), 0.0
            )
            pending_active_epoch = any(
                pending.epoch_id == str(self.active_epoch.get("epoch_id", ""))
                for pending in self.pending_provider_jobs.values()
            )
            if not prefetch_due or pending_active_epoch:
                return False
            self._enqueue_next_epoch_generation()
            self.active_epoch = {}
            self._active_epoch_snapshot = None
        relationship = [job for job in self.queue if _job_lane(job) == "relationship"]
        protagonist = [job for job in self.queue if _job_lane(job) == "protagonist"]
        relationship.sort(key=lambda job: (-job.priority, job.id))
        protagonist.sort(key=lambda job: (-job.priority, job.id))
        selected = [
            *relationship[: max(int(self.config.epoch_relationship_limit), 0)],
            *protagonist[: max(int(self.config.epoch_protagonist_limit), 0)],
        ]
        if not selected:
            return False
        epoch_id = f"cognition-epoch-{self._next_epoch_sequence}"
        generation = self._next_epoch_sequence
        self._next_epoch_sequence += 1
        snapshot = world.snapshot()
        snapshot_hash = _snapshot_hash(snapshot)
        self._active_epoch_snapshot = json_copy(snapshot)
        self.active_epoch = {
            "epoch_id": epoch_id,
            "generation": generation,
            "source_tick": int(tick),
            "snapshot_hash": snapshot_hash,
            "started_at": perf_counter(),
            "expected_job_ids": [job.id for job in selected],
            "relationship_count": min(
                len(relationship), max(int(self.config.epoch_relationship_limit), 0)
            ),
            "protagonist_count": min(
                len(protagonist), max(int(self.config.epoch_protagonist_limit), 0)
            ),
        }
        for order, job in enumerate(selected):
            job.metadata["cognition_epoch"] = {
                "epoch_id": epoch_id,
                "generation": generation,
                "source_tick": int(tick),
                "snapshot_hash": snapshot_hash,
                "order": order,
            }
            self.eligible_since_tick[job.id] = int(tick)
            self.released_slot_by_job[job.id] = "cognition_epoch"
        return True

    def _enqueue_next_epoch_generation(self) -> None:
        generation = self._next_epoch_sequence
        for template_id, template in sorted(self._epoch_templates.items()):
            metadata = json_copy(template.metadata)
            metadata.pop("cognition_epoch", None)
            metadata["epoch_template_id"] = template_id
            self.enqueue(
                AgentJob(
                    id=f"{template_id}::epoch-{generation}",
                    kind=template.kind,
                    provider=template.provider,
                    graph_key=template.graph_key,
                    priority=template.priority,
                    slot=template.slot,
                    metadata=metadata,
                )
            )

    def _can_dispatch_lane(self, job: AgentJob) -> bool:
        lane = _job_lane(job)
        active_by_lane: dict[str, int] = {}
        for pending in self.pending_provider_jobs.values():
            pending_lane = _job_lane(pending.job)
            active_by_lane[pending_lane] = active_by_lane.get(pending_lane, 0) + 1
        lane_limit = int(self.config.lane_limits.get(lane, 0) or 0)
        if lane_limit > 0 and active_by_lane.get(lane, 0) >= lane_limit:
            return False
        if lane == "auxiliary":
            for core_lane in ("relationship", "protagonist"):
                core_limit = int(self.config.lane_limits.get(core_lane, 0) or 0)
                if core_limit <= 0 or active_by_lane.get(core_lane, 0) >= core_limit:
                    continue
                if any(_job_lane(queued) == core_lane for queued in self.queue):
                    return False
        return self._remaining_capacity() > 0

    def _remaining_capacity(self) -> int:
        if self.config.max_concurrent <= 0:
            return 0
        remaining_budget = self.remaining_budget()
        if remaining_budget is None:
            return max(self.config.max_concurrent - len(self.pending_provider_jobs), 0)
        return min(
            max(self.config.max_concurrent - len(self.pending_provider_jobs), 0),
            remaining_budget,
        )

    def _budget_exhausted(self) -> bool:
        return (
            self.config.daily_budget > 0
            and self.started_count >= self.config.daily_budget
        )

    def _with_scheduler_metadata(
        self,
        output: ProviderOutput,
        job: AgentJob,
        slot: str,
        context_packet: JsonDict,
        *,
        eligible_since_tick: int | None = None,
        dispatched_tick: int | None = None,
        missed_slots: int = 0,
    ) -> ProviderOutput:
        metadata = json_copy(output.metadata)
        metadata["context_packet"] = self.context_builder.summary(context_packet)
        metadata["scheduler"] = {
            "job_id": job.id,
            "job_kind": job.kind,
            "graph_key": job.graph_key,
            "slot": slot,
            "job_slot": job.slot,
            "lane": _job_lane(job),
            "eligible_since_tick": eligible_since_tick,
            "dispatched_tick": dispatched_tick,
            "missed_slot_count": missed_slots,
            "job_metadata": json_copy(job.metadata),
            "started_count": self.started_count,
            "remaining_budget": self.remaining_budget(),
            "queue_length": len(self.queue),
        }
        epoch_data = _dict(job.metadata.get("cognition_epoch"))
        if epoch_data:
            metadata["scheduler"]["cognition_epoch"] = json_copy(epoch_data)
        metadata["provider_boundary"] = {
            **_dict(metadata.get("provider_output_boundary")),
            "replaceable_provider": True,
            "provider_name": job.provider.name,
            "context_schema": context_packet.get("schema", ""),
            "expected_output_style": "ai_isekai_node_edge_updates_key_character_pressure_or_structured_effects",
            "world_authority": "rule_engine_feedback",
        }
        return ProviderOutput(
            source=output.source,
            summary=output.summary,
            effects=output.effects,
            metadata=metadata,
        )

    def _provider_executor(self) -> ThreadPoolExecutor:
        if self.lifecycle_state == "closed":
            raise RuntimeError("scheduler is closed")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=max(int(self.config.max_concurrent), 1),
                thread_name_prefix="live-provider",
            )
        return self._executor

    def _collect_pending(self, world: World) -> list[ProviderOutput]:
        outputs: list[ProviderOutput] = []
        for job_id, pending in list(self.pending_provider_jobs.items()):
            if not pending.future.done():
                continue
            del self.pending_provider_jobs[job_id]
            elapsed_ms = round((perf_counter() - pending.started_at) * 1000, 3)
            try:
                output = pending.future.result()
                generation_id = _generation_id(
                    pending.epoch_id,
                    pending.job.id,
                    pending.epoch_generation,
                )
                if generation_id and generation_id in self._accepted_generation_ids:
                    status = "duplicate_generation"
                    output = ProviderOutput(
                        source=output.source,
                        summary=f"discarded duplicate generation {generation_id}",
                        metadata={
                            **json_copy(output.metadata),
                            "result_disposition": "duplicate_generation",
                        },
                    )
                elif (
                    pending.control_revision != self.control_revision
                    and self.lifecycle_state in {"canceling", "canceled", "closed"}
                ):
                    status = "discarded_after_cancel"
                    output = ProviderOutput(
                        source=output.source,
                        summary=f"discarded late canceled output for {pending.job.id}",
                        metadata={
                            **json_copy(output.metadata),
                            "result_disposition": "discarded_after_cancel",
                            "possible_external_completion": True,
                        },
                    )
                else:
                    if generation_id:
                        self._accepted_generation_ids.add(generation_id)
                    fresh = (
                        _context_fingerprint(world, pending.context_packet)
                        == pending.context_fingerprint
                    )
                    status = "completed" if fresh else "expired"
                    if not fresh:
                        retained_effects = _revalidate_stale_effects(
                            world, output.effects
                        )
                        if any(
                            item.type
                            not in {
                                "thought_bubble_add",
                                "thought_schedule_add",
                                "memory_add",
                            }
                            for item in retained_effects
                        ):
                            status = "revalidated"
                        output = ProviderOutput(
                            source=output.source,
                            summary=f"retained stale cognition for {pending.job.id}",
                            effects=retained_effects,
                            metadata=json_copy(output.metadata),
                        )
            except (CancelledError, ProviderCancelled) as exc:
                status = "canceled"
                output = ProviderOutput(
                    source=pending.job.provider.name,
                    summary=f"provider job canceled: {pending.job.id}",
                    metadata={
                        "provider_runtime": {
                            "provider": pending.job.provider.name,
                            "attempts": pending.transport_attempt,
                            "latency_ms": elapsed_ms,
                            "status": "canceled",
                        },
                        "provider_cancel": {
                            "reason": str(exc) or self.lifecycle_reason,
                            "possible_external_completion": not pending.future.cancelled(),
                        },
                    },
                )
            except Exception as exc:  # noqa: BLE001 - async failures become safe scheduler output.
                status = "failed"
                attempt_phases = getattr(exc, "provider_attempt_phases", [])
                if not isinstance(attempt_phases, list):
                    attempt_phases = []
                output = ProviderOutput(
                    source=pending.job.provider.name,
                    summary=f"provider job failed: {exc.__class__.__name__}",
                    metadata={
                        "provider_error": {
                            "type": exc.__class__.__name__,
                            "message": str(exc)[:240],
                        },
                        "provider_runtime": {
                            "provider": pending.job.provider.name,
                            "attempts": len(attempt_phases) or 1,
                            "latency_ms": elapsed_ms,
                            "attempt_phases": json_copy(attempt_phases),
                            "status": "failed",
                        },
                    },
                )
            metadata = json_copy(output.metadata)
            metadata["provider_pending"] = {
                "job_id": pending.job.id,
                "source_tick": pending.source_tick,
                "completed_tick": world.tick,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "context_fingerprint": pending.context_fingerprint,
                "epoch_id": pending.epoch_id,
                "epoch_order": pending.epoch_order,
                "epoch_generation": pending.epoch_generation,
                "epoch_snapshot_hash": pending.epoch_snapshot_hash,
                "request_id": pending.request_id,
                "transport_attempt": pending.transport_attempt,
                "control_revision": pending.control_revision,
                "scheduler_control_revision": self.control_revision,
            }
            output = ProviderOutput(
                source=output.source,
                summary=output.summary,
                effects=output.effects,
                metadata=metadata,
            )
            completed_output = self._with_scheduler_metadata(
                output,
                pending.job,
                pending.slot,
                pending.context_packet,
                eligible_since_tick=pending.eligible_since_tick,
                dispatched_tick=pending.source_tick,
                missed_slots=pending.missed_slot_count,
            )
            if pending.epoch_id:
                cognition, authoritative = _split_epoch_output(completed_output)
                outputs.extend(
                    self._route_epoch_cognition(
                        pending.job, pending.epoch_order, cognition
                    )
                )
                if authoritative.effects:
                    self._epoch_authoritative_buffer.setdefault(
                        pending.epoch_id, []
                    ).append((pending.epoch_order, authoritative))
            else:
                outputs.append(completed_output)
            self.completed_provider_jobs.append(
                {
                    "job_id": pending.job.id,
                    "status": status,
                    "source_tick": pending.source_tick,
                    "completed_tick": world.tick,
                    "elapsed_ms": elapsed_ms,
                }
            )
        outputs.extend(self._release_epoch_relationship_cognition())
        outputs.extend(self._release_epoch_authoritative_outputs())
        self._advance_lifecycle_after_collect()
        return outputs

    def _route_epoch_cognition(
        self,
        job: AgentJob,
        order: int,
        cognition: ProviderOutput,
    ) -> list[ProviderOutput]:
        if job.kind != "relationship_round":
            return [cognition] if cognition.effects else []
        epoch = _dict(_dict(cognition.metadata.get("scheduler")).get("cognition_epoch"))
        epoch_id = str(epoch.get("epoch_id", ""))
        schedules = [
            item for item in cognition.effects if item.type == "thought_schedule_add"
        ]
        immediate = [
            item for item in cognition.effects if item.type != "thought_schedule_add"
        ]
        outputs = (
            [
                ProviderOutput(
                    source=cognition.source,
                    summary=cognition.summary,
                    effects=immediate,
                    metadata=json_copy(cognition.metadata),
                )
            ]
            if immediate
            else []
        )
        release_id = f"{epoch_id}:graph:{int(order)}"
        if (
            schedules
            and epoch_id
            and epoch_id not in self._released_presentation_epoch_ids
            and release_id not in self._released_presentation_epoch_ids
        ):
            generation = int(epoch.get("generation", 0) or 0)
            effects = plan_incremental_relationship_presentation(
                schedules,
                graph_order=order,
                epoch_id=epoch_id,
                generation=generation,
                seed=f"{epoch_id}:{generation}",
            )
            self._released_presentation_epoch_ids.add(release_id)
            if effects:
                metadata = json_copy(cognition.metadata)
                metadata["presentation_only"] = True
                active_effects = [
                    item
                    for item in effects
                    if str(item.fields.get("origin", "active_node"))
                    != "ripple_response"
                ]
                ripple_effects = [
                    item
                    for item in effects
                    if str(item.fields.get("origin", "active_node"))
                    == "ripple_response"
                ]
                metadata["presentation_epoch"] = {
                    "epoch_id": epoch_id,
                    "generation": generation,
                    "graph_orders": [int(order)],
                    "active_count": len(active_effects),
                    "ripple_count": len(ripple_effects),
                    "schedule_count": len(effects),
                    "occurrence_count": sum(
                        len(item.fields.get("occurrences", [])) for item in effects
                    ),
                    "duration_seconds": 60,
                    "streamed": True,
                }
                outputs.append(
                    ProviderOutput(
                        source=cognition.source,
                        summary=(
                            f"paced {len(active_effects)} active and "
                            f"{len(ripple_effects)} ripple thoughts for "
                            f"{epoch_id} graph {int(order)}"
                        ),
                        effects=effects,
                        metadata=metadata,
                    )
                )
        return outputs

    def _release_epoch_relationship_cognition(self) -> list[ProviderOutput]:
        released: list[ProviderOutput] = []
        now = perf_counter()
        for epoch_id, buffered in list(
            self._epoch_relationship_cognition_buffer.items()
        ):
            pending_relationship = any(
                pending.epoch_id == epoch_id
                and pending.job.kind == "relationship_round"
                for pending in self.pending_provider_jobs.values()
            )
            queued_relationship = any(
                job.kind == "relationship_round"
                and str(_dict(job.metadata.get("cognition_epoch")).get("epoch_id", ""))
                == epoch_id
                for job in self.queue
            )
            epoch_metadata = _dict(
                _dict(buffered[0][1].metadata.get("scheduler")).get("cognition_epoch")
            )
            started_at = float(self.active_epoch.get("started_at", now) or now)
            deadline_reached = now - started_at >= max(
                float(self.config.epoch_soft_deadline_seconds), 0.0
            )
            if (pending_relationship or queued_relationship) and not deadline_reached:
                continue
            grouped = [(order, output.effects) for order, output in buffered]
            generation = int(epoch_metadata.get("generation", 0) or 0)
            effects = plan_normal_relationship_presentation(
                grouped,
                epoch_id=epoch_id,
                generation=generation,
                seed=f"{epoch_id}:{generation}",
            )
            del self._epoch_relationship_cognition_buffer[epoch_id]
            self._released_presentation_epoch_ids.update(
                f"{epoch_id}:graph:{int(order)}" for order, _ in buffered
            )
            if not effects:
                continue
            metadata = json_copy(buffered[0][1].metadata)
            metadata["presentation_only"] = True
            active_effects = [
                item
                for item in effects
                if str(item.fields.get("origin", "active_node")) != "ripple_response"
            ]
            ripple_effects = [
                item
                for item in effects
                if str(item.fields.get("origin", "active_node")) == "ripple_response"
            ]
            metadata["presentation_epoch"] = {
                "epoch_id": epoch_id,
                "generation": generation,
                "active_node_ids": [
                    _node_ref(item.fields.get("target", item.fields.get("node_id", "")))
                    for item in active_effects
                ],
                "ripple_node_ids": [
                    _node_ref(item.fields.get("target", item.fields.get("node_id", "")))
                    for item in ripple_effects
                ],
                "active_count": len(active_effects),
                "ripple_count": len(ripple_effects),
                "schedule_count": len(effects),
                "occurrence_count": sum(
                    len(item.fields.get("occurrences", [])) for item in effects
                ),
                "duration_seconds": 60,
            }
            released.append(
                ProviderOutput(
                    source=buffered[0][1].source,
                    summary=(
                        f"paced {len(active_effects)} active and "
                        f"{len(ripple_effects)} ripple thoughts for {epoch_id}"
                    ),
                    effects=effects,
                    metadata=metadata,
                )
            )
        return released

    def _release_epoch_authoritative_outputs(self) -> list[ProviderOutput]:
        released: list[ProviderOutput] = []
        now = perf_counter()
        for epoch_id, buffered in list(self._epoch_authoritative_buffer.items()):
            pending_same_epoch = any(
                pending.epoch_id == epoch_id
                for pending in self.pending_provider_jobs.values()
            )
            started_at = float(self.active_epoch.get("started_at", now) or now)
            deadline_reached = now - started_at >= max(
                float(self.config.epoch_soft_deadline_seconds), 0.0
            )
            if (
                pending_same_epoch
                and not deadline_reached
                and epoch_id not in self._released_epoch_ids
            ):
                continue
            buffered.sort(key=lambda item: item[0])
            released.extend(output for _, output in buffered)
            del self._epoch_authoritative_buffer[epoch_id]
            self._released_epoch_ids.add(epoch_id)
        return released


def _slot_matches(slot: str, job: AgentJob) -> bool:
    if slot == "relationship" and job.kind == "relationship_round":
        return True
    if slot == "key_character" and job.kind == "key_character_continuity":
        return True
    if slot == "lens" and job.slot == "event_lens":
        return True
    if slot == "event_lens" and job.kind in {"commercial_lens", "relationship_lens"}:
        return True
    if slot.startswith("tribe") and job.kind == "relationship_round":
        return True
    if slot.startswith("protagonist") and job.kind == "key_character_continuity":
        return True
    return False


def _job_lane(job: AgentJob) -> str:
    if job.kind == "relationship_round":
        return "relationship"
    if job.kind == "key_character_continuity":
        return "protagonist"
    return "auxiliary"


def _context_fingerprint(world: World, context_packet: JsonDict) -> str:
    node_ids = {
        str(item.get("id", ""))
        for field_name in ("coverage_nodes", "active_candidates")
        for item in context_packet.get(field_name, [])
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    payload = {
        "nodes": sorted(node_id for node_id in node_ids if world.has_node(node_id)),
        "missing_nodes": sorted(
            node_id for node_id in node_ids if not world.has_node(node_id)
        ),
        "relationships": [
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "weight": round(float(edge.weight), 6),
            }
            for edge in sorted(world.relationships.values(), key=lambda item: item.key)
            if edge.source in node_ids and edge.target in node_ids
        ],
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _json_fingerprint(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _snapshot_hash(snapshot: JsonDict) -> str:
    raw = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _provider_request_id(job: AgentJob, epoch_data: JsonDict, tick: int) -> str:
    identity = (
        f"{epoch_data.get('epoch_id', '')}:"
        f"{epoch_data.get('generation', 0)}:{job.id}:{int(tick)}"
    )
    return f"provider-request-{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _generation_id(epoch_id: str, job_id: str, generation: int) -> str:
    if not epoch_id:
        return ""
    return f"{epoch_id}:{int(generation)}:{job_id}"


def _restore_job_spec(
    value: JsonDict,
    base_jobs: dict[str, AgentJob],
) -> AgentJob | None:
    job_id = str(value.get("id", ""))
    metadata = _dict(value.get("metadata"))
    template_id = str(metadata.get("epoch_template_id", ""))
    if not template_id and "::epoch-" in job_id:
        template_id = job_id.split("::epoch-", 1)[0]
    base = base_jobs.get(job_id) or base_jobs.get(template_id)
    if base is None:
        provider_name = str(value.get("provider", ""))
        base = next(
            (
                candidate
                for candidate in base_jobs.values()
                if candidate.provider.name == provider_name
                and candidate.kind == str(value.get("kind", ""))
            ),
            None,
        )
    if base is None or not job_id:
        return None
    return AgentJob(
        id=job_id,
        kind=str(value.get("kind", base.kind)),
        provider=base.provider,
        graph_key=str(value.get("graph_key", base.graph_key)),
        priority=int(value.get("priority", base.priority) or 0),
        slot=str(value.get("slot", base.slot)),
        metadata=json_copy(metadata),
    )


def _provider_output_from_dict(value: Any) -> ProviderOutput | None:
    if not isinstance(value, dict):
        return None
    effects = [
        WorldEffect(
            str(item.get("type", "")),
            {str(key): json_copy(raw) for key, raw in item.items() if key != "type"},
        )
        for item in value.get("effects", [])
        if isinstance(item, dict) and str(item.get("type", ""))
    ]
    metadata = {
        str(key): json_copy(raw)
        for key, raw in value.items()
        if key not in {"source", "summary", "effects"}
    }
    return ProviderOutput(
        source=str(value.get("source", "")),
        summary=str(value.get("summary", "")),
        effects=effects,
        metadata=metadata,
    )


def _split_epoch_output(
    output: ProviderOutput,
) -> tuple[ProviderOutput, ProviderOutput]:
    cognition_types = {"thought_bubble_add", "thought_schedule_add", "memory_add"}
    cognition_effects = [
        item for item in output.effects if item.type in cognition_types
    ]
    authoritative_effects = [
        item for item in output.effects if item.type not in cognition_types
    ]
    cognition_metadata = json_copy(output.metadata)
    cognition_metadata["epoch_phase"] = "cognition"
    authoritative_metadata = json_copy(output.metadata)
    authoritative_metadata["epoch_phase"] = "authoritative"
    authoritative_metadata.pop("provider_runtime", None)
    authoritative_metadata.pop("provider_attempts", None)
    return (
        ProviderOutput(
            source=output.source,
            summary=output.summary,
            effects=cognition_effects,
            metadata=cognition_metadata,
        ),
        ProviderOutput(
            source=output.source,
            summary=f"stable epoch candidates: {output.summary}",
            effects=authoritative_effects,
            metadata=authoritative_metadata,
        ),
    )


def _revalidate_stale_effects(world: World, effects: list[Any]) -> list[Any]:
    retained: list[Any] = []
    for item in effects:
        if item.type in {"thought_bubble_add", "thought_schedule_add", "memory_add"}:
            retained.append(item)
            continue
        fields = item.fields
        if item.type == "rule_pressure_add":
            node_id = _node_ref(fields.get("target", fields.get("node_id", "")))
            rule = str(fields.get("rule", ""))
            if node_id and rule_pressure_is_groundable(world, node_id, rule, fields):
                retained.append(item)
            continue
        if item.type == "relationship_delta":
            source_id = _node_ref(fields.get("source", ""))
            target_id = _node_ref(fields.get("target", ""))
            if (
                source_id
                and target_id
                and world.has_node(source_id)
                and world.has_node(target_id)
            ):
                retained.append(item)
            continue
        if item.type == "key_character_state":
            node_id = _node_ref(fields.get("target", fields.get("node_id", "")))
            if node_id and world.has_node(node_id):
                retained.append(item)
    return retained


def _node_ref(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id", value.get("node_id", ""))
    text = str(value)
    return text.split(":", 1)[1] if text.startswith("node:") else text


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}
