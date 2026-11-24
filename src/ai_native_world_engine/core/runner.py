"""Run harness for reproducible world experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .archive import WorldArchive
from .action_grounding import ENTERPRISE_AGENT_RULES
from .agent_context import AgentContextPacketBuilder
from .events import TraceRecord, json_copy
from .evaluation import evaluate_run
from .feedback import APPLY_AUTHORITATIVE, ActionFeedback, FeedbackIngestor, WorldEffect
from .interventions import (
    WorldIntervention,
    compile_world_intervention,
    is_structured_world_intervention,
)
from .incremental import (
    COMPACT_CHECKPOINT_SCHEMA,
    IncrementalRunResult,
    TickCommit,
    compact_world_snapshot,
    replay_tick_commits,
    world_from_compact_snapshot,
    world_state_delta,
)
from .memory import (
    AiCausalityTraceLedger,
    PressureActionTraceLedger,
    ProviderOutcomeLedger,
    SocialRippleLedger,
    WorldMemoryConsolidator,
)
from .pressure import StructuredPressureView
from .provider_governance import (
    GovernedProviderRunner,
    ProviderPolicyProfile,
    ProviderRegistry,
)
from .provider_profiles import ProviderExecutionProfiler
from .provider_telemetry import (
    accumulate_provider_usage,
    empty_provider_usage_totals,
    merge_provider_attempts,
    provider_attempt_totals,
    provider_attempts_from_output,
)
from .providers import (
    AgentProvider,
    DeterministicPressureProvider,
    ProviderContext,
    ProviderOutput,
)
from .rules import (
    MOVEMENT_CORE_RULES,
    WORLD_ECOSYSTEM_RULES,
    RuleEngineSet,
    RulePackage,
    expand_rule_names,
)
from .scheduler import (
    SCHEDULED_AGENT_SCENARIOS,
    AgentJob,
    AgentScheduler,
    AgentSchedulerConfig,
    default_agent_scheduler_config,
)
from .scheduler_jobs import (
    enterprise_event_triggered_lens_jobs,
    enterprise_pressure_triggered_jobs,
    scenario_agent_jobs,
)
from .sovereign_intent import (
    SovereignDynamicRulePackage,
    SovereignIntentPlan,
    apply_sovereign_intent_plan,
)
from .world import World
from .world_director import (
    DeterministicWorldDirectorProvider,
    WORLD_DIRECTOR_SOURCE,
    WorldDirectorConfig,
)


JsonDict = dict[str, Any]
DEFAULT_TIMELINE_RETENTION = 64
DEFAULT_CAUSAL_SETTLE_TICKS = 3
RUN_PHASES = {
    "running",
    "provider_draining",
    "provider_canceling",
    "causal_settling",
    "completed",
    "stopped",
    "canceled",
}


@dataclass(slots=True)
class RunConfig:
    scenario: str = "seed"
    seed: int = 7
    ticks: int = 3
    rules: list[str] | None = None
    provider: AgentProvider | None = None
    provider_params: JsonDict = field(default_factory=dict)
    scheduler_provider: AgentProvider | None = None
    runtime_provider: JsonDict = field(default_factory=dict)
    require_cognition_ready: bool = False
    scenario_path: str = ""
    scheduler: AgentSchedulerConfig | None = None
    govern_provider_output: bool = False
    provider_id: str = "default"
    allowed_rule_names: list[str] = field(default_factory=list)
    allowed_relationship_types: list[str] = field(default_factory=list)
    capture_timeline: bool = False
    timeline_retention: int = DEFAULT_TIMELINE_RETENTION
    causal_settle_ticks: int = DEFAULT_CAUSAL_SETTLE_TICKS
    provider_drain_timeout_seconds: float = 60.0
    interventions: list[JsonDict] = field(default_factory=list)
    memory_consolidation: JsonDict = field(default_factory=dict)
    provider_profile: JsonDict = field(default_factory=dict)
    evaluation_goals: JsonDict = field(default_factory=dict)
    world_director: JsonDict = field(default_factory=dict)
    external_rule_packages: list[RulePackage] = field(default_factory=list)
    sovereign_intents: list[JsonDict | SovereignIntentPlan] = field(
        default_factory=list
    )

    @classmethod
    def from_dict(cls, value: JsonDict) -> "RunConfig":
        scheduler_data = _dict(value.get("scheduler"))
        scheduler = None
        if scheduler_data.get("enabled"):
            scheduler = AgentSchedulerConfig.from_dict(scheduler_data)
        return cls(
            scenario=str(value.get("scenario", "seed")),
            seed=int(value.get("seed", 7) or 7),
            ticks=int(value.get("ticks", 3) or 3),
            rules=[str(item) for item in _list(value.get("rules"))]
            if "rules" in value
            else None,
            provider_params=_dict(value.get("provider_params")),
            runtime_provider=_dict(value.get("runtime_provider")),
            require_cognition_ready=bool(
                value.get("require_cognition_ready", False)
            ),
            scenario_path=str(value.get("scenario_path", "")),
            scheduler=scheduler,
            govern_provider_output=bool(value.get("govern_provider_output", False)),
            provider_id=str(value.get("provider_id", "default")),
            allowed_rule_names=[
                str(item) for item in _list(value.get("allowed_rule_names"))
            ],
            allowed_relationship_types=[
                str(item) for item in _list(value.get("allowed_relationship_types"))
            ],
            capture_timeline=bool(value.get("capture_timeline", False)),
            timeline_retention=max(
                int(
                    value.get("timeline_retention", DEFAULT_TIMELINE_RETENTION)
                    or DEFAULT_TIMELINE_RETENTION
                ),
                1,
            ),
            causal_settle_ticks=max(
                int(
                    value.get(
                        "causal_settle_ticks", DEFAULT_CAUSAL_SETTLE_TICKS
                    )
                    or 0
                ),
                0,
            ),
            provider_drain_timeout_seconds=max(
                float(value.get("provider_drain_timeout_seconds", 60.0) or 0.0),
                0.0,
            ),
            interventions=[
                json_copy(item)
                for item in _list(value.get("interventions"))
                if isinstance(item, dict)
            ],
            memory_consolidation=_dict(value.get("memory_consolidation")),
            provider_profile=_dict(value.get("provider_profile")),
            evaluation_goals=_dict(value.get("evaluation_goals")),
            world_director=_dict(value.get("world_director")),
            sovereign_intents=[
                json_copy(item)
                for item in _list(value.get("sovereign_intents"))
                if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> JsonDict:
        provider = self.provider or DeterministicPressureProvider(
            **self.provider_params
        )
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "ticks": self.ticks,
            "rules": json_copy(resolve_rule_names(self.scenario, self.rules)),
            "provider": provider.name,
            "provider_params": json_copy(self.provider_params),
            "scheduler_provider": self.scheduler_provider.name
            if self.scheduler_provider is not None
            else "",
            "runtime_provider": json_copy(self.runtime_provider),
            "require_cognition_ready": bool(self.require_cognition_ready),
            "scenario_path": self.scenario_path,
            "scheduler": self.scheduler.to_dict()
            if self.scheduler
            else {"enabled": False},
            "govern_provider_output": self.govern_provider_output,
            "provider_id": self.provider_id,
            "allowed_rule_names": json_copy(self.allowed_rule_names),
            "allowed_relationship_types": json_copy(self.allowed_relationship_types),
            "capture_timeline": self.capture_timeline,
            "timeline_retention": max(int(self.timeline_retention), 1),
            "causal_settle_ticks": max(int(self.causal_settle_ticks), 0),
            "provider_drain_timeout_seconds": max(
                float(self.provider_drain_timeout_seconds), 0.0
            ),
            "interventions": json_copy(self.interventions),
            "memory_consolidation": json_copy(self.memory_consolidation),
            "provider_profile": json_copy(self.provider_profile),
            "evaluation_goals": json_copy(self.evaluation_goals),
            "world_director": _resolved_world_director_config(
                self.scenario, self.world_director
            ),
            "external_rule_packages": [
                _rule_package_name(package)
                for package in resolve_external_rule_packages(
                    self.scenario,
                    self.external_rule_packages,
                    resolve_rule_names(self.scenario, self.rules),
                )
            ],
            "sovereign_intents": [
                _sovereign_intent_dict(item) for item in self.sovereign_intents
            ],
        }


@dataclass(slots=True)
class RunResult:
    config: JsonDict
    snapshot: JsonDict
    pressure_view: JsonDict
    pressure_action_report: JsonDict
    ai_causality_report: JsonDict
    provider_outcome_report: JsonDict
    provider_execution_report: JsonDict
    provider_attempt_report: JsonDict
    scorecard: JsonDict
    provider_outputs: list[JsonDict]
    provider_attempts: list[JsonDict]
    provider_audits: list[JsonDict]
    scheduler_status: JsonDict
    events: list[JsonDict]
    traces: list[JsonDict]
    timeline: list[JsonDict] = field(default_factory=list)
    intervention_audits: list[JsonDict] = field(default_factory=list)
    memory_consolidation_report: list[JsonDict] = field(default_factory=list)
    sovereign_intent_audits: list[JsonDict] = field(default_factory=list)
    social_ripples: JsonDict = field(default_factory=dict)
    world_archive: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "config": json_copy(self.config),
            "snapshot": json_copy(self.snapshot),
            "pressure_view": json_copy(self.pressure_view),
            "pressure_action_report": json_copy(self.pressure_action_report),
            "ai_causality_report": json_copy(self.ai_causality_report),
            "provider_outcome_report": json_copy(self.provider_outcome_report),
            "provider_execution_report": json_copy(self.provider_execution_report),
            "provider_attempt_report": json_copy(self.provider_attempt_report),
            "scorecard": json_copy(self.scorecard),
            "provider_outputs": json_copy(self.provider_outputs),
            "provider_attempts": json_copy(self.provider_attempts),
            "provider_audits": json_copy(self.provider_audits),
            "scheduler_status": json_copy(self.scheduler_status),
            "events": json_copy(self.events),
            "traces": json_copy(self.traces),
            "timeline": json_copy(self.timeline),
            "intervention_audits": json_copy(self.intervention_audits),
            "memory_consolidation_report": json_copy(self.memory_consolidation_report),
            "sovereign_intent_audits": json_copy(self.sovereign_intent_audits),
            "social_ripples": json_copy(self.social_ripples),
            "world_archive": json_copy(self.world_archive),
        }


def run(config: RunConfig | None = None) -> RunResult:
    return RunSession(config).run_to_end().result()


def default_rules_for_scenario(scenario: str) -> list[str]:
    if str(scenario) == "compound_crisis":
        return json_copy(WORLD_ECOSYSTEM_RULES)
    if str(scenario) == "tribe_survival":
        return ["movement", "combat", "speak"]
    if str(scenario) == "enterprise_earth":
        return json_copy(ENTERPRISE_AGENT_RULES)
    return json_copy(MOVEMENT_CORE_RULES)


def resolve_rule_names(scenario: str, rules: list[str] | None) -> list[str]:
    if rules is None:
        return expand_rule_names(default_rules_for_scenario(scenario))
    return expand_rule_names([str(item) for item in rules])


def resolve_external_rule_packages(
    scenario: str,
    packages: list[RulePackage] | None = None,
    rule_names: list[str] | None = None,
) -> list[RulePackage]:
    resolved: list[RulePackage] = []
    if str(scenario) == "enterprise_earth" and (
        rule_names is None or "speak" in rule_names
    ):
        from ai_native_world_engine.scenarios.planet_actions import (
            planet_rule_packages,
        )

        resolved.extend(planet_rule_packages())  # type: ignore[arg-type]
    if str(scenario) == "tribe_survival":
        from ai_native_world_engine.scenarios.tribe_survival import (
            TribeSurvivalRulePackage,
        )
        from ai_native_world_engine.scenarios.tribe_activities import (
            TribeActivityRulePackage,
        )

        resolved.extend([TribeActivityRulePackage(), TribeSurvivalRulePackage()])
    resolved.extend(packages or [])
    deduplicated: list[RulePackage] = []
    seen: set[str] = set()
    for package in resolved:
        name = _rule_package_name(package)
        if name in seen:
            continue
        seen.add(name)
        deduplicated.append(package)
    return deduplicated


class RunSession:
    def __init__(self, config: RunConfig | None = None) -> None:
        self.config = config or RunConfig()
        self.provider = self.config.provider or DeterministicPressureProvider(
            **self.config.provider_params
        )
        self.provider_profile = _provider_profile(self.config.provider_profile)
        scenario_kwargs: JsonDict = {"seed": self.config.seed}
        if self.config.scenario_path:
            scenario_kwargs["scenario_path"] = self.config.scenario_path
        self.world = World.scenario(self.config.scenario, **scenario_kwargs)
        self.rules = resolve_rule_names(self.config.scenario, self.config.rules)
        self.external_rule_packages = resolve_external_rule_packages(
            self.config.scenario,
            self.config.external_rule_packages,
            self.rules,
        )
        self.rule_engine = RuleEngineSet.from_scenario(
            self.rules, extra_packages=self.external_rule_packages
        )
        self.ingestor = FeedbackIngestor()
        self.world_director = _world_director_for_config(self.config)
        self.provider_outputs: list[JsonDict] = []
        self.provider_attempts: list[JsonDict] = []
        self.provider_usage_totals: JsonDict = empty_provider_usage_totals()
        self.dropped_provider_attempt_count = 0
        self.provider_audits: list[JsonDict] = []
        self.intervention_audits: list[JsonDict] = []
        self.memory_consolidation_report: list[JsonDict] = []
        self.sovereign_intent_audits: list[JsonDict] = []
        self._applied_sovereign_intent_ids: set[str] = set()
        scheduler_config = self.config.scheduler
        if (
            scheduler_config is None
            and self.config.provider is None
            and self.config.scenario in SCHEDULED_AGENT_SCENARIOS
        ):
            scheduler_config = default_agent_scheduler_config(
                self.config.scenario, self.config.ticks
            )
            self.config.scheduler = scheduler_config
        self.scheduler = (
            AgentScheduler(scheduler_config)
            if scheduler_config and scheduler_config.enabled
            else None
        )
        self.timeline: list[JsonDict] = []
        self._timeline_event_count = 0
        self._timeline_trace_count = 0
        self._timeline_sequence = 0
        self.target_ticks = max(int(self.config.ticks), 0)
        self.phase = "running" if self.target_ticks > 0 else "completed"
        self.stop_requested = False
        self.lifecycle_reason = ""
        self.settle_ticks_completed = 0
        self._commit_sequence = 0
        self._event_cursor = 0
        self._presentation_cursor = 0
        self._trace_cursor = 0
        self._provider_output_cursor = 0
        self._provider_audit_cursor = 0
        self._intervention_audit_cursor = 0
        self._memory_consolidation_cursor = 0
        self._sovereign_intent_audit_cursor = 0
        self._last_committed_world_state = compact_world_snapshot(self.world)
        if self.scheduler:
            self.scheduler.enqueue_many(
                scenario_agent_jobs(
                    self.world,
                    rule=str(self.config.provider_params.get("rule", "move")),
                    include_static_lenses=not self.scheduler.config.event_triggered_lenses,
                    provider_override=self.config.scheduler_provider,
                )
            )
        self._last_committed_scheduler_state = (
            _bounded_scheduler_state(self.scheduler.checkpoint_state())
            if self.scheduler
            else {}
        )
        self.bootstrap_state = self._initial_bootstrap_state()

    @property
    def completed(self) -> bool:
        return self.phase == "completed"

    @property
    def terminal(self) -> bool:
        return self.phase in {"completed", "stopped", "canceled"}

    def request_stop(
        self,
        reason: str = "run stop requested",
        deadline_seconds: float | None = None,
    ) -> None:
        if self.terminal:
            return
        self.stop_requested = True
        self.lifecycle_reason = str(reason)
        if self.scheduler:
            self.scheduler.begin_drain(
                self.config.provider_drain_timeout_seconds
                if deadline_seconds is None
                else deadline_seconds,
                reason,
            )
            self.phase = "provider_draining"
        else:
            self.phase = "stopped"

    def request_cancel(self, reason: str = "run canceled") -> None:
        if self.terminal:
            return
        self.lifecycle_reason = str(reason)
        if (
            self.config.require_cognition_ready
            and self.bootstrap_state.get("phase") not in {"ready", "legacy_ready"}
        ):
            self._set_bootstrap_phase(
                "canceled",
                ready=False,
                retryable=True,
                error_code="initial_cognition_canceled",
                error_message=str(reason),
            )
        if self.scheduler:
            self.scheduler.cancel_pending(reason)
            self.phase = (
                "provider_canceling"
                if self.scheduler.has_pending_provider_jobs
                else "canceled"
            )
        else:
            self.phase = "canceled"

    def resume(self) -> None:
        """Resume a recoverable graceful stop without replacing the session owner."""

        if self.phase != "stopped":
            return
        if self.scheduler:
            self.scheduler.resume_accepting()
            if not self.scheduler.accepting_jobs:
                raise RuntimeError("stopped scheduler cannot be resumed")
        self.stop_requested = False
        self.lifecycle_reason = ""
        self.phase = "running"

    def close(self, reason: str = "run session closed") -> None:
        if self.scheduler:
            self.scheduler.close(reason)

    def step(self) -> bool:
        if self.terminal:
            return False
        if self.phase == "provider_canceling":
            if self.scheduler:
                self._record_discarded_scheduler_outputs(
                    self.scheduler.lifecycle_step(self.world)
                )
                if self.scheduler.has_pending_provider_jobs:
                    self.scheduler.close(self.lifecycle_reason or "run canceled")
            self.phase = "canceled"
            return True
        if self.phase != "running" or self.world.tick >= self.target_ticks:
            return self._step_completion_phase()
        bootstrap_pending = bool(
            self.config.require_cognition_ready
            and self.bootstrap_state.get("phase") != "ready"
        )
        if bootstrap_pending:
            if _bootstrap_deadline_expired(self.bootstrap_state):
                if self.scheduler:
                    self.scheduler.cancel_pending(
                        "initial cognition deadline exceeded"
                    )
                self._set_bootstrap_phase(
                    "timed_out",
                    ready=False,
                    retryable=True,
                    error_code="initial_provider_timeout",
                    error_message=(
                        "The initial Provider thought deadline was exceeded."
                    ),
                )
                self.phase = "stopped"
                self.lifecycle_reason = "initial_provider_timeout"
                return True
            self._set_bootstrap_phase("dispatching_cognition")
        self._apply_scheduled_sovereign_intents()
        self.intervention_audits.extend(
            _apply_runtime_interventions(
                self.world, self.ingestor, self.config.interventions
            )
        )
        self._dispatch_world_director()
        bootstrap_output_start = len(self.provider_outputs) if bootstrap_pending else 0
        bootstrap_event_start = self.world.events.count if bootstrap_pending else 0
        bootstrap_presentation_start = (
            self.world.presentation.count if bootstrap_pending else 0
        )
        if self.scheduler:
            scheduler_outputs = self._dispatch_scheduler()
            bootstrap_outputs = (
                [output.to_dict() for output in scheduler_outputs]
                if bootstrap_pending
                else []
            )
        else:
            self._dispatch_provider()
            bootstrap_outputs = (
                self.provider_outputs[bootstrap_output_start:]
                if bootstrap_pending
                else []
            )
        self.world.step(self.rule_engine)
        if bootstrap_pending:
            self._observe_cognition_bootstrap(
                bootstrap_outputs,
                self.world.events.since_index(bootstrap_event_start),
                self.world.presentation.since_index(
                    bootstrap_presentation_start
                ),
            )
            if self.phase == "stopped":
                return True
        self.memory_consolidation_report.extend(
            _apply_memory_consolidation(self.world, self.config.memory_consolidation)
        )
        if self.config.capture_timeline:
            self._capture_timeline_frame()
        if self.world.tick >= self.target_ticks:
            if self.scheduler and self.scheduler.has_pending_provider_jobs:
                self._begin_provider_drain("target tick reached")
            elif self.scheduler:
                self._enter_settle_or_complete()
            else:
                self.phase = "completed"
        return True

    def _initial_bootstrap_state(self) -> JsonDict:
        now = datetime.now(timezone.utc).isoformat()
        provider_mode = str(
            self.config.runtime_provider.get("mode", "deterministic")
            or "deterministic"
        )
        if not self.config.require_cognition_ready:
            return {
                "phase": "legacy_ready",
                "scenario_id": self.config.scenario,
                "provider_mode": provider_mode,
                "initial_snapshot_tick": int(self.world.tick),
                "ready": True,
                "retryable": False,
            }
        queued_job_ids = (
            [job.id for job in self.scheduler.queue[:32]] if self.scheduler else []
        )
        return {
            "phase": "dispatching_cognition",
            "scenario_id": self.config.scenario,
            "provider_mode": provider_mode,
            "provenance": (
                "deterministic_debug"
                if provider_mode == "deterministic"
                else "live_model"
            ),
            "initial_snapshot_tick": int(self.world.tick),
            "provider_job_ids": queued_job_ids,
            "accepted_provider_output_count": 0,
            "committed_pressure_ids": [],
            "grounded_action_sequences": [],
            "accepted_thought_sequences": [],
            "ready_projection_sequence": 0,
            "ready": False,
            "retryable": True,
            "started_at": now,
            "updated_at": now,
            "deadline_at": (
                datetime.now(timezone.utc)
                + timedelta(seconds=self.config.provider_drain_timeout_seconds)
            ).isoformat(),
            "error_code": "",
            "error_message": "",
        }

    def _set_bootstrap_phase(self, phase: str, **updates: Any) -> None:
        self.bootstrap_state.update(updates)
        self.bootstrap_state["phase"] = str(phase)
        self.bootstrap_state["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _observe_cognition_bootstrap(
        self,
        new_outputs: list[JsonDict],
        new_events: list[JsonDict],
        new_presentation_events: list[JsonDict],
    ) -> None:
        """Observe the normal runtime without changing its tick or rule path."""

        if self.scheduler:
            scheduler_status = self.scheduler.status_snapshot()
            self.bootstrap_state["provider_job_ids"] = [
                str(item)
                for item in scheduler_status.get("dispatched_job_ids", [])[-32:]
            ]
        accepted = [
            output for output in new_outputs if not _provider_output_failed(output)
        ]
        if accepted:
            self.bootstrap_state["accepted_provider_output_count"] = int(
                self.bootstrap_state.get("accepted_provider_output_count", 0) or 0
            ) + len(accepted)
        committed = {
            str(item)
            for item in self.bootstrap_state.get("committed_pressure_ids", [])
            if str(item)
        }
        committed.update(
            pressure_id
            for output in accepted
            for pressure_id in _provider_output_pressure_ids(output)
        )
        self.bootstrap_state["committed_pressure_ids"] = sorted(committed)[-32:]
        grounded_sequences = {
            int(item)
            for item in self.bootstrap_state.get("grounded_action_sequences", [])
            if int(item) > 0
        }
        grounded_sequences.update(
            _grounded_action_sequences(new_events, committed)
        )
        self.bootstrap_state["grounded_action_sequences"] = sorted(
            grounded_sequences
        )[-32:]

        thought_sequences = {
            int(item)
            for item in self.bootstrap_state.get("accepted_thought_sequences", [])
            if int(item) > 0
        }
        if any(_provider_output_has_visible_thought(output) for output in accepted):
            accepted_sources = {
                str(output.get("source", "")) for output in accepted
            }
            thought_sequences.update(
                _thought_event_sequences(
                    new_presentation_events, accepted_sources
                )
            )
        self.bootstrap_state["accepted_thought_sequences"] = sorted(
            thought_sequences
        )[-32:]

        if thought_sequences:
            self.world.attributes["cognition_ready"] = True
            self.world.attributes["cognition_ready_thought_sequences"] = sorted(
                thought_sequences
            )[-32:]
            self._set_bootstrap_phase(
                "ready",
                ready=True,
                retryable=False,
                ready_projection_sequence=self._commit_sequence + 1,
            )
            return

        failed_outputs = bool(new_outputs) and not accepted
        pending = bool(self.scheduler and self.scheduler.has_pending_provider_jobs)
        no_more_world_ticks = self.world.tick >= self.target_ticks
        if (failed_outputs or no_more_world_ticks) and not pending:
            error_type = _bootstrap_provider_error_type(new_outputs)
            timed_out = "timeout" in error_type.lower()
            self._set_bootstrap_phase(
                "timed_out" if timed_out else "failed",
                ready=False,
                error_code=(
                    "initial_provider_timeout"
                    if timed_out
                    else "initial_provider_no_visible_thought"
                ),
                error_message="The first Provider wave did not emit a visible thought.",
            )
            self.phase = "stopped"
            self.lifecycle_reason = str(self.bootstrap_state["error_code"])
            return
        self._set_bootstrap_phase("waiting_provider")

    def _step_completion_phase(self) -> bool:
        if self.phase == "running":
            if self.scheduler and self.scheduler.has_pending_provider_jobs:
                self._begin_provider_drain("target tick reached")
            else:
                self._enter_settle_or_complete()

        if self.phase == "provider_draining":
            if self.scheduler:
                if self.scheduler.config.dispatch_mode == "cognition_epoch":
                    self.world.step(self.rule_engine)
                    self.memory_consolidation_report.extend(
                        _apply_memory_consolidation(
                            self.world, self.config.memory_consolidation
                        )
                    )
                    if self.config.capture_timeline:
                        self._capture_timeline_frame()
                self.scheduler.wait_for_pending(timeout=0.01)
                self._ingest_scheduler_outputs(
                    self.scheduler.lifecycle_step(self.world)
                )
                if self.scheduler.lifecycle_state == "canceling":
                    self.scheduler.close("provider drain deadline exceeded")
                    self.phase = "canceled"
                    return True
                if self.scheduler.has_pending_provider_jobs:
                    return True
                if self.scheduler.lifecycle_state == "canceled":
                    self.phase = "canceled"
                    return True
            if self.stop_requested:
                self.phase = "stopped"
                return True
            self._enter_settle_or_complete()

        if self.phase != "causal_settling":
            return True
        if not self._has_pending_causal_observations():
            self.phase = "completed"
            return True
        if self.settle_ticks_completed >= max(
            int(self.config.causal_settle_ticks), 0
        ):
            self.phase = "completed"
            return True

        self.world.step(self.rule_engine)
        self.settle_ticks_completed += 1
        self.memory_consolidation_report.extend(
            _apply_memory_consolidation(self.world, self.config.memory_consolidation)
        )
        if self.config.capture_timeline:
            self._capture_timeline_frame()
        if (
            not self._has_pending_causal_observations()
            or self.settle_ticks_completed
            >= max(int(self.config.causal_settle_ticks), 0)
        ):
            self.phase = "completed"
        return True

    def _enter_settle_or_complete(self) -> None:
        if (
            self.scheduler is not None
            and int(self.config.causal_settle_ticks) > 0
            and self._has_pending_causal_observations()
        ):
            self.phase = "causal_settling"
        else:
            self.phase = "completed"

    def _begin_provider_drain(self, reason: str) -> None:
        self.phase = "provider_draining"
        if self.scheduler:
            self.scheduler.begin_drain(
                self.config.provider_drain_timeout_seconds,
                reason,
            )

    def _record_discarded_scheduler_outputs(
        self, outputs: list[ProviderOutput]
    ) -> None:
        for output in outputs:
            self._record_provider_output(output)

    def _has_pending_causal_observations(self) -> bool:
        totals = _dict(
            PressureActionTraceLedger().build_report(self.world).get("totals")
        )
        return int(totals.get("pending_observation", 0) or 0) > 0

    def runtime_status(self) -> JsonDict:
        settle_limit = max(int(self.config.causal_settle_ticks), 0)
        return {
            "phase": self.phase,
            "terminal": self.terminal,
            "stop_requested": self.stop_requested,
            "lifecycle_reason": self.lifecycle_reason,
            "target_ticks": self.target_ticks,
            "world_tick": self.world.tick,
            "causal_settle_ticks": settle_limit,
            "settle_ticks_completed": self.settle_ticks_completed,
            "settle_ticks_remaining": max(
                settle_limit - self.settle_ticks_completed,
                0,
            ),
            "bootstrap_state": json_copy(self.bootstrap_state),
        }

    def _capture_timeline_frame(self) -> None:
        self._timeline_sequence += 1
        self.timeline.append(
            _timeline_frame(
                self.world,
                event_start=self._timeline_event_count,
                trace_start=self._timeline_trace_count,
                sequence=self._timeline_sequence,
            )
        )
        self._timeline_event_count = len(self.world.events.recent())
        self._timeline_trace_count = len(self.world.traces.recent())
        retention = max(int(self.config.timeline_retention), 1)
        if len(self.timeline) > retention:
            self.timeline = self.timeline[-retention:]

    def run_to_end(self) -> "RunSession":
        while self.step():
            pass
        if self.completed:
            self.close("run completed")
        return self

    def step_incremental(self) -> IncrementalRunResult | None:
        """Advance once without constructing terminal reports or full projections."""

        if self.terminal:
            return None
        source_tick = self.world.tick
        source_phase = self.phase
        before = self._last_committed_world_state
        event_start = self._event_cursor
        presentation_start = self._presentation_cursor
        trace_start = self._trace_cursor
        output_start = self._provider_output_cursor
        audit_start = self._provider_audit_cursor
        intervention_start = self._intervention_audit_cursor
        memory_start = self._memory_consolidation_cursor
        sovereign_start = self._sovereign_intent_audit_cursor

        capture_timeline = self.config.capture_timeline
        self.config.capture_timeline = False
        try:
            advanced = self.step()
        finally:
            self.config.capture_timeline = capture_timeline
        if not advanced:
            return None

        after = compact_world_snapshot(self.world)
        new_outputs = json_copy(self.provider_outputs[output_start:])
        new_attempts: list[JsonDict] = []
        for ordinal, output in enumerate(new_outputs, start=output_start):
            new_attempts.extend(provider_attempts_from_output(output, ordinal=ordinal))

        self._commit_sequence += 1
        event_end = self.world.events.count
        trace_end = self.world.traces.count
        output_end = len(self.provider_outputs)
        commit = TickCommit(
            sequence=self._commit_sequence,
            source_tick=source_tick,
            resulting_tick=self.world.tick,
            source_phase=source_phase,
            resulting_phase=self.phase,
            state_delta=world_state_delta(before, after),
            session_state=self._incremental_session_state(),
            event_start=event_start,
            event_end=event_end,
            trace_start=trace_start,
            trace_end=trace_end,
            provider_output_start=output_start,
            provider_output_end=output_end,
            provider_attempt_start=max(output_start, 0),
            provider_attempt_end=max(output_start, 0) + len(new_attempts),
        )
        result = IncrementalRunResult(
            commit=commit,
            events=self.world.events.since_index(event_start),
            presentation_events=self.world.presentation.since_index(presentation_start),
            traces=self.world.traces.since_index(trace_start),
            provider_outputs=new_outputs,
            provider_attempts=new_attempts,
            provider_audits=json_copy(self.provider_audits[audit_start:]),
            intervention_audits=json_copy(
                self.intervention_audits[intervention_start:]
            ),
            memory_consolidation=json_copy(
                self.memory_consolidation_report[memory_start:]
            ),
            sovereign_intent_audits=json_copy(
                self.sovereign_intent_audits[sovereign_start:]
            ),
            runtime=self.runtime_status(),
        )
        self._last_committed_world_state = after
        self._event_cursor = event_end
        self._presentation_cursor = self.world.presentation.count
        self._trace_cursor = trace_end
        self._provider_output_cursor = output_end
        self._provider_audit_cursor = len(self.provider_audits)
        self._intervention_audit_cursor = len(self.intervention_audits)
        self._memory_consolidation_cursor = len(self.memory_consolidation_report)
        self._sovereign_intent_audit_cursor = len(self.sovereign_intent_audits)
        return result

    def compact_checkpoint(self) -> JsonDict:
        """Return compact recovery state plus bounded semantic evidence."""

        scheduler_state = (
            _bounded_scheduler_state(self.scheduler.checkpoint_state())
            if self.scheduler
            else {}
        )
        return {
            "schema": COMPACT_CHECKPOINT_SCHEMA,
            "version": 3,
            "config": self.config.to_dict(),
            "target_ticks": self.target_ticks,
            "phase": self.phase,
            "stop_requested": self.stop_requested,
            "lifecycle_reason": self.lifecycle_reason,
            "settle_ticks_completed": self.settle_ticks_completed,
            "bootstrap_state": json_copy(self.bootstrap_state),
            "world_state": compact_world_snapshot(self.world),
            "commit_sequence": self._commit_sequence,
            # These cursors address append-only repository rows. The bounded
            # windows reconstruct current model evidence without reloading the
            # complete Run history after every checkpoint.
            "event_cursor": _latest_event_sequence(self.world.events.recent()),
            "trace_cursor": self.world.traces.count,
            "recovery_event_window": self.world.events.recent(128),
            "recovery_trace_window": self.world.traces.recent(128),
            "provider_output_cursor": self._provider_output_cursor,
            "dropped_provider_attempt_count": self.dropped_provider_attempt_count,
            "provider_usage_totals": json_copy(self.provider_usage_totals),
            "applied_sovereign_intent_ids": sorted(
                self._applied_sovereign_intent_ids
            ),
            "scheduler_state": scheduler_state,
        }

    @classmethod
    def from_compact_checkpoint(
        cls,
        checkpoint: JsonDict,
        scheduler_provider: AgentProvider | None = None,
        *,
        commits: list[JsonDict] | None = None,
        events: list[JsonDict] | None = None,
        traces: list[JsonDict] | None = None,
        provider_outputs: list[JsonDict] | None = None,
        provider_attempts: list[JsonDict] | None = None,
        provider_audits: list[JsonDict] | None = None,
        intervention_audits: list[JsonDict] | None = None,
        memory_consolidation_report: list[JsonDict] | None = None,
        sovereign_intent_audits: list[JsonDict] | None = None,
    ) -> "RunSession":
        if int(checkpoint.get("version", 0) or 0) not in {2, 3}:
            return cls.from_checkpoint(checkpoint, scheduler_provider)
        config = RunConfig.from_dict(_dict(checkpoint.get("config")))
        config.scheduler_provider = scheduler_provider
        session = cls(config)
        base_sequence = int(checkpoint.get("commit_sequence", 0) or 0)
        later_commits = [
            item
            for item in commits or []
            if int(item.get("sequence", 0) or 0) > base_sequence
        ]
        world_state, replayed_sequence, replayed_phase = replay_tick_commits(
            _dict(checkpoint.get("world_state")), later_commits
        )
        checkpoint_events = _list(checkpoint.get("recovery_event_window"))
        checkpoint_traces = _list(checkpoint.get("recovery_trace_window"))
        session.world = world_from_compact_snapshot(
            world_state,
            events=[*checkpoint_events, *_events_after_cursor(events, checkpoint)],
            traces=[*checkpoint_traces, *(traces or [])],
        )
        session.provider_outputs = json_copy(provider_outputs or [])
        session.provider_attempts = json_copy(provider_attempts or [])
        # The repository returns the complete append-only attempt ledger on
        # recovery. Recomputing from it includes both pre- and post-checkpoint
        # attempts and avoids accidentally omitting later rows.
        session.provider_usage_totals = accumulate_provider_usage(
            _dict(checkpoint.get("provider_usage_totals")), session.provider_attempts
        )
        session.provider_audits = json_copy(provider_audits or [])
        session.intervention_audits = json_copy(intervention_audits or [])
        session.memory_consolidation_report = json_copy(
            memory_consolidation_report or []
        )
        session.sovereign_intent_audits = json_copy(
            sovereign_intent_audits or []
        )
        session.target_ticks = int(
            checkpoint.get("target_ticks", session.target_ticks)
            or session.target_ticks
        )
        session._commit_sequence = max(base_sequence, replayed_sequence)
        session._event_cursor = session.world.events.count
        session._presentation_cursor = 0
        session._trace_cursor = session.world.traces.count
        session._provider_output_cursor = len(session.provider_outputs)
        session._provider_audit_cursor = len(session.provider_audits)
        session._intervention_audit_cursor = len(session.intervention_audits)
        session._memory_consolidation_cursor = len(
            session.memory_consolidation_report
        )
        session._sovereign_intent_audit_cursor = len(
            session.sovereign_intent_audits
        )
        session._last_committed_world_state = world_state
        session.dropped_provider_attempt_count = int(
            checkpoint.get("dropped_provider_attempt_count", 0) or 0
        )
        session.settle_ticks_completed = max(
            int(checkpoint.get("settle_ticks_completed", 0) or 0), 0
        )
        session.bootstrap_state = json_copy(
            _dict(checkpoint.get("bootstrap_state"))
        ) or session._initial_bootstrap_state()
        session._applied_sovereign_intent_ids = {
            str(item)
            for item in _list(checkpoint.get("applied_sovereign_intent_ids"))
        }
        session.stop_requested = bool(checkpoint.get("stop_requested", False))
        session.lifecycle_reason = str(checkpoint.get("lifecycle_reason", ""))
        scheduler_state = _dict(checkpoint.get("scheduler_state"))
        for commit_data in sorted(
            later_commits,
            key=lambda item: int(item.get("sequence", 0) or 0),
        ):
            session_state = _dict(commit_data.get("session_state"))
            if not session_state:
                continue
            session.settle_ticks_completed = int(
                session_state.get(
                    "settle_ticks_completed", session.settle_ticks_completed
                )
                or 0
            )
            restored_bootstrap = _dict(session_state.get("bootstrap_state"))
            if restored_bootstrap:
                session.bootstrap_state = json_copy(restored_bootstrap)
            session._applied_sovereign_intent_ids = {
                str(item)
                for item in _list(
                    session_state.get("applied_sovereign_intent_ids")
                )
            }
            session.stop_requested = bool(
                session_state.get("stop_requested", session.stop_requested)
            )
            session.lifecycle_reason = str(
                session_state.get("lifecycle_reason", session.lifecycle_reason)
            )
            scheduler_state = _apply_scheduler_state_delta(
                scheduler_state,
                _dict(session_state.get("scheduler_state_delta")),
            )
        if session.scheduler:
            session.scheduler.restore_state(session.world, scheduler_state)
        session._last_committed_scheduler_state = scheduler_state
        restored_phase = replayed_phase if replayed_sequence else str(
            checkpoint.get("phase", "running")
        )
        session.phase = (
            restored_phase if restored_phase in RUN_PHASES else "running"
        )
        return session

    def _incremental_session_state(self) -> JsonDict:
        scheduler_state = (
            _bounded_scheduler_state(self.scheduler.checkpoint_state())
            if self.scheduler
            else {}
        )
        scheduler_delta = _scheduler_state_delta(
            self._last_committed_scheduler_state, scheduler_state
        )
        self._last_committed_scheduler_state = scheduler_state
        return {
            "stop_requested": self.stop_requested,
            "lifecycle_reason": self.lifecycle_reason,
            "settle_ticks_completed": self.settle_ticks_completed,
            "bootstrap_state": json_copy(self.bootstrap_state),
            "applied_sovereign_intent_ids": sorted(
                self._applied_sovereign_intent_ids
            ),
            "scheduler_state_delta": scheduler_delta,
        }

    def checkpoint(self) -> JsonDict:
        return {
            "version": 1,
            "config": self.config.to_dict(),
            "target_ticks": self.target_ticks,
            "phase": self.phase,
            "stop_requested": self.stop_requested,
            "lifecycle_reason": self.lifecycle_reason,
            "settle_ticks_completed": self.settle_ticks_completed,
            "bootstrap_state": json_copy(self.bootstrap_state),
            "world_snapshot": self.world.snapshot(),
            "provider_outputs": json_copy(self.provider_outputs),
            "provider_attempts": json_copy(self.provider_attempts),
            "dropped_provider_attempt_count": self.dropped_provider_attempt_count,
            "provider_usage_totals": json_copy(self.provider_usage_totals),
            "provider_audits": json_copy(self.provider_audits),
            "intervention_audits": json_copy(self.intervention_audits),
            "memory_consolidation_report": json_copy(self.memory_consolidation_report),
            "timeline": json_copy(self.timeline),
            "timeline_event_count": self._timeline_event_count,
            "timeline_trace_count": self._timeline_trace_count,
            "timeline_sequence": self._timeline_sequence,
            "sovereign_intent_audits": json_copy(self.sovereign_intent_audits),
            "applied_sovereign_intent_ids": sorted(self._applied_sovereign_intent_ids),
            "scheduler_state": self.scheduler.checkpoint_state()
            if self.scheduler
            else {},
        }

    @classmethod
    def from_checkpoint(
        cls, checkpoint: JsonDict, scheduler_provider: AgentProvider | None = None
    ) -> "RunSession":
        config = RunConfig.from_dict(_dict(checkpoint.get("config")))
        config.scheduler_provider = scheduler_provider
        session = cls(config)
        session.target_ticks = int(
            checkpoint.get("target_ticks", session.target_ticks) or session.target_ticks
        )
        session.world = World.from_snapshot(_dict(checkpoint.get("world_snapshot")))
        session.provider_outputs = json_copy(_list(checkpoint.get("provider_outputs")))
        session.provider_attempts = json_copy(_list(checkpoint.get("provider_attempts")))
        session.provider_usage_totals = json_copy(
            _dict(checkpoint.get("provider_usage_totals"))
        ) or accumulate_provider_usage(None, session.provider_attempts)
        session.dropped_provider_attempt_count = int(
            checkpoint.get("dropped_provider_attempt_count", 0) or 0
        )
        session.provider_audits = json_copy(_list(checkpoint.get("provider_audits")))
        session.intervention_audits = json_copy(
            _list(checkpoint.get("intervention_audits"))
        )
        session.memory_consolidation_report = json_copy(
            _list(checkpoint.get("memory_consolidation_report"))
        )
        session.timeline = json_copy(_list(checkpoint.get("timeline")))
        session._timeline_event_count = int(
            checkpoint.get("timeline_event_count", len(session.world.events.recent()))
            or len(session.world.events.recent())
        )
        session._timeline_trace_count = int(
            checkpoint.get("timeline_trace_count", len(session.world.traces.recent()))
            or len(session.world.traces.recent())
        )
        session._timeline_sequence = int(
            checkpoint.get(
                "timeline_sequence", _latest_timeline_sequence(session.timeline)
            )
            or _latest_timeline_sequence(session.timeline)
        )
        session.sovereign_intent_audits = json_copy(
            _list(checkpoint.get("sovereign_intent_audits"))
        )
        session._applied_sovereign_intent_ids = {
            str(item) for item in _list(checkpoint.get("applied_sovereign_intent_ids"))
        }
        session.stop_requested = bool(checkpoint.get("stop_requested", False))
        session.lifecycle_reason = str(checkpoint.get("lifecycle_reason", ""))
        if session.scheduler:
            session.scheduler.restore_state(
                session.world,
                _dict(checkpoint.get("scheduler_state")),
            )
        session.settle_ticks_completed = max(
            int(checkpoint.get("settle_ticks_completed", 0) or 0),
            0,
        )
        session.bootstrap_state = json_copy(
            _dict(checkpoint.get("bootstrap_state"))
        ) or session._initial_bootstrap_state()
        restored_phase = str(checkpoint.get("phase", ""))
        if restored_phase in RUN_PHASES:
            session.phase = restored_phase
        elif session.world.tick < session.target_ticks:
            session.phase = "running"
        elif session.scheduler and session.scheduler.has_pending_provider_jobs:
            session.phase = "provider_draining"
        elif session._has_pending_causal_observations():
            session.phase = "causal_settling"
        else:
            session.phase = "completed"
        return session

    def result(self) -> RunResult:
        snapshot = self.world.snapshot()
        provider_outcome_report = ProviderOutcomeLedger().build_report(self.world)
        social_ripples = SocialRippleLedger().build_report(self.world)
        world_archive = WorldArchive().export(
            self.world, self.provider_outputs, self.provider_audits
        )
        result = RunResult(
            config=self.config.to_dict(),
            snapshot=snapshot,
            pressure_view=StructuredPressureView().build(self.world),
            pressure_action_report=PressureActionTraceLedger().build_report(self.world),
            ai_causality_report=AiCausalityTraceLedger().build_report(self.world),
            provider_outcome_report=provider_outcome_report,
            provider_execution_report=ProviderExecutionProfiler().build_report(
                self.provider_outputs,
                self.provider_audits,
                provider_outcome_report,
            ),
            provider_attempt_report=provider_attempt_totals(
                self.provider_attempts,
                self.dropped_provider_attempt_count,
                self.provider_usage_totals,
            ),
            scorecard={},
            provider_outputs=self.provider_outputs,
            provider_attempts=self.provider_attempts,
            provider_audits=self.provider_audits,
            scheduler_status={
                **(
                    self.scheduler.status_snapshot()
                    if self.scheduler
                    else {"enabled": False}
                ),
                "run_runtime": self.runtime_status(),
            },
            events=snapshot["events"],
            traces=snapshot["traces"],
            timeline=self.timeline,
            intervention_audits=self.intervention_audits,
            memory_consolidation_report=self.memory_consolidation_report,
            sovereign_intent_audits=self.sovereign_intent_audits,
            social_ripples=social_ripples,
            world_archive=world_archive,
        )
        result.scorecard = evaluate_run(result).to_dict()
        return result

    def _dispatch_scheduler(self) -> list[ProviderOutput]:
        if self.scheduler is None:
            return []
        if self.scheduler.config.event_triggered_lenses:
            self.scheduler.enqueue_many(
                enterprise_event_triggered_lens_jobs(
                    self.world,
                    tick=self.world.tick,
                    limit=self.scheduler.config.max_triggered_lenses_per_tick,
                    feedback_limit=self.scheduler.config.trigger_feedback_limit,
                )
            )
        if self.scheduler.config.pressure_triggered_jobs:
            self.scheduler.enqueue_many(
                enterprise_pressure_triggered_jobs(
                    self.world,
                    tick=self.world.tick,
                    limit=self.scheduler.config.max_pressure_triggered_jobs_per_tick,
                    threshold=self.scheduler.config.pressure_trigger_threshold,
                    rule=str(self.config.provider_params.get("rule", "move")),
                    provider_override=self.config.scheduler_provider,
                )
            )
        scheduler_params = json_copy(self.config.provider_params)
        scheduler_params["enabled_rule_names"] = list(self.rules)
        if self.config.runtime_provider:
            scheduler_params["runtime_provider"] = json_copy(
                self.config.runtime_provider
            )
        outputs = self.scheduler.dispatch_tick(
            self.world, self.world.tick, scheduler_params
        )
        self._ingest_scheduler_outputs(outputs)
        return outputs

    def _ingest_scheduler_outputs(self, outputs: list[ProviderOutput]) -> None:
        for output in outputs:
            if not bool(output.metadata.get("presentation_only", False)):
                self._record_provider_output(output)
            _ingest_provider_output(self.world, self.ingestor, output.source, output)

    def _record_provider_output(self, output: ProviderOutput) -> None:
        output_data = output.to_dict()
        ordinal = len(self.provider_outputs)
        self.provider_outputs.append(output_data)
        additions = provider_attempts_from_output(output_data, ordinal=ordinal)
        self.provider_usage_totals = accumulate_provider_usage(
            self.provider_usage_totals, additions
        )
        retained, dropped = merge_provider_attempts(
            self.provider_attempts,
            additions,
        )
        self.provider_attempts = retained
        self.dropped_provider_attempt_count += dropped

    def _dispatch_provider(self) -> None:
        params = json_copy(self.config.provider_params)
        if self.provider_profile:
            params["provider_profile"] = self.provider_profile.to_dict()
            params["context_strategy"] = json_copy(
                self.provider_profile.context_strategy
            )
        if "agent_context_packet" not in params:
            direct_job = AgentJob(
                id=f"direct-provider-{self.world.id}-{self.world.tick}",
                kind="relationship_round",
                provider=self.provider,
                metadata={},
            )
            params["agent_context_packet"] = AgentContextPacketBuilder().build(
                self.world, direct_job
            )
        context = ProviderContext(
            world=self.world,
            tick=self.world.tick,
            snapshot=self.world.snapshot(),
            params=params,
        )
        if self.config.govern_provider_output or self.provider_profile is not None:
            provider_id = self.config.provider_id
            allowed_rule_names = self.config.allowed_rule_names
            allowed_relationship_types = self.config.allowed_relationship_types
            if self.provider_profile:
                provider_id = (
                    self.config.provider_id
                    if self.config.provider_id != "default"
                    else self.provider_profile.id
                )
                allowed_rule_names = (
                    allowed_rule_names or self.provider_profile.allowed_rule_names
                )
                allowed_relationship_types = (
                    allowed_relationship_types
                    or self.provider_profile.allowed_relationship_types
                )
            registry = ProviderRegistry()
            registry.register(
                provider_id,
                self.provider,
                allowed_rule_names=set(allowed_rule_names),
                allowed_relationship_types=set(allowed_relationship_types),
                policy_profile=self.provider_profile,
            )
            governed = GovernedProviderRunner(registry).observe(provider_id, context)
            self.provider_audits.append(governed.audit.to_dict())
            if governed.output is not None:
                self._record_provider_output(governed.output)
                _ingest_provider_output(
                    self.world, self.ingestor, self.provider.name, governed.output
                )
        else:
            output = self.provider.observe(context)
            self._record_provider_output(output)
            _ingest_provider_output(
                self.world, self.ingestor, self.provider.name, output
            )

    def _dispatch_world_director(self) -> None:
        if self.world_director is None:
            return
        context = ProviderContext(
            world=self.world,
            tick=self.world.tick,
            snapshot=self.world.snapshot(),
            params={
                "world_director": _resolved_world_director_config(
                    self.config.scenario, self.config.world_director
                )
            },
        )
        output = self.world_director.observe(context)
        self._record_provider_output(output)
        _ingest_provider_output(
            self.world, self.ingestor, WORLD_DIRECTOR_SOURCE, output
        )

    def _apply_scheduled_sovereign_intents(self) -> None:
        for raw_plan in self.config.sovereign_intents:
            plan = (
                raw_plan
                if isinstance(raw_plan, SovereignIntentPlan)
                else SovereignIntentPlan.from_dict(raw_plan)
            )
            if plan.id in self._applied_sovereign_intent_ids:
                continue
            if int(plan.scheduled_tick) != self.world.tick:
                continue
            applied = apply_sovereign_intent_plan(self.world, self.ingestor, plan)
            if plan.dynamic_rules:
                self.rule_engine.packages.append(SovereignDynamicRulePackage(plan))
            self._applied_sovereign_intent_ids.add(plan.id)
            self.sovereign_intent_audits.append(
                {
                    "id": plan.id,
                    "tick": self.world.tick,
                    "title": plan.title,
                    "impact_level": plan.impact_level,
                    "initial_effect_count": len(plan.initial_effects),
                    "dynamic_rule_count": len(plan.dynamic_rules),
                    "sequence": applied.get("sequence"),
                    "error_count": len(applied.get("errors", [])),
                }
            )


def _apply_memory_consolidation(world: World, options: JsonDict) -> list[JsonDict]:
    if not _dict(options).get("enabled"):
        return []
    interval = max(int(_dict(options).get("interval", 1) or 1), 1)
    if world.tick <= 0 or world.tick % interval != 0:
        return []
    results = WorldMemoryConsolidator().consolidate_world(
        world,
        max_memories=max(int(_dict(options).get("max_memories", 12) or 12), 2),
        recent_keep=max(int(_dict(options).get("recent_keep", 6) or 6), 1),
        source_credibility=_dict(_dict(options).get("source_credibility")) or None,
        retention_importance_floor=_optional_float(
            _dict(options).get("retention_importance_floor")
        ),
    )
    report = [
        {
            "tick": world.tick,
            **result.to_dict(),
        }
        for result in results
    ]
    if not report:
        return []
    forgotten_count = sum(
        int(_dict(item.get("summary")).get("forgotten_count", 0) or 0)
        for item in report
    )
    summary_count = sum(
        1
        for item in report
        if _dict(item.get("summary")).get("kind") == "memory_summary"
    )
    observed = {
        "consolidated_nodes": len(report),
        "summary_count": summary_count,
        "forgotten_count": forgotten_count,
        "interval": interval,
    }
    world.traces.record(
        TraceRecord(
            tick=world.tick,
            kind="memory_consolidation",
            source="run_harness",
            observed=observed,
            delta={"results": json_copy(report[-20:])},
        )
    )
    world.events.record_delta(
        world.tick,
        "run_harness",
        {
            "kind": "memory_consolidation",
            **observed,
            "results": json_copy(report[-20:]),
        },
    )
    return report


def _timeline_frame(
    world: World, event_start: int, trace_start: int, sequence: int
) -> JsonDict:
    from .viewer_projection import project_run_for_viewer

    snapshot = world.snapshot()
    all_events = _list(snapshot.get("events"))
    all_traces = _list(snapshot.get("traces"))
    events = json_copy(all_events[max(int(event_start), 0) :])
    traces = json_copy(all_traces[max(int(trace_start), 0) :])
    frame_data = {
        "config": {},
        "snapshot": snapshot,
        "pressure_view": StructuredPressureView().build(world),
        "pressure_action_report": PressureActionTraceLedger().build_report(world),
        "ai_causality_report": AiCausalityTraceLedger().build_report(world),
        "provider_outcome_report": ProviderOutcomeLedger().build_report(world),
        "scorecard": {},
        "provider_outputs": [],
        "provider_audits": [],
        "scheduler_status": {},
        "events": events,
        "traces": traces,
    }
    return {
        "sequence": max(int(sequence), 1),
        "tick": snapshot["tick"],
        "event_cursor": int(all_events[-1].get("sequence", 0) or 0)
        if all_events
        else 0,
        "trace_cursor": len(all_traces),
        "events": events,
        "traces": traces,
        "deltas": [
            json_copy(event) for event in events if event.get("kind") == "state_delta"
        ],
        "projection": project_run_for_viewer(frame_data).to_dict(),
    }


def _latest_timeline_sequence(timeline: list[JsonDict]) -> int:
    return max(
        (
            int(frame.get("sequence", frame.get("tick", 0)) or 0)
            for frame in timeline
            if isinstance(frame, dict)
        ),
        default=0,
    )


def _latest_event_sequence(events: list[JsonDict]) -> int:
    return max(
        (int(item.get("sequence", 0) or 0) for item in events if isinstance(item, dict)),
        default=0,
    )


def _events_after_cursor(events: list[JsonDict] | None, checkpoint: JsonDict) -> list[JsonDict]:
    cursor = int(checkpoint.get("event_cursor", 0) or 0)
    return [
        json_copy(item)
        for item in events or []
        if isinstance(item, dict) and int(item.get("sequence", 0) or 0) > cursor
    ]


def _ingest_provider_output(
    world: World,
    ingestor: FeedbackIngestor,
    provider_name: str,
    output: ProviderOutput,
) -> None:
    if not output.effects:
        return
    ingestor.ingest(
        world,
        ActionFeedback(
            source=output.source,
            actor_type="agent",
            actor_id=provider_name,
            action="provider_pressure",
            summary=output.summary,
            effects=output.effects,
            apply_mode=APPLY_AUTHORITATIVE,
            metadata=output.metadata,
        ),
    )


def _provider_output_failed(output: JsonDict) -> bool:
    if isinstance(output.get("provider_error"), dict):
        return True
    pending = _dict(output.get("provider_pending"))
    return str(pending.get("status", "")) in {
        "failed",
        "canceled",
        "expired",
        "discarded_after_cancel",
        "duplicate_generation",
    }


def _provider_output_pressure_ids(output: JsonDict) -> list[str]:
    return [
        pressure_id
        for item in _list(output.get("effects"))
        if isinstance(item, dict)
        and str(item.get("type", "")) == "rule_pressure_add"
        and (pressure_id := str(item.get("pressure_id", "")).strip())
    ]


def _provider_output_has_visible_thought(output: JsonDict) -> bool:
    return any(
        isinstance(item, dict)
        and str(item.get("type", ""))
        in {"thought_bubble_add", "thought_schedule_add"}
        and _thought_payload_has_text(item)
        for item in _list(output.get("effects"))
    )


def _thought_event_sequences(
    events: list[JsonDict], accepted_sources: set[str]
) -> list[int]:
    sequences: list[int] = []
    for event in events:
        if accepted_sources and str(event.get("source", "")) not in accepted_sources:
            continue
        payload = _dict(event.get("payload"))
        if str(payload.get("type", "")) not in {
            "thought_bubble",
            "thought_schedule",
        }:
            continue
        if not _thought_payload_has_text(payload):
            continue
        sequence = int(event.get("sequence", 0) or 0)
        if sequence > 0:
            sequences.append(sequence)
    return sequences


def _thought_payload_has_text(payload: JsonDict) -> bool:
    for key in ("text", "thought", "visible_thought"):
        if str(payload.get(key, "")).strip():
            return True
    for key in ("slices", "occurrences", "thought_bubbles"):
        for item in _list(payload.get(key)):
            if isinstance(item, dict):
                if any(
                    str(item.get(field, "")).strip()
                    for field in ("text", "thought", "visible_thought")
                ):
                    return True
            elif str(item).strip():
                return True
    return False


def _bootstrap_deadline_expired(state: JsonDict) -> bool:
    deadline_text = str(state.get("deadline_at", "")).strip()
    if not deadline_text:
        return False
    try:
        deadline = datetime.fromisoformat(deadline_text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= deadline.astimezone(timezone.utc)


def _bootstrap_provider_error_type(outputs: list[JsonDict]) -> str:
    for output in outputs:
        error = _dict(output.get("provider_error"))
        if error:
            return str(error.get("type", "provider_error"))
    return "provider_output_without_visible_thought"


def _grounded_action_sequences(
    events: list[JsonDict], pressure_ids: set[str]
) -> list[int]:
    sequences: list[int] = []
    for event in events:
        if str(event.get("kind", "")) != "action_feedback":
            continue
        payload = _dict(event.get("payload"))
        if str(payload.get("apply_mode", "")) != APPLY_AUTHORITATIVE:
            continue
        caused_by = {
            str(item)
            for item in _list(payload.get("caused_by_pressure_ids"))
            if str(item)
        }
        if caused_by.intersection(pressure_ids):
            sequences.append(int(event.get("sequence", 0) or 0))
    return [sequence for sequence in sequences if sequence > 0]


def _apply_runtime_interventions(
    world: World,
    ingestor: FeedbackIngestor,
    interventions: list[JsonDict],
) -> list[JsonDict]:
    audits: list[JsonDict] = []
    for index, raw in enumerate(interventions):
        if not isinstance(raw, dict):
            audits.append(
                {
                    "id": f"intervention-{index + 1}",
                    "tick": world.tick,
                    "accepted": False,
                    "error": "intervention must be an object",
                }
            )
            continue
        scheduled_tick = int(raw.get("tick", 0) or 0)
        if scheduled_tick != world.tick:
            continue
        audit = _ingest_runtime_intervention(world, ingestor, raw, index)
        audits.append(audit)
    return audits


def _ingest_runtime_intervention(
    world: World,
    ingestor: FeedbackIngestor,
    raw: JsonDict,
    index: int,
) -> JsonDict:
    intervention_id = str(raw.get("id", f"intervention-{index + 1}"))
    structured_metadata: JsonDict = {}
    if is_structured_world_intervention(raw):
        try:
            intervention = WorldIntervention.from_dict(raw)
            compiled = compile_world_intervention(world, intervention)
        except (TypeError, ValueError) as exc:
            error = str(exc)
            audit = {
                "id": intervention_id,
                "tick": world.tick,
                "accepted": False,
                "error": error,
                "schema": str(raw.get("schema", "")),
                "intervention_type": str(raw.get("intervention_type", "")),
            }
            world.traces.record(
                TraceRecord(
                    tick=world.tick,
                    kind="runtime_intervention",
                    source=str(raw.get("source", "runtime_intervention")),
                    observed={
                        "id": intervention_id,
                        "schema": str(raw.get("schema", "")),
                        "intervention_type": str(raw.get("intervention_type", "")),
                    },
                    selected={"accepted": False, "error": error},
                )
            )
            return audit
        effects = list(compiled.effects)
        structured_metadata = compiled.to_metadata()
    else:
        raw_effects = raw.get("effects", [])
        if not isinstance(raw_effects, list):
            return {
                "id": intervention_id,
                "tick": world.tick,
                "accepted": False,
                "error": "intervention effects must be a list",
            }
        effects = [
            WorldEffect(
                str(effect.get("type", "")),
                {
                    key: json_copy(value)
                    for key, value in effect.items()
                    if key != "type"
                },
            )
            for effect in raw_effects
            if isinstance(effect, dict)
        ]
    feedback = ActionFeedback(
        source=str(raw.get("source", "runtime_intervention")),
        actor_type=str(raw.get("actor_type", "user")),
        actor_id=str(raw.get("actor_id", "operator")),
        action=str(raw.get("action", "runtime_intervention")),
        summary=str(raw.get("summary", f"runtime intervention {intervention_id}")),
        effects=effects,
        apply_mode=APPLY_AUTHORITATIVE,
        metadata={
            "intervention": {
                "id": intervention_id,
                "scheduled_tick": int(raw.get("tick", world.tick) or world.tick),
                "effect_count": len(effects),
                **structured_metadata,
            }
        },
    )
    normalized = ingestor.ingest(world, feedback)
    audit = {
        "id": intervention_id,
        "tick": world.tick,
        "accepted": not normalized["errors"],
        "sequence": normalized["sequence"],
        "effect_count": len(effects),
        "applied_effect_count": len(normalized["applied_effects"]),
        "error_count": len(normalized["errors"]),
        "errors": json_copy(normalized["errors"]),
        **structured_metadata,
    }
    world.traces.record(
        TraceRecord(
            tick=world.tick,
            kind="runtime_intervention",
            source=str(raw.get("source", "runtime_intervention")),
            observed={
                "id": intervention_id,
                "actor_id": feedback.actor_id,
                "effect_count": len(effects),
                **structured_metadata,
            },
            selected={"accepted": audit["accepted"], "sequence": audit["sequence"]},
            delta={
                "applied_effect_count": audit["applied_effect_count"],
                "error_count": audit["error_count"],
            },
        )
    )
    return audit


def _bounded_scheduler_state(value: JsonDict) -> JsonDict:
    state = json_copy(value)
    completed = state.get("completed_provider_jobs")
    if isinstance(completed, list):
        state["completed_provider_jobs"] = completed[-100:]
    return state


def _scheduler_state_delta(before: JsonDict, after: JsonDict) -> JsonDict:
    if not after and not before:
        return {}
    set_fields = {
        key: json_copy(value)
        for key, value in after.items()
        if key not in {"pending_provider_jobs", "eligible_jobs"}
        and before.get(key) != value
    }
    before_pending = {
        str(item.get("job_id", "")): item
        for item in _list(before.get("pending_provider_jobs"))
        if isinstance(item, dict) and str(item.get("job_id", ""))
    }
    after_pending = {
        str(item.get("job_id", "")): item
        for item in _list(after.get("pending_provider_jobs"))
        if isinstance(item, dict) and str(item.get("job_id", ""))
    }
    before_eligible = {
        str(item.get("job_id", "")): item
        for item in _list(before.get("eligible_jobs"))
        if isinstance(item, dict) and str(item.get("job_id", ""))
    }
    after_eligible = {
        str(item.get("job_id", "")): item
        for item in _list(after.get("eligible_jobs"))
        if isinstance(item, dict) and str(item.get("job_id", ""))
    }
    return {
        "set": set_fields,
        "pending_upsert": [
            json_copy(after_pending[job_id])
            for job_id in sorted(after_pending)
            if before_pending.get(job_id) != after_pending[job_id]
        ],
        "pending_delete": sorted(set(before_pending) - set(after_pending)),
        "eligible_upsert": [
            json_copy(after_eligible[job_id])
            for job_id in sorted(after_eligible)
            if before_eligible.get(job_id) != after_eligible[job_id]
        ],
        "eligible_delete": sorted(set(before_eligible) - set(after_eligible)),
    }


def _apply_scheduler_state_delta(state: JsonDict, delta: JsonDict) -> JsonDict:
    result = json_copy(state)
    result.update(json_copy(_dict(delta.get("set"))))
    for field_name, upsert_name, delete_name in (
        ("pending_provider_jobs", "pending_upsert", "pending_delete"),
        ("eligible_jobs", "eligible_upsert", "eligible_delete"),
    ):
        rows = {
            str(item.get("job_id", "")): json_copy(item)
            for item in _list(result.get(field_name))
            if isinstance(item, dict) and str(item.get("job_id", ""))
        }
        for job_id in _list(delta.get(delete_name)):
            rows.pop(str(job_id), None)
        for item in _list(delta.get(upsert_name)):
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id", ""))
            if job_id:
                rows[job_id] = json_copy(item)
        result[field_name] = [rows[key] for key in sorted(rows)]
    return result


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _rule_package_name(package: RulePackage) -> str:
    return str(getattr(package, "name", package.__class__.__name__))


def _sovereign_intent_dict(plan: JsonDict | SovereignIntentPlan) -> JsonDict:
    if isinstance(plan, SovereignIntentPlan):
        return plan.to_dict()
    return json_copy(plan) if isinstance(plan, dict) else {}


def _provider_profile(value: JsonDict) -> ProviderPolicyProfile | None:
    if not value:
        return None
    return ProviderPolicyProfile.from_dict(value)


def _world_director_for_config(
    config: RunConfig,
) -> DeterministicWorldDirectorProvider | None:
    options = _resolved_world_director_config(config.scenario, config.world_director)
    if not bool(options.get("enabled", False)):
        return None
    return DeterministicWorldDirectorProvider(WorldDirectorConfig.from_dict(options))


def _resolved_world_director_config(scenario: str, options: JsonDict) -> JsonDict:
    explicit_enabled = "enabled" in options
    enabled = (
        bool(options.get("enabled"))
        if explicit_enabled
        else str(scenario) == "compound_crisis"
    )
    resolved = json_copy(options)
    resolved["enabled"] = enabled
    return resolved


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
