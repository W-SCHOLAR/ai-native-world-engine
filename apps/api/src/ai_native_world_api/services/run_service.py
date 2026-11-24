"""Run orchestration service that adapts product requests to engine calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from ai_native_world_engine.core import (
    RunConfig,
    SovereignDynamicRule,
    SovereignIntentPlan,
    World,
    apply_projection_delta,
    project_run_for_viewer,
    run,
)

from ..auth import current_principal
from ..models import RunControlState, RunRecord, RunStatus
from ..provider_config import (
    RuntimeProviderSelection,
    SovereignIntentCompilerSelection,
    create_runtime_provider_config,
    create_sovereign_intent_compiler,
)
from ..repository import RunRepository
from ..runtime_config import scenario_scheduler_config
from ..scenario_defaults import scenario_defaults


JsonDict = dict[str, Any]


class RunQueue:
    def enqueue(self, job: Any) -> JsonDict:
        ...

    def process_run(self, run_id: str) -> JsonDict:
        ...

    def request_control(
        self,
        run_id: str,
        command: str,
        reason: str = "",
    ) -> bool:
        ...


class RuntimeProviderFactory(Protocol):
    def __call__(
        self,
        rules: list[str] | None = None,
        runtime_provider: JsonDict | None = None,
    ) -> RuntimeProviderSelection:
        ...


class SovereignIntentCompilerFactory(Protocol):
    def __call__(self, intent_index: int = 1) -> SovereignIntentCompilerSelection:
        ...


class RunService:
    def __init__(
        self,
        repository: RunRepository,
        queue: RunQueue | None = None,
        runtime_provider_factory: RuntimeProviderFactory = create_runtime_provider_config,
        sovereign_compiler_factory: SovereignIntentCompilerFactory = create_sovereign_intent_compiler,
        external_worker: bool = False,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.runtime_provider_factory = runtime_provider_factory
        self.sovereign_compiler_factory = sovereign_compiler_factory
        self.external_worker = bool(external_worker)

    def list_scenarios(self) -> list[JsonDict]:
        return [scenario.to_dict() for scenario in self.repository.list_scenarios()]

    def list_runs(self) -> list[JsonDict]:
        owner_id = current_principal().user_id
        return [
            _public_run_summary(run_record)
            for run_record in self.repository.list_runs()
            if run_record.owner_id == owner_id
        ]

    def create_sync_run(
        self,
        scenario: str = "seed",
        seed: int = 7,
        ticks: int = 3,
        runtime_provider: JsonDict | None = None,
    ) -> JsonDict:
        resolved = _resolve_run_defaults(self.repository, scenario, ticks)
        run_record = RunRecord(
            id=f"run_{uuid4().hex[:12]}",
            scenario=scenario,
            seed=int(seed),
            ticks=resolved["ticks"],
            owner_id=current_principal().user_id,
            status=RunStatus.RUNNING,
            config={
                "scenario": scenario,
                "seed": int(seed),
                "ticks": resolved["ticks"],
                "rules": resolved["rules"],
                "evaluation_goals": resolved["evaluation_goals"],
            },
        )
        self.repository.save_run(run_record)
        try:
            scheduler = scenario_scheduler_config(scenario, resolved["ticks"])
            provider_selection = self.runtime_provider_factory(
                rules=resolved["rules"], runtime_provider=runtime_provider
            )
            result = run(
                RunConfig(
                    scenario=scenario,
                    seed=int(seed),
                    ticks=resolved["ticks"],
                    rules=resolved["rules"],
                    evaluation_goals=resolved["evaluation_goals"],
                    scheduler=scheduler,
                    provider=provider_selection.scheduler_provider,
                    scheduler_provider=provider_selection.scheduler_provider,
                    runtime_provider=provider_selection.metadata,
                    capture_timeline=True,
                )
            )
            result_data = result.to_dict()
            run_record.config = result_data["config"]
            run_record.snapshot = result_data["snapshot"]
            run_record.events = result_data["events"]
            run_record.traces = result_data["traces"]
            run_record.scorecard = result_data["scorecard"]
            run_record.provider_execution_report = result_data["provider_execution_report"]
            run_record.provider_attempt_report = result_data["provider_attempt_report"]
            run_record.provider_attempts = result_data["provider_attempts"]
            run_record.projection = project_run_for_viewer(result).to_dict()
            run_record.timeline = result_data["timeline"]
            run_record.status_events.extend(_timeline_status_events(run_record.id, run_record.timeline))
            run_record.provider_audits = result_data["provider_audits"]
            run_record.sovereign_intent_audits = result_data["sovereign_intent_audits"]
            run_record.memory_consolidation_report = result_data["memory_consolidation_report"]
            run_record.mark(RunStatus.COMPLETED)
            self.repository.save_final_result(run_record.id, result_data)
        except Exception as exc:  # pragma: no cover - defensive product boundary
            run_record.mark(RunStatus.FAILED, str(exc))
        self.repository.save_run(run_record)
        return _public_run_detail(run_record)

    def enqueue_run(
        self,
        scenario: str = "seed",
        seed: int = 7,
        ticks: int = 3,
        runtime_provider: JsonDict | None = None,
        require_cognition_ready: bool = False,
        run_id: str = "",
        retry_of_run_id: str = "",
        retry_attempt: int = 0,
    ) -> JsonDict:
        run_id = str(run_id or f"run_{uuid4().hex[:12]}")
        resolved = _resolve_run_defaults(self.repository, scenario, ticks)
        provider_selection = self.runtime_provider_factory(
            rules=resolved["rules"], runtime_provider=runtime_provider
        )
        if self.queue is not None:
            from ai_native_world_worker import RunJob

            self.queue.enqueue(
                RunJob(
                    run_id=run_id,
                    owner_id=current_principal().user_id,
                    scenario=scenario,
                    seed=int(seed),
                    ticks=resolved["ticks"],
                    rules=resolved["rules"],
                    evaluation_goals=resolved["evaluation_goals"],
                    runtime_provider=(
                        dict(runtime_provider)
                        if isinstance(runtime_provider, dict)
                        else provider_selection.metadata
                    ),
                    require_cognition_ready=bool(require_cognition_ready),
                    retry_of_run_id=str(retry_of_run_id),
                    retry_attempt=max(int(retry_attempt), 0),
                )
            )
            queued_record = self._owned_run(run_id)
            if queued_record is not None:
                return _public_run_summary(queued_record)
            return {"error": "run_not_found", "run_id": run_id}
        if isinstance(runtime_provider, dict) and runtime_provider.get("api_key"):
            return {
                "error": "live_provider_requires_embedded_worker",
                "message": "Browser-supplied provider credentials require embedded Worker mode.",
                "run_id": run_id,
            }
        run_record = RunRecord(
            id=run_id,
            scenario=scenario,
            seed=int(seed),
            ticks=resolved["ticks"],
            owner_id=current_principal().user_id,
            status=RunStatus.QUEUED,
            retry_of_run_id=str(retry_of_run_id),
            retry_attempt=max(int(retry_attempt), 0),
            config={
                "scenario": scenario,
                "seed": int(seed),
                "ticks": resolved["ticks"],
                "rules": resolved["rules"],
                "evaluation_goals": resolved["evaluation_goals"],
                "runtime_provider": provider_selection.metadata,
                "require_cognition_ready": bool(require_cognition_ready),
                "retry_of_run_id": str(retry_of_run_id),
                "retry_attempt": max(int(retry_attempt), 0),
            },
            runtime_state=(
                {
                    "mode": "cooperative_tick",
                    "tick_cursor": 0,
                    "target_ticks": resolved["ticks"],
                    "session_backed": False,
                    "last_step_status": "queued",
                    "externally_managed": True,
                    "bootstrap_state": (
                        {
                            "phase": "creating_world",
                            "scenario_id": scenario,
                            "provider_mode": str(
                                provider_selection.metadata.get(
                                    "mode", "deterministic"
                                )
                            ),
                            "ready": False,
                            "retryable": True,
                        }
                        if require_cognition_ready
                        else {}
                    ),
                }
                if self.external_worker
                else {}
            ),
        )
        self.repository.save_run(run_record)
        return _public_run_summary(run_record)

    def retry_run(
        self,
        run_id: str,
        runtime_provider: JsonDict | None = None,
    ) -> JsonDict:
        source = self._owned_run(run_id)
        if source is None:
            return {"error": "run_not_found", "run_id": run_id}
        if source.status != RunStatus.FAILED:
            return {
                "error": "run_not_retryable",
                "run_id": run_id,
                "status": source.status.value,
            }

        existing_replacement = (
            self._owned_run(source.replaced_by_run_id)
            if source.replaced_by_run_id
            else None
        )
        if existing_replacement is not None:
            return _retry_response(
                source.id,
                "existing_replacement",
                existing_replacement,
            )

        provider_config = (
            dict(runtime_provider)
            if isinstance(runtime_provider, dict)
            else _dict(source.config.get("runtime_provider"))
        )
        retry_attempt = max(int(source.retry_attempt), 0) + 1
        replay_safe = _bootstrap_retry_replay_safe(
            source,
            self.repository.get_run_recovery_data(source.id),
            self.queue,
        )
        target_run_id = source.id if replay_safe else f"run_{uuid4().hex[:12]}"
        retry_of_run_id = source.retry_of_run_id if replay_safe else source.id
        previous_events = list(source.status_events)
        retried_payload = self.enqueue_run(
            scenario=source.scenario,
            seed=source.seed,
            ticks=source.ticks,
            runtime_provider=provider_config,
            require_cognition_ready=bool(
                source.config.get("require_cognition_ready", True)
            ),
            run_id=target_run_id,
            retry_of_run_id=retry_of_run_id,
            retry_attempt=retry_attempt,
        )
        if retried_payload.get("error"):
            return retried_payload
        retried = self._owned_run(target_run_id)
        if retried is None:
            return {"error": "run_not_found", "run_id": target_run_id}

        timestamp = datetime.now(timezone.utc).isoformat()
        retry_event = {
            "type": "run.status",
            "run_id": retried.id,
            "status": retried.status.value,
            "message": "World bootstrap retry queued",
            "retry_disposition": "reused" if replay_safe else "replacement",
            "retry_of_run_id": retry_of_run_id,
            "retry_attempt": retry_attempt,
            "timestamp": timestamp,
        }
        if replay_safe:
            retried.status_events = [*previous_events[-90:], retry_event]
        else:
            retried.status_events.append(retry_event)
            source.replaced_by_run_id = retried.id
            source.updated_at = datetime.now(timezone.utc)
            source.status_events.append(
                {
                    "type": "run.status",
                    "run_id": source.id,
                    "status": source.status.value,
                    "message": "World bootstrap replaced for retry",
                    "replaced_by_run_id": retried.id,
                    "timestamp": timestamp,
                }
            )
            self.repository.save_run(source)
        self.repository.save_run(retried)
        return _retry_response(
            source.id,
            "reused" if replay_safe else "replacement",
            retried,
        )

    def get_run(self, run_id: str) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        payload = _public_run_detail(run_record)
        return payload

    def add_intervention(self, run_id: str, intervention: JsonDict) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        if run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            return {"error": "run_not_mutable", "run_id": run_id, "status": run_record.status.value}
        if not isinstance(intervention, dict):
            return {"error": "invalid_intervention", "run_id": run_id}
        next_intervention = dict(intervention)
        next_intervention.setdefault("id", f"intervention_{len(run_record.interventions) + 1}")
        run_record.interventions.append(next_intervention)
        run_record.config["interventions"] = run_record.interventions
        run_record.updated_at = datetime.now(timezone.utc)
        run_record.status_events.append(
            {
                "type": "run.status",
                "run_id": run_id,
                "status": run_record.status.value,
                "message": "Run intervention queued",
                "intervention_id": next_intervention["id"],
                "submitted_by": current_principal().user_id,
                "timestamp": run_record.updated_at.isoformat(),
            }
        )
        self.repository.save_run(run_record)
        return {
            "run_id": run_id,
            "status": run_record.status.value,
            "intervention": next_intervention,
            "intervention_count": len(run_record.interventions),
        }

    def add_sovereign_intent(self, run_id: str, request: JsonDict) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        if run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            return {"error": "run_not_mutable", "run_id": run_id, "status": run_record.status.value}
        text = str(request.get("text", request.get("input", ""))).strip()
        if not text:
            return {"error": "invalid_sovereign_intent", "run_id": run_id}
        scheduled_tick = int(
            request.get(
                "scheduled_tick",
                _dict(run_record.runtime_state).get("tick_cursor", len(run_record.timeline)),
            )
            or 0
        )
        actor_id = str(request.get("actor_id", "web-sovereign"))
        compiler_context: JsonDict = {}
        try:
            selection = self.sovereign_compiler_factory(intent_index=len(run_record.sovereign_intents) + 1)
            compiler_context = dict(selection.metadata)
            compiler_world = self._compiler_world(run_record)
            compiled = selection.compiler.compile(compiler_world, text, scheduled_tick=scheduled_tick)
            plan = _product_sovereign_plan(
                compiled,
                run_record,
                actor_id,
                selection.metadata,
                submitted_by=current_principal().user_id,
            )
        except Exception as exc:  # noqa: BLE001 - product ingress must persist compiler failures.
            run_record.updated_at = datetime.now(timezone.utc)
            run_record.status_events.append(
                {
                    "type": "run.status",
                    "run_id": run_id,
                    "status": run_record.status.value,
                    "message": "Sovereign intent compilation failed",
                    "code": "sovereign_intent_compilation_failed",
                    "error": str(exc),
                    "compiler": compiler_context,
                    "timestamp": run_record.updated_at.isoformat(),
                }
            )
            self.repository.save_run(run_record)
            return {
                "error": "sovereign_intent_compilation_failed",
                "run_id": run_id,
                "status": run_record.status.value,
                "message": str(exc),
                "compiler": compiler_context,
            }
        plan_data = plan.to_dict()
        run_record.sovereign_intents.append(plan_data)
        run_record.config["sovereign_intents"] = run_record.sovereign_intents
        run_record.updated_at = datetime.now(timezone.utc)
        run_record.status_events.append(
            {
                "type": "run.status",
                "run_id": run_id,
                "status": run_record.status.value,
                "message": "Sovereign intent compiled and queued",
                "sovereign_intent_id": plan.id,
                "compiler": compiler_context,
                "submitted_by": current_principal().user_id,
                "timestamp": run_record.updated_at.isoformat(),
            }
        )
        self.repository.save_run(run_record)
        return {
            "run_id": run_id,
            "status": run_record.status.value,
            "sovereign_intent": plan_data,
            "sovereign_intent_count": len(run_record.sovereign_intents),
            "compiler": compiler_context,
        }

    def control_run(self, run_id: str, command: str, reason: str = "", actor_id: str = "operator") -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        normalized = str(command).strip().lower()
        if normalized not in {"pause", "resume", "cancel"}:
            return {"error": "invalid_run_control_command", "run_id": run_id, "command": command}
        if run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            if normalized == "cancel" and run_record.control_state == RunControlState.CANCELED:
                return _control_response(run_record)
            return {
                "error": "run_not_controllable",
                "run_id": run_id,
                "status": run_record.status.value,
                "control_state": run_record.control_state.value,
            }
        if normalized == "pause":
            if run_record.control_state == RunControlState.CANCELED:
                return {"error": "run_already_canceled", "run_id": run_id}
            run_record.control(
                "pause",
                reason=reason,
                actor_id=actor_id,
                submitted_by=current_principal().user_id,
            )
        elif normalized == "resume":
            if run_record.control_state != RunControlState.PAUSED:
                return {
                    "error": "run_not_paused",
                    "run_id": run_id,
                    "control_state": run_record.control_state.value,
                }
            run_record.control(
                "resume",
                reason=reason,
                actor_id=actor_id,
                submitted_by=current_principal().user_id,
            )
        elif normalized == "cancel":
            run_record.control(
                "cancel",
                reason=reason,
                actor_id=actor_id,
                submitted_by=current_principal().user_id,
            )
            run_record.mark(RunStatus.FAILED, "Run canceled by control command")
        self.repository.save_run(run_record)
        if self.queue is not None:
            notify = getattr(self.queue, "request_control", None)
            if callable(notify):
                notify(run_id, normalized, reason)
        return _control_response(run_record)

    def get_projection(self, run_id: str) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        final_result = self.repository.get_final_result(run_id)
        if final_result is not None and isinstance(final_result.get("projection"), dict):
            return _dict(final_result.get("projection"))
        keyframe = self.repository.get_latest_projection(run_id)
        if keyframe is None:
            return run_record.projection
        state = keyframe
        keyframe_sequence = int(keyframe.get("sequence", 0) or 0)
        for delta in self.repository.list_projection_deltas(
            run_id, after=keyframe_sequence, limit=0
        ):
            state = apply_projection_delta(state, delta)
        snapshot = _dict(state.get("world_state"))
        events = self.repository.list_run_events(run_id, after=0, limit=0)
        traces = self.repository.list_run_traces(run_id, after=0, limit=0)
        snapshot["events"] = events
        snapshot["deltas"] = [
            event for event in events if event.get("kind") == "state_delta"
        ]
        snapshot["traces"] = traces
        projection = project_run_for_viewer(
            {
                "snapshot": snapshot,
                "events": events,
                "traces": traces,
                "scorecard": {},
            }
        ).to_dict()
        projection["speech_bubbles"] = _merge_speech_bubbles(
            projection.get("speech_bubbles"),
            state.get("speech_bubbles"),
        )
        return projection

    def consume_thought_schedules(
        self,
        run_id: str,
        sequences: list[int],
        occurrence_ids: list[str] | None = None,
    ) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        consume = getattr(self.repository, "consume_thought_schedules", None)
        if not callable(consume):
            return {"error": "presentation_consume_unavailable", "run_id": run_id}
        normalized = sorted({int(value) for value in sequences if int(value) > 0})
        normalized_occurrences = sorted(
            {str(value) for value in (occurrence_ids or []) if str(value)}
        )
        occurrence_consume = getattr(
            self.repository, "consume_thought_occurrences", None
        )
        occurrence_count = (
            int(occurrence_consume(run_id, normalized_occurrences))
            if normalized_occurrences and callable(occurrence_consume)
            else 0
        )
        return {
            "run_id": run_id,
            "consumed_count": int(consume(run_id, normalized)) + occurrence_count,
            "consumed_sequences": normalized,
            "consumed_occurrence_ids": normalized_occurrences,
        }

    def get_timeline(self, run_id: str, cursor: int = 0, limit: int = 50) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        if _dict(run_record.runtime_state).get("mode") == "cooperative_tick":
            deltas = self.repository.list_projection_deltas(
                run_id, after=0, limit=0
            )
            frames = [
                {
                    "sequence": int(delta.get("sequence", 0) or 0),
                    "tick": int(delta.get("tick", 0) or 0),
                    "projection_delta": delta,
                }
                for delta in deltas
            ]
        else:
            frames = _normalized_timeline_frames(run_record.timeline)
        page = _cursor_page(frames, cursor, limit)
        return {
            "run_id": run_id,
            "status": run_record.status.value,
            "cursor": page["cursor"],
            "next_cursor": page["next_cursor"],
            "retained_from_cursor": page["retained_from_cursor"],
            "retained_to_cursor": page["retained_to_cursor"],
            "cursor_expired": page["cursor_expired"],
            "has_more": page["has_more"],
            "timeline": page["items"],
        }

    def get_stream(self, run_id: str, cursor: int = 0, limit: int = 50) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        if _dict(run_record.runtime_state).get("mode") == "cooperative_tick":
            frames = [
                {
                    "type": "run.tick",
                    "run_id": run_id,
                    "sequence": int(delta.get("sequence", 0) or 0),
                    "tick": int(delta.get("tick", 0) or 0),
                    "status": RunStatus.RUNNING.value,
                    "projection_delta": delta,
                }
                for delta in self.repository.list_projection_deltas(
                    run_id, after=0, limit=0
                )
            ]
            if run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
                latest = max(
                    (int(frame.get("sequence", 0) or 0) for frame in frames),
                    default=0,
                )
                frames.append(
                    {
                        "type": "run.completed"
                        if run_record.status == RunStatus.COMPLETED
                        else "run.failed",
                        "run_id": run_id,
                        "sequence": latest + 1,
                        "tick": int(
                            _dict(run_record.runtime_state).get("tick_cursor", 0)
                            or 0
                        ),
                        "status": run_record.status.value,
                        "error": run_record.error,
                    }
                )
        else:
            frames = _run_stream_frames(run_record)
        page = _cursor_page(frames, cursor, limit)
        return {
            "run_id": run_id,
            "status": run_record.status.value,
            "cursor": page["cursor"],
            "next_cursor": page["next_cursor"],
            "retained_from_cursor": page["retained_from_cursor"],
            "retained_to_cursor": page["retained_to_cursor"],
            "cursor_expired": page["cursor_expired"],
            "has_more": page["has_more"],
            "completed": run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED},
            "control_state": run_record.control_state.value,
            "runtime_state": _public_runtime_state(run_record.runtime_state),
            "bootstrap_state": _dict(
                _public_runtime_state(run_record.runtime_state).get(
                    "bootstrap_state"
                )
            ),
            "updates": page["items"],
        }

    def advance_run(self, run_id: str) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        before_tick = int(_dict(run_record.runtime_state).get("tick_cursor", 0) or 0)
        if run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            return _advance_response(run_record, before_tick, before_tick)
        if run_record.control_state != RunControlState.ACTIVE:
            return _advance_response(run_record, before_tick, before_tick)
        if self.external_worker:
            return {
                **_advance_response(run_record, before_tick, before_tick),
                "externally_managed": True,
            }
        if self.queue is None:
            return {"error": "run_queue_unavailable", "run_id": run_id, "status": run_record.status.value}
        if _dict(run_record.runtime_state).get("mode") != "cooperative_tick":
            return {"error": "run_not_cooperative", "run_id": run_id, "status": run_record.status.value}
        process_run = getattr(self.queue, "process_run", None)
        if not callable(process_run):
            return {"error": "run_queue_unavailable", "run_id": run_id, "status": run_record.status.value}
        process_run(run_record.id)
        updated = self._owned_run(run_id)
        if updated is None:
            return {"error": "run_not_found", "run_id": run_id}
        after_tick = int(_dict(updated.runtime_state).get("tick_cursor", before_tick) or before_tick)
        return _advance_response(updated, before_tick, after_tick)

    def get_traces(self, run_id: str, cursor: int = 0, limit: int = 1000) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        traces = (
            self.repository.list_run_traces(run_id, after=cursor, limit=limit)
            if _dict(run_record.runtime_state).get("mode") == "cooperative_tick"
            else run_record.traces[max(int(cursor), 0) :][: max(int(limit), 1)]
        )
        return {
            "run_id": run_id,
            "cursor": max(int(cursor), 0),
            "next_cursor": max(int(cursor), 0) + len(traces),
            "traces": traces,
        }

    def get_events(self, run_id: str, cursor: int = 0, limit: int = 1000) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        events = (
            self.repository.list_run_events(run_id, after=cursor, limit=limit)
            if _dict(run_record.runtime_state).get("mode") == "cooperative_tick"
            else [
                event
                for event in run_record.events
                if int(event.get("sequence", 0) or 0) > max(int(cursor), 0)
            ][: max(int(limit), 1)]
        )
        return {
            "run_id": run_id,
            "cursor": max(int(cursor), 0),
            "next_cursor": int(events[-1].get("sequence", cursor) or cursor)
            if events
            else max(int(cursor), 0),
            "events": events,
            "status_events": run_record.status_events,
        }

    def get_final_result(self, run_id: str) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        result = self.repository.get_final_result(run_id)
        if result is None:
            return {
                "error": "final_result_not_available",
                "run_id": run_id,
                "status": run_record.status.value,
            }
        return {"run_id": run_id, "result": result}

    def get_status_events(self, run_id: str) -> JsonDict:
        run_record = self._owned_run(run_id)
        if run_record is None:
            return {"error": "run_not_found", "run_id": run_id}
        return {"run_id": run_id, "events": run_record.status_events}

    def _owned_run(self, run_id: str) -> RunRecord | None:
        run_record = self.repository.get_run(run_id)
        if run_record is None or run_record.owner_id != current_principal().user_id:
            return None
        return run_record

    def _compiler_world(self, run_record: RunRecord) -> World:
        if _dict(run_record.runtime_state).get("mode") != "cooperative_tick":
            return _sovereign_compiler_world(run_record)
        keyframe = self.repository.get_latest_projection(run_record.id)
        if keyframe is None:
            return _sovereign_compiler_world(run_record)
        state = keyframe
        sequence = int(keyframe.get("sequence", 0) or 0)
        for delta in self.repository.list_projection_deltas(
            run_record.id, after=sequence, limit=0
        ):
            state = apply_projection_delta(state, delta)
        snapshot = _dict(state.get("world_state"))
        if snapshot.get("id"):
            return World.from_snapshot(snapshot)
        return _sovereign_compiler_world(run_record)


def _timeline_status_events(run_id: str, timeline: list[JsonDict]) -> list[JsonDict]:
    return [
        {
            "type": "run.tick",
            "run_id": run_id,
            "status": RunStatus.RUNNING.value,
            "tick": int(frame.get("tick", 0) or 0),
            "message": f"Run tick {frame.get('tick', 0)}",
        }
        for frame in timeline
    ]


def _merge_speech_bubbles(*groups: object, limit: int = 256) -> list[JsonDict]:
    """Merge delivery-only speech visuals without promoting them to world events."""

    keyed: dict[str, JsonDict] = {}
    for group in groups:
        for raw_item in _list(group):
            item = _dict(raw_item)
            if not item:
                continue
            key = str(
                item.get("speech_event_id")
                or item.get("occurrence_id")
                or item.get("sequence")
                or f"{item.get('node_id', '')}:{item.get('text', '')}"
            )
            keyed[key] = item
    return list(keyed.values())[-max(int(limit), 1) :]


def _resolve_run_defaults(repository: RunRepository, scenario: str, ticks: int) -> JsonDict:
    scenario_record = repository.get_scenario(scenario)
    defaults = dict(scenario_record.defaults) if scenario_record is not None else scenario_defaults(scenario)
    rules = [str(item) for item in _list(defaults.get("rules"))] or ["movement"]
    return {
        "ticks": int(ticks),
        "rules": rules,
        "evaluation_goals": _dict(defaults.get("evaluation_goals")),
    }


def _control_response(run_record: RunRecord) -> JsonDict:
    return {
        "run_id": run_record.id,
        "status": run_record.status.value,
        "control_state": run_record.control_state.value,
        "control_events": run_record.control_events,
        "error": run_record.error,
    }


def _retry_response(
    source_run_id: str,
    disposition: str,
    run_record: RunRecord,
) -> JsonDict:
    return {
        "source_run_id": str(source_run_id),
        "retry_disposition": str(disposition),
        "run": _public_run_detail(run_record),
    }


def _bootstrap_retry_replay_safe(
    run_record: RunRecord,
    recovery: JsonDict,
    queue: RunQueue | None,
) -> bool:
    """Allow same-id retry only before any durable or in-flight cognition work."""

    state = _dict(run_record.runtime_state)
    bootstrap = _dict(state.get("bootstrap_state"))
    if str(bootstrap.get("phase", "")) not in {"creating_world", "failed"}:
        return False
    if not bool(bootstrap.get("retryable", False)):
        return False
    if run_record.control_state != RunControlState.ACTIVE:
        return False
    if int(state.get("tick_cursor", 0) or 0) != 0:
        return False
    if int(bootstrap.get("accepted_provider_output_count", 0) or 0) != 0:
        return False
    for key in (
        "provider_job_ids",
        "committed_pressure_ids",
        "grounded_action_sequences",
        "accepted_thought_sequences",
    ):
        if _list(bootstrap.get(key)):
            return False
    if bootstrap.get("ready_projection_sequence"):
        return False
    if run_record.snapshot or run_record.events or run_record.traces or run_record.projection:
        return False
    if any(value for value in recovery.values()):
        return False
    if queue is not None:
        sessions = getattr(queue, "sessions", {})
        if isinstance(sessions, dict) and run_record.id in sessions:
            return False
        pending = getattr(queue, "pending", [])
        if any(getattr(job, "run_id", "") == run_record.id for job in pending):
            return False
    return True


def _advance_response(run_record: RunRecord, before_tick: int, after_tick: int) -> JsonDict:
    return {
        "run_id": run_record.id,
        "status": run_record.status.value,
        "completed": run_record.status in {RunStatus.COMPLETED, RunStatus.FAILED},
        "control_state": run_record.control_state.value,
        "runtime_state": _public_runtime_state(run_record.runtime_state),
        "bootstrap_state": _dict(
            _public_runtime_state(run_record.runtime_state).get("bootstrap_state")
        ),
        "advanced": after_tick > before_tick,
        "previous_tick_cursor": before_tick,
        "tick_cursor": after_tick,
        "error": run_record.error,
    }


def _run_stream_frames(run_record: RunRecord) -> list[JsonDict]:
    status_by_tick = {
        int(event.get("tick", 0) or 0): event
        for event in run_record.status_events
        if event.get("type") == "run.tick"
    }
    frames: list[JsonDict] = []
    timeline = _normalized_timeline_frames(run_record.timeline)
    for frame in timeline:
        tick = int(frame.get("tick", 0) or 0)
        stream_frame = {
            "type": "run.tick",
            "run_id": run_record.id,
            "sequence": int(frame.get("sequence", tick) or tick),
            "status": RunStatus.RUNNING.value,
            "tick": tick,
            "timeline_frame": frame,
        }
        if tick in status_by_tick:
            stream_frame["status_event"] = status_by_tick[tick]
        frames.append(stream_frame)
    terminal_events = [
        event
        for event in run_record.status_events
        if event.get("type") in {"run.completed", "run.failed"}
    ]
    if terminal_events:
        event = terminal_events[-1]
        latest_sequence = max((int(frame.get("sequence", 0) or 0) for frame in timeline), default=0)
        terminal_frame = {
            "type": str(event.get("type", "run.completed")),
            "run_id": run_record.id,
            "sequence": latest_sequence + 1,
            "status": run_record.status.value,
            "tick": int(run_record.snapshot.get("tick", run_record.ticks) or run_record.ticks)
            if isinstance(run_record.snapshot, dict)
            else run_record.ticks,
            "status_event": event,
            "error": run_record.error,
        }
        if run_record.projection and not frames:
            terminal_frame["projection"] = run_record.projection
        frames.append(terminal_frame)
    return frames


def _normalized_timeline_frames(timeline: list[JsonDict]) -> list[JsonDict]:
    normalized: list[JsonDict] = []
    previous_sequence = 0
    for index, raw_frame in enumerate(timeline):
        frame = dict(raw_frame)
        sequence = int(frame.get("sequence", frame.get("tick", index + 1)) or index + 1)
        if sequence <= previous_sequence:
            sequence = previous_sequence + 1
        frame["sequence"] = sequence
        previous_sequence = sequence
        normalized.append(frame)
    return normalized


def _cursor_page(frames: list[JsonDict], cursor: int, limit: int) -> JsonDict:
    ordered = sorted(frames, key=lambda frame: int(frame.get("sequence", 0) or 0))
    safe_cursor = max(int(cursor), 0)
    safe_limit = max(min(int(limit), 200), 1)
    retained_from = int(ordered[0].get("sequence", 0) or 0) if ordered else 0
    retained_to = int(ordered[-1].get("sequence", 0) or 0) if ordered else 0
    cursor_expired = bool(ordered and safe_cursor < retained_from - 1)
    effective_cursor = retained_from - 1 if cursor_expired else safe_cursor
    available = [frame for frame in ordered if int(frame.get("sequence", 0) or 0) > effective_cursor]
    items = available[:safe_limit]
    next_cursor = int(items[-1].get("sequence", effective_cursor) or effective_cursor) if items else safe_cursor
    return {
        "cursor": safe_cursor,
        "next_cursor": next_cursor,
        "retained_from_cursor": retained_from,
        "retained_to_cursor": retained_to,
        "cursor_expired": cursor_expired,
        "has_more": len(available) > len(items),
        "items": items,
    }


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> JsonDict:
    return dict(value) if isinstance(value, dict) else {}


def _public_runtime_state(value: object) -> JsonDict:
    state = _dict(value)
    forbidden = {
        "session_checkpoint",
        "checkpoint",
        "world_snapshot",
        "pending_context",
        "context_packet",
    }
    public = {key: item for key, item in state.items() if key not in forbidden}
    pending = public.get("provider_pending")
    if isinstance(pending, list):
        public["provider_pending"] = [
            {
                key: item
                for key, item in entry.items()
                if str(key).lower()
                not in {
                    "authorization",
                    "context_packet",
                    "headers",
                    "prompt",
                    "response",
                    "snapshot",
                }
            }
            for entry in pending[-32:]
            if isinstance(entry, dict)
        ]
    return public


def _public_run_summary(run_record: RunRecord) -> JsonDict:
    payload = run_record.to_summary_dict()
    payload["runtime_state"] = _public_runtime_state(run_record.runtime_state)
    return payload


def _public_run_detail(run_record: RunRecord) -> JsonDict:
    if _dict(run_record.runtime_state).get("mode") == "cooperative_tick":
        return {
            **_public_run_summary(run_record),
            "config": run_record.config,
            "status_events": run_record.status_events[-100:],
            "interventions": run_record.interventions,
            "sovereign_intents": run_record.sovereign_intents,
            "control_events": run_record.control_events[-100:],
            "final_result_available": bool(
                run_record.runtime_state.get("final_result_available", False)
            ),
        }
    payload = run_record.to_detail_dict()
    payload["runtime_state"] = _public_runtime_state(run_record.runtime_state)
    return payload


def _sovereign_compiler_world(run_record: RunRecord) -> World:
    if isinstance(run_record.snapshot, dict) and run_record.snapshot.get("id"):
        return World.from_snapshot(run_record.snapshot)
    scenario_kwargs: JsonDict = {"seed": run_record.seed}
    scenario_path = str(run_record.config.get("scenario_path", ""))
    if scenario_path:
        scenario_kwargs["scenario_path"] = scenario_path
    return World.scenario(run_record.scenario, **scenario_kwargs)


def _product_sovereign_plan(
    plan: SovereignIntentPlan,
    run_record: RunRecord,
    actor_id: str,
    compiler_metadata: JsonDict,
    submitted_by: str = "local",
) -> SovereignIntentPlan:
    existing_ids = {str(item.get("id", "")) for item in run_record.sovereign_intents}
    plan_id = plan.id
    suffix = 2
    while plan_id in existing_ids:
        plan_id = f"{plan.id}-{suffix}"
        suffix += 1
    rule_suffix = "" if plan_id == plan.id else f"-{suffix - 1}"
    dynamic_rules = [
        SovereignDynamicRule(
            id=f"{rule.id}{rule_suffix}",
            action=rule.action,
            summary=rule.summary,
            trigger=dict(rule.trigger),
            effects=list(rule.effects),
            score=rule.score,
            ttl=rule.ttl,
            once_per_node=rule.once_per_node,
            metadata=dict(rule.metadata),
        )
        for rule in plan.dynamic_rules
    ]
    metadata = dict(plan.metadata)
    metadata.update(
        {
            "actor_id": actor_id,
            "submitted_by": submitted_by,
            "compiler": str(compiler_metadata.get("mode", "")),
            "product_compiler": dict(compiler_metadata),
        }
    )
    return SovereignIntentPlan(
        id=plan_id,
        user_input=plan.user_input,
        title=plan.title,
        summary=plan.summary,
        impact_level=plan.impact_level,
        scheduled_tick=plan.scheduled_tick,
        initial_effects=list(plan.initial_effects),
        dynamic_rules=dynamic_rules,
        metadata=metadata,
    )
