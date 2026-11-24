"""In-process worker job primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from ai_native_world_engine.core import (
    DEFAULT_TIMELINE_RETENTION,
    RunConfig,
    RunSession,
    apply_projection_delta,
    project_run_for_viewer,
    projection_delta_from_incremental,
    projection_keyframe,
    run,
)
from ai_native_world_api.models import RunControlState, RunRecord, RunStatus
from ai_native_world_api.provider_config import RuntimeProviderSelection, create_runtime_provider_config
from ai_native_world_api.repository import LeaseLostError, RunProgressWrite, RunRepository
from ai_native_world_api.runtime_config import scenario_scheduler_config
from ai_native_world_api.scenario_defaults import scenario_defaults


JsonDict = dict[str, Any]
CHECKPOINT_COMMIT_INTERVAL = 16
KEYFRAME_COMMIT_INTERVAL = 32
CHECKPOINT_DELTA_BYTES = 1_000_000


class RuntimeProviderFactory(Protocol):
    def __call__(
        self,
        rules: list[str] | None = None,
        runtime_provider: JsonDict | None = None,
    ) -> RuntimeProviderSelection:
        ...


@dataclass(slots=True)
class RunJob:
    run_id: str
    owner_id: str = "local"
    scenario: str = "seed"
    seed: int = 7
    ticks: int = 3
    rules: list[str] | None = None
    evaluation_goals: JsonDict | None = None
    interventions: list[JsonDict] | None = None
    sovereign_intents: list[JsonDict] | None = None
    runtime_provider: JsonDict | None = None
    require_cognition_ready: bool = False
    retry_of_run_id: str = ""
    retry_attempt: int = 0


def run_job(job: RunJob, runtime_provider_factory: RuntimeProviderFactory = create_runtime_provider_config) -> JsonDict:
    result = run(_run_config(job, runtime_provider_factory))
    result_data = result.to_dict()
    return {
        "run_id": job.run_id,
        "status": "completed",
        "config": result_data["config"],
        "snapshot": result_data["snapshot"],
        "events": result_data["events"],
        "traces": result_data["traces"],
        "scorecard": result_data["scorecard"],
        "provider_execution_report": result_data["provider_execution_report"],
        "provider_attempt_report": result_data["provider_attempt_report"],
        "provider_attempts": result_data["provider_attempts"],
        "provider_audits": result_data["provider_audits"],
        "sovereign_intent_audits": result_data["sovereign_intent_audits"],
        "projection": project_run_for_viewer(result).to_dict(),
        "timeline": result_data["timeline"],
        "memory_consolidation_report": result_data["memory_consolidation_report"],
        "status_events": _timeline_status_events(job.run_id, result_data["timeline"]),
    }


class InProcessRunQueue:
    def __init__(
        self,
        repository: RunRepository,
        auto_drain: bool = True,
        cooperative_ticks: bool = False,
        runtime_provider_factory: RuntimeProviderFactory = create_runtime_provider_config,
        worker_id: str = "",
        worker_mode: str = "embedded",
        sessions: dict[str, RunSession] | None = None,
    ) -> None:
        self.repository = repository
        self.auto_drain = auto_drain
        self.cooperative_ticks = cooperative_ticks
        self.runtime_provider_factory = runtime_provider_factory
        self.worker_id = str(worker_id)
        self.worker_mode = str(worker_mode)
        self.pending: list[RunJob] = []
        self.sessions = sessions if sessions is not None else {}

    def request_control(
        self,
        run_id: str,
        command: str,
        reason: str = "",
    ) -> bool:
        """Propagate controls to a live in-process execution owner."""

        session = self.sessions.get(str(run_id))
        if session is None:
            return False
        normalized = str(command).strip().lower()
        if normalized == "cancel":
            session.request_cancel(reason or "run canceled by control command")
            return True
        return normalized in {"pause", "resume"}

    def close_session(self, run_id: str, reason: str) -> bool:
        session = self.sessions.pop(str(run_id), None)
        if session is None:
            return False
        session.close(reason)
        return True

    def enqueue(self, job: RunJob) -> JsonDict:
        scheduler = _scheduler_for_job(job)
        record = RunRecord(
            id=job.run_id,
            scenario=job.scenario,
            seed=int(job.seed),
            ticks=int(job.ticks),
            owner_id=job.owner_id,
            status=RunStatus.QUEUED,
            retry_of_run_id=str(job.retry_of_run_id),
            retry_attempt=max(int(job.retry_attempt), 0),
            config={
                "scenario": job.scenario,
                "seed": int(job.seed),
                "ticks": int(job.ticks),
                "rules": _rules_for_job(job),
                "evaluation_goals": _evaluation_goals_for_job(job),
                "interventions": _list_of_dicts(job.interventions),
                "sovereign_intents": _list_of_dicts(job.sovereign_intents),
                "scheduler": scheduler.to_dict() if scheduler else {"enabled": False},
                "runtime_provider": _public_runtime_provider(job.runtime_provider),
                "require_cognition_ready": bool(job.require_cognition_ready),
                "retry_of_run_id": str(job.retry_of_run_id),
                "retry_attempt": max(int(job.retry_attempt), 0),
            },
            interventions=_list_of_dicts(job.interventions),
            sovereign_intents=_list_of_dicts(job.sovereign_intents),
            runtime_state=_initial_runtime_state(job) if self.cooperative_ticks else {},
        )
        self.repository.save_run(record)
        self.pending.append(job)
        if self.auto_drain:
            self.drain()
        return self.repository.get_run(job.run_id).to_summary_dict()  # type: ignore[union-attr]

    def drain(self) -> list[JsonDict]:
        results: list[JsonDict] = []
        while self.pending:
            pending_before = [job.run_id for job in self.pending]
            result = self.process_next()
            results.append(result)
            if result.get("status") == "paused" and [job.run_id for job in self.pending] == pending_before:
                break
        return results

    def process_run(self, run_id: str) -> JsonDict:
        for index, job in enumerate(self.pending):
            if job.run_id != run_id:
                continue
            self.pending.insert(0, self.pending.pop(index))
            return self.process_next()
        return {"status": "idle", "run_id": run_id, "pending_count": len(self.pending)}

    def recover_pending(self, mark_running_recovery: bool = True) -> JsonDict:
        existing = {job.run_id for job in self.pending}
        recovered: list[str] = []
        skipped: list[str] = []
        for record in self.repository.list_runs():
            if record.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                continue
            if record.id in existing:
                skipped.append(record.id)
                continue
            if record.status == RunStatus.RUNNING and mark_running_recovery:
                record.status_events.append(
                    {
                        "type": "run.status",
                        "run_id": record.id,
                        "status": RunStatus.QUEUED.value,
                        "message": "Recovered running run after worker restart",
                        "previous_status": RunStatus.RUNNING.value,
                    }
                )
                record.status = RunStatus.QUEUED
                self.repository.save_run(record)
            self.pending.append(_job_from_record(record))
            existing.add(record.id)
            recovered.append(record.id)
        if self.auto_drain and recovered:
            self.drain()
        return {
            "status": "recovered",
            "recovered_count": len(recovered),
            "recovered_run_ids": recovered,
            "skipped_count": len(skipped),
            "skipped_run_ids": skipped,
            "pending_count": len(self.pending),
        }

    def process_next(self) -> JsonDict:
        if not self.pending:
            return {"status": "idle"}
        job = self.pending.pop(0)
        record = self.repository.get_run(job.run_id)
        if record is None:
            record = RunRecord(
                id=job.run_id,
                scenario=job.scenario,
                seed=int(job.seed),
                ticks=int(job.ticks),
                owner_id=job.owner_id,
                status=RunStatus.QUEUED,
            )
        elif record.interventions or record.sovereign_intents:
            job = RunJob(
                run_id=job.run_id,
                owner_id=record.owner_id,
                scenario=job.scenario,
                seed=job.seed,
                ticks=job.ticks,
                rules=job.rules,
                evaluation_goals=job.evaluation_goals,
                interventions=record.interventions,
                sovereign_intents=record.sovereign_intents,
                runtime_provider=job.runtime_provider,
                require_cognition_ready=job.require_cognition_ready,
                retry_of_run_id=job.retry_of_run_id,
                retry_attempt=job.retry_attempt,
            )
        if record.control_state == RunControlState.PAUSED:
            if not any(pending.run_id == job.run_id for pending in self.pending):
                self.pending.append(job)
            record.status_events.append(
                {
                    "type": "run.status",
                    "run_id": record.id,
                    "status": record.status.value,
                    "message": "Run skipped because it is paused",
                    "control_state": record.control_state.value,
                }
            )
            self._annotate_worker_runtime(record, "paused")
            self.repository.save_run(record)
            return {
                "status": "paused",
                "run_id": record.id,
                "control_state": record.control_state.value,
                "pending_count": len(self.pending),
            }
        if record.control_state == RunControlState.CANCELED:
            if record.status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
                record.mark(RunStatus.FAILED, "Run canceled before execution")
            session = self.sessions.get(job.run_id)
            if session is not None:
                session.request_cancel("run canceled before execution")
            self.close_session(job.run_id, "run canceled before execution")
            self._annotate_worker_runtime(record, "canceled")
            self.repository.save_run(record)
            return record.to_detail_dict()
        if self.cooperative_ticks:
            return self._process_cooperative_tick(job, record)
        record.mark(RunStatus.RUNNING)
        self.repository.save_run(record)
        try:
            payload = run_job(job, self.runtime_provider_factory)
            record.config = _dict(payload.get("config"))
            record.snapshot = _dict(payload.get("snapshot"))
            record.events = _list_of_dicts(payload.get("events"))
            record.traces = _list_of_dicts(payload.get("traces"))
            record.scorecard = _dict(payload.get("scorecard"))
            record.provider_execution_report = _dict(payload.get("provider_execution_report"))
            record.provider_attempt_report = _dict(payload.get("provider_attempt_report"))
            record.provider_attempts = _list_of_dicts(payload.get("provider_attempts"))
            record.projection = _dict(payload.get("projection"))
            record.timeline = _list_of_dicts(payload.get("timeline"))
            record.memory_consolidation_report = _list_of_dicts(payload.get("memory_consolidation_report"))
            record.status_events.extend(_list_of_dicts(payload.get("status_events")))
            record.provider_audits = _list_of_dicts(payload.get("provider_audits"))
            record.sovereign_intent_audits = _list_of_dicts(payload.get("sovereign_intent_audits"))
            record.mark(RunStatus.COMPLETED)
        except Exception as exc:  # noqa: BLE001 - worker failures must be persisted.
            record.mark(RunStatus.FAILED, str(exc))
        self.repository.save_run(record)
        return record.to_detail_dict()

    def _process_cooperative_tick(self, job: RunJob, record: RunRecord) -> JsonDict:
        runtime_state = _runtime_state(record, job)
        tick_cursor = int(runtime_state.get("tick_cursor", 0) or 0)
        target_ticks = int(runtime_state.get("target_ticks", job.ticks) or job.ticks)
        active_session = self.sessions.get(job.run_id)
        pending_count = int(runtime_state.get("provider_pending_count", 0) or 0)
        runtime_phase = str(runtime_state.get("phase", ""))
        legacy_completed = (
            not runtime_phase
            and tick_cursor >= target_ticks
            and pending_count == 0
        )
        phase_completed = runtime_phase == "completed"
        if (legacy_completed or phase_completed) and (
            active_session is None or active_session.completed
        ):
            if self.repository.get_final_result(record.id) is not None:
                if record.status != RunStatus.COMPLETED:
                    record.mark(RunStatus.COMPLETED)
                runtime_state["last_step_status"] = "completed"
                runtime_state["final_result_available"] = True
                record.runtime_state = runtime_state
                self.close_session(job.run_id, "run completed")
                self.repository.save_run(record)
                return record.to_detail_dict()
            recovered_session = self._session_for_job(job, record, tick_cursor)
            if recovered_session.completed:
                final_data = recovered_session.result().to_dict()
                final_data["projection"] = project_run_for_viewer(
                    final_data
                ).to_dict()
                self.repository.save_final_result(record.id, final_data)
                record.mark(RunStatus.COMPLETED)
                record.runtime_state = {
                    **runtime_state,
                    "last_step_status": "completed",
                    "final_result_available": True,
                }
                self._annotate_worker_runtime(record, "completed")
                self.close_session(job.run_id, "run completed")
                self.repository.save_run(record)
                return record.to_detail_dict()

        try:
            session = self._session_for_job(job, record, tick_cursor)
            session.config.interventions = _list_of_dicts(job.interventions)
            session.config.sovereign_intents = _list_of_dicts(job.sovereign_intents)
            incremental = session.step_incremental()
            if incremental is None:
                raise RuntimeError("incremental session did not advance")
            next_tick = session.world.tick
            scheduler_status = session.scheduler.status_snapshot() if session.scheduler else {}
            provider_pending = _list_of_dicts(scheduler_status.get("provider_pending"))
            bootstrap_state = _dict(session.runtime_status().get("bootstrap_state"))
            bootstrap_phase = str(bootstrap_state.get("phase", ""))
            session_completed = session.completed
            step_status = (
                bootstrap_phase
                if bootstrap_phase and bootstrap_phase not in {"ready", "legacy_ready"}
                else "provider_pending"
                if provider_pending
                else session.phase
            )
            if record.status != RunStatus.RUNNING:
                record.mark(RunStatus.RUNNING)
            commit = incremental.commit
            runtime_state.update(
                {
                    "mode": "cooperative_tick",
                    "tick_cursor": next_tick,
                    "target_ticks": target_ticks,
                    "session_backed": True,
                    "last_step_status": step_status,
                    "provider_pending_count": len(provider_pending),
                    "provider_pending": provider_pending,
                    "commit_sequence": commit.sequence,
                    "event_cursor": commit.event_end,
                    "trace_cursor": commit.trace_end,
                    "projection_cursor": commit.sequence,
                    **session.runtime_status(),
                }
            )
            checkpoint = None
            if _checkpoint_due(incremental.to_dict(), session):
                checkpoint = session.compact_checkpoint()
                runtime_state["checkpoint_sequence"] = commit.sequence
            record.runtime_state = runtime_state
            self._annotate_worker_runtime(
                record,
                step_status,
            )
            record.status_events.append(
                {
                    "type": "run.tick",
                    "run_id": record.id,
                    "status": "running",
                    "tick": next_tick,
                    "sequence": commit.sequence,
                    "message": f"Run tick {next_tick}",
                }
            )
            record.status_events = record.status_events[-100:]
            incremental_data = incremental.to_dict()
            projection_delta = projection_delta_from_incremental(
                incremental_data
            ).to_dict()
            keyframe = None
            if (
                commit.sequence == 1
                or commit.sequence % KEYFRAME_COMMIT_INTERVAL == 0
                or session_completed
            ):
                existing_keyframe = self.repository.get_latest_projection(record.id)
                if existing_keyframe is None:
                    keyframe = projection_keyframe(session.world, commit.sequence)
                else:
                    keyframe = existing_keyframe
                    keyframe_sequence = int(
                        keyframe.get("sequence", 0) or 0
                    )
                    for retained_delta in self.repository.list_projection_deltas(
                        record.id, after=keyframe_sequence, limit=0
                    ):
                        keyframe = apply_projection_delta(
                            keyframe, retained_delta
                        )
                keyframe = apply_projection_delta(keyframe, projection_delta)
            self.repository.save_run_progress(
                RunProgressWrite(
                    run=record,
                    incremental=incremental_data,
                    checkpoint=checkpoint,
                    projection_delta=projection_delta,
                    projection_keyframe=keyframe,
                )
            )
            if session_completed:
                final_data = session.result().to_dict()
                final_data["projection"] = project_run_for_viewer(final_data).to_dict()
                self.repository.save_final_result(record.id, final_data)
                record.mark(RunStatus.COMPLETED)
                record.runtime_state = {
                    **_dict(record.runtime_state),
                    "last_step_status": "completed",
                    "phase": "completed",
                    "final_result_available": True,
                }
                self._annotate_worker_runtime(record, "completed")
                self.close_session(job.run_id, "run completed")
                self.repository.save_run(record)
            elif bootstrap_phase in {"failed", "timed_out", "canceled"}:
                error = str(
                    bootstrap_state.get("error_message")
                    or bootstrap_state.get("error_code")
                    or f"world bootstrap {bootstrap_phase}"
                )
                record.runtime_state = {
                    **_dict(record.runtime_state),
                    "last_step_status": bootstrap_phase,
                    "bootstrap_state": bootstrap_state,
                }
                record.mark(RunStatus.FAILED, error)
                self.close_session(job.run_id, error)
                self.repository.save_run(record)
            else:
                if not any(pending.run_id == job.run_id for pending in self.pending):
                    self.pending.append(job)
        except LeaseLostError:
            session = self.sessions.get(job.run_id)
            if session is not None:
                session.request_cancel("worker lease lost")
            self.close_session(job.run_id, "worker lease lost")
            raise
        except Exception as exc:  # noqa: BLE001 - worker failures must be persisted.
            record.runtime_state = {
                **runtime_state,
                "last_step_status": "failed",
                "error": str(exc),
            }
            self._annotate_worker_runtime(record, "failed")
            session = self.sessions.get(job.run_id)
            if session is not None:
                session.request_cancel("worker execution failed")
            self.close_session(job.run_id, "worker execution failed")
            record.mark(RunStatus.FAILED, str(exc))
            self.repository.save_run(record)
        return record.to_detail_dict()

    def _annotate_worker_runtime(self, record: RunRecord, cycle_status: str) -> None:
        if self.worker_mode != "standalone":
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        runtime_state = _dict(record.runtime_state)
        runtime_state.update(
            {
                "worker_id": self.worker_id,
                "worker_mode": self.worker_mode,
                "worker_cycle_status": str(cycle_status),
                "worker_cycle_at": timestamp,
            }
        )
        record.runtime_state = runtime_state
        record.status_events.append(
            {
                "type": "run.status",
                "run_id": record.id,
                "status": record.status.value,
                "message": "Standalone worker cycle",
                "worker_id": self.worker_id,
                "worker_mode": self.worker_mode,
                "worker_cycle_status": str(cycle_status),
                "tick": int(runtime_state.get("tick_cursor", 0) or 0),
                "timestamp": timestamp,
            }
        )

    def _session_for_job(self, job: RunJob, record: RunRecord, tick_cursor: int) -> RunSession:
        session = self.sessions.get(job.run_id)
        if session is None:
            legacy_checkpoint = _dict(
                _dict(record.runtime_state).get("session_checkpoint")
            )
            recovery = self.repository.get_run_recovery_data(job.run_id)
            checkpoint = _dict(recovery.get("checkpoint"))
            if checkpoint:
                rules = _rules_for_job(job)
                runtime_provider = self.runtime_provider_factory(rules=rules, runtime_provider=_dict(job.runtime_provider))
                session = RunSession.from_compact_checkpoint(
                    checkpoint,
                    scheduler_provider=runtime_provider.scheduler_provider,
                    commits=_list_of_dicts(recovery.get("commits")),
                    events=_list_of_dicts(recovery.get("events")),
                    traces=_list_of_dicts(recovery.get("traces")),
                    provider_outputs=_list_of_dicts(recovery.get("provider_outputs")),
                    provider_attempts=_list_of_dicts(recovery.get("provider_attempts")),
                    provider_audits=_list_of_dicts(recovery.get("provider_audits")),
                    intervention_audits=_list_of_dicts(recovery.get("intervention_audits")),
                    memory_consolidation_report=_list_of_dicts(
                        recovery.get("memory_consolidation_report")
                    ),
                    sovereign_intent_audits=_list_of_dicts(
                        recovery.get("sovereign_intent_audits")
                    ),
                )
            elif legacy_checkpoint:
                rules = _rules_for_job(job)
                runtime_provider = self.runtime_provider_factory(rules=rules, runtime_provider=_dict(job.runtime_provider))
                session = RunSession.from_checkpoint(
                    legacy_checkpoint,
                    scheduler_provider=runtime_provider.scheduler_provider,
                )
            else:
                session = RunSession(_run_config(job, self.runtime_provider_factory))
                while session.world.tick < tick_cursor and session.step():
                    pass
            self.sessions[job.run_id] = session
        if (
            session.phase == "stopped"
            and session.lifecycle_reason.startswith("worker shutdown:")
        ):
            session.resume()
        return session


def _checkpoint_due(incremental: JsonDict, session: RunSession) -> bool:
    commit = _dict(incremental.get("commit"))
    sequence = int(commit.get("sequence", 0) or 0)
    phase_changed = str(commit.get("source_phase", "")) != str(
        commit.get("resulting_phase", "")
    )
    delta_bytes = len(
        json.dumps(
            commit.get("state_delta", {}),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return (
        sequence == 1
        or sequence % CHECKPOINT_COMMIT_INTERVAL == 0
        or phase_changed
        or session.completed
        or delta_bytes >= CHECKPOINT_DELTA_BYTES
    )


def _dict(value: object) -> JsonDict:
    return dict(value) if isinstance(value, dict) else {}


def _public_runtime_provider(value: object) -> JsonDict:
    """Return provider metadata safe to persist in a Run record."""
    provider = _dict(value)
    return {key: item for key, item in provider.items() if key not in {"api_key", "secret", "token"}}


def _list_of_dicts(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _initial_runtime_state(job: RunJob) -> JsonDict:
    state: JsonDict = {
        "mode": "cooperative_tick",
        "tick_cursor": 0,
        "target_ticks": int(job.ticks),
        "session_backed": False,
        "last_step_status": "queued",
        "phase": "queued",
    }
    if job.require_cognition_ready:
        state["bootstrap_state"] = {
            "phase": "creating_world",
            "scenario_id": job.scenario,
            "provider_mode": str(
                _dict(job.runtime_provider).get("mode", "deterministic")
            ),
            "ready": False,
            "retryable": True,
        }
    return state


def _runtime_state(record: RunRecord, job: RunJob) -> JsonDict:
    state = _dict(record.runtime_state)
    if state.get("mode") != "cooperative_tick":
        state.update(_initial_runtime_state(job))
    state.setdefault("tick_cursor", _latest_timeline_tick(record.timeline))
    state.setdefault("target_ticks", int(job.ticks))
    return state


def _apply_run_payload(record: RunRecord, payload: JsonDict) -> None:
    record.config = _dict(payload.get("config"))
    record.snapshot = _dict(payload.get("snapshot"))
    record.events = _list_of_dicts(payload.get("events"))
    record.traces = _list_of_dicts(payload.get("traces"))
    record.scorecard = _dict(payload.get("scorecard"))
    record.provider_execution_report = _dict(payload.get("provider_execution_report"))
    record.provider_attempt_report = _dict(payload.get("provider_attempt_report"))
    record.provider_attempts = _list_of_dicts(payload.get("provider_attempts"))
    record.projection = _dict(payload.get("projection"))
    record.timeline = _list_of_dicts(payload.get("timeline"))
    record.memory_consolidation_report = _list_of_dicts(payload.get("memory_consolidation_report"))
    record.provider_audits = _list_of_dicts(payload.get("provider_audits"))
    record.sovereign_intent_audits = _list_of_dicts(payload.get("sovereign_intent_audits"))


def _run_config(job: RunJob, runtime_provider_factory: RuntimeProviderFactory = create_runtime_provider_config) -> RunConfig:
    rules = _rules_for_job(job)
    runtime_provider = runtime_provider_factory(rules=rules, runtime_provider=_dict(job.runtime_provider))
    return RunConfig(
        scenario=job.scenario,
        seed=job.seed,
        ticks=job.ticks,
        rules=rules,
        evaluation_goals=_evaluation_goals_for_job(job),
        capture_timeline=True,
        interventions=_list_of_dicts(job.interventions),
        sovereign_intents=_list_of_dicts(job.sovereign_intents),
        scheduler=_scheduler_for_job(job),
        provider=runtime_provider.scheduler_provider,
        scheduler_provider=runtime_provider.scheduler_provider,
        runtime_provider=runtime_provider.metadata,
        require_cognition_ready=bool(job.require_cognition_ready),
        provider_drain_timeout_seconds=max(
            float(runtime_provider.metadata.get("deadline_seconds", 60.0) or 0.0),
            0.0,
        ),
    )


def _scheduler_for_job(job: RunJob):
    return scenario_scheduler_config(job.scenario, int(job.ticks))


def _payload_from_session(run_id: str, session: RunSession) -> JsonDict:
    result_data = session.result().to_dict()
    return {
        "run_id": run_id,
        "status": "completed" if session.completed else "running",
        "config": result_data["config"],
        "snapshot": result_data["snapshot"],
        "events": result_data["events"],
        "traces": result_data["traces"],
        "scorecard": result_data["scorecard"],
        "provider_execution_report": result_data["provider_execution_report"],
        "provider_attempt_report": result_data["provider_attempt_report"],
        "provider_attempts": result_data["provider_attempts"],
        "provider_audits": result_data["provider_audits"],
        "sovereign_intent_audits": result_data["sovereign_intent_audits"],
        "projection": project_run_for_viewer(result_data).to_dict(),
        "timeline": result_data["timeline"],
        "memory_consolidation_report": result_data["memory_consolidation_report"],
        "status_events": _timeline_status_events(run_id, result_data["timeline"]),
    }


def _merge_tick_status_events(record: RunRecord, tick_events: list[JsonDict]) -> None:
    existing_tick_keys = {
        int(event.get("tick", 0) or 0)
        for event in record.status_events
        if event.get("type") == "run.tick"
    }
    for event in tick_events:
        if event.get("type") != "run.tick":
            continue
        tick = int(event.get("tick", 0) or 0)
        if tick not in existing_tick_keys:
            record.status_events.append(event)
            existing_tick_keys.add(tick)
    retained_ticks = {
        int(frame.get("tick", 0) or 0)
        for frame in record.timeline[-max(int(record.config.get("timeline_retention", DEFAULT_TIMELINE_RETENTION) or DEFAULT_TIMELINE_RETENTION), 1) :]
    }
    record.status_events = [
        event
        for event in record.status_events
        if event.get("type") != "run.tick" or int(event.get("tick", 0) or 0) in retained_ticks
    ]


def _job_from_record(record: RunRecord) -> RunJob:
    config = record.config if isinstance(record.config, dict) else {}
    return RunJob(
        run_id=record.id,
        owner_id=record.owner_id,
        scenario=str(config.get("scenario", record.scenario)),
        seed=int(config.get("seed", record.seed) or record.seed),
        ticks=int(config.get("ticks", record.ticks) or record.ticks),
        rules=[str(item) for item in _list(config.get("rules"))] or None,
        evaluation_goals=_dict(config.get("evaluation_goals")) or None,
        interventions=_list_of_dicts(record.interventions or config.get("interventions")),
        sovereign_intents=_list_of_dicts(record.sovereign_intents or config.get("sovereign_intents")),
        runtime_provider=_dict(config.get("runtime_provider")),
        require_cognition_ready=bool(
            config.get("require_cognition_ready", False)
        ),
        retry_of_run_id=str(
            record.retry_of_run_id or config.get("retry_of_run_id", "")
        ),
        retry_attempt=max(
            int(record.retry_attempt or config.get("retry_attempt", 0) or 0), 0
        ),
    )


def _timeline_status_events(run_id: str, timeline: list[JsonDict]) -> list[JsonDict]:
    return [
        {
            "type": "run.tick",
            "run_id": run_id,
            "status": "running",
            "tick": int(frame.get("tick", 0) or 0),
            "message": f"Run tick {frame.get('tick', 0)}",
        }
        for frame in timeline
    ]


def _latest_timeline_tick(timeline: list[JsonDict]) -> int:
    return max((int(frame.get("tick", 0) or 0) for frame in timeline), default=0)


def _rules_for_job(job: RunJob) -> list[str]:
    if job.rules:
        return [str(item) for item in job.rules]
    defaults = scenario_defaults(job.scenario)
    return [str(item) for item in _list(defaults.get("rules"))] or ["movement"]


def _evaluation_goals_for_job(job: RunJob) -> JsonDict:
    if job.evaluation_goals:
        return dict(job.evaluation_goals)
    defaults = scenario_defaults(job.scenario)
    return _dict(defaults.get("evaluation_goals"))


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
