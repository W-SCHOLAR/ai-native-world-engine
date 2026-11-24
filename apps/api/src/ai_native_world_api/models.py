"""Product-layer records for commercial API and worker skeletons."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


JsonDict = dict[str, Any]


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunControlState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELED = "canceled"


@dataclass(slots=True)
class ScenarioRecord:
    id: str
    name: str
    description: str
    source: str = "engine"
    defaults: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "defaults": self.defaults,
        }


@dataclass(slots=True)
class RunRecord:
    id: str
    scenario: str
    seed: int
    ticks: int
    owner_id: str = "local"
    status: RunStatus = RunStatus.QUEUED
    config: JsonDict = field(default_factory=dict)
    snapshot: JsonDict | None = None
    events: list[JsonDict] = field(default_factory=list)
    traces: list[JsonDict] = field(default_factory=list)
    scorecard: JsonDict = field(default_factory=dict)
    provider_execution_report: JsonDict = field(default_factory=dict)
    provider_attempt_report: JsonDict = field(default_factory=dict)
    provider_attempts: list[JsonDict] = field(default_factory=list)
    projection: JsonDict = field(default_factory=dict)
    timeline: list[JsonDict] = field(default_factory=list)
    provider_audits: list[JsonDict] = field(default_factory=list)
    status_events: list[JsonDict] = field(default_factory=list)
    interventions: list[JsonDict] = field(default_factory=list)
    sovereign_intents: list[JsonDict] = field(default_factory=list)
    sovereign_intent_audits: list[JsonDict] = field(default_factory=list)
    memory_consolidation_report: list[JsonDict] = field(default_factory=list)
    control_state: RunControlState = RunControlState.ACTIVE
    control_events: list[JsonDict] = field(default_factory=list)
    runtime_state: JsonDict = field(default_factory=dict)
    retry_of_run_id: str = ""
    replaced_by_run_id: str = ""
    retry_attempt: int = 0
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_summary_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "scenario": self.scenario,
            "seed": self.seed,
            "ticks": self.ticks,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "control_state": self.control_state.value,
            "runtime_state": _public_runtime_state(self.runtime_state),
            "bootstrap_state": _public_bootstrap_state(
                self.runtime_state, self.scenario, self.projection
            ),
            "retry_of_run_id": self.retry_of_run_id,
            "replaced_by_run_id": self.replaced_by_run_id,
            "retry_attempt": self.retry_attempt,
            "provider_attempt_report": self.provider_attempt_report,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_detail_dict(self) -> JsonDict:
        data = self.to_summary_dict()
        data.update(
            {
                "config": self.config,
                "snapshot": self.snapshot,
                "events": self.events,
                "traces": self.traces,
                "scorecard": self.scorecard,
                "provider_execution_report": self.provider_execution_report,
                "provider_attempt_report": self.provider_attempt_report,
                "provider_attempts": self.provider_attempts,
                "projection": self.projection,
                "timeline": self.timeline,
                "provider_audits": self.provider_audits,
                "status_events": self.status_events,
                "interventions": self.interventions,
                "sovereign_intents": self.sovereign_intents,
                "sovereign_intent_audits": self.sovereign_intent_audits,
                "memory_consolidation_report": self.memory_consolidation_report,
                "control_state": self.control_state.value,
                "control_events": self.control_events,
                "runtime_state": _public_runtime_state(self.runtime_state),
            }
        )
        return data

    def mark(self, status: RunStatus, error: str = "") -> None:
        self.status = status
        self.error = error
        self.updated_at = datetime.now(timezone.utc)
        self.status_events.append(
            {
                "type": _event_type(status),
                "run_id": self.id,
                "status": status.value,
                "message": f"Run {status.value}",
                "error": error,
                "timestamp": self.updated_at.isoformat(),
            }
        )

    def to_storage_dict(self) -> JsonDict:
        return self.to_detail_dict()

    def to_live_storage_dict(self) -> JsonDict:
        """Serialize bounded schema-v2 metadata for an active Run row."""

        return {
            "storage_schema": 2,
            **self.to_summary_dict(),
            "config": self.config,
            "status_events": self.status_events[-100:],
            "interventions": self.interventions,
            "sovereign_intents": self.sovereign_intents,
            "control_events": self.control_events[-100:],
        }

    @classmethod
    def from_storage_dict(cls, value: JsonDict) -> "RunRecord":
        record = cls(
            id=str(value["id"]),
            scenario=str(value["scenario"]),
            seed=int(value["seed"]),
            ticks=int(value["ticks"]),
            owner_id=str(value.get("owner_id", "local")),
            status=RunStatus(str(value.get("status", RunStatus.QUEUED.value))),
            config=_dict(value.get("config")),
            snapshot=_optional_dict(value.get("snapshot")),
            events=_list_of_dicts(value.get("events")),
            traces=_list_of_dicts(value.get("traces")),
            scorecard=_dict(value.get("scorecard")),
            provider_execution_report=_dict(value.get("provider_execution_report")),
            provider_attempt_report=_dict(value.get("provider_attempt_report")),
            provider_attempts=_list_of_dicts(value.get("provider_attempts")),
            projection=_dict(value.get("projection")),
            timeline=_list_of_dicts(value.get("timeline")),
            provider_audits=_list_of_dicts(value.get("provider_audits")),
            status_events=_list_of_dicts(value.get("status_events")),
            interventions=_list_of_dicts(value.get("interventions")),
            sovereign_intents=_list_of_dicts(value.get("sovereign_intents")),
            sovereign_intent_audits=_list_of_dicts(value.get("sovereign_intent_audits")),
            memory_consolidation_report=_list_of_dicts(value.get("memory_consolidation_report")),
            control_state=RunControlState(str(value.get("control_state", RunControlState.ACTIVE.value))),
            control_events=_list_of_dicts(value.get("control_events")),
            runtime_state=_dict(value.get("runtime_state")),
            retry_of_run_id=str(value.get("retry_of_run_id", "")),
            replaced_by_run_id=str(value.get("replaced_by_run_id", "")),
            retry_attempt=int(value.get("retry_attempt", 0) or 0),
            error=str(value.get("error", "")),
            created_at=_datetime(value.get("created_at")),
            updated_at=_datetime(value.get("updated_at")),
        )
        return record

    def control(
        self,
        command: str,
        reason: str = "",
        actor_id: str = "operator",
        submitted_by: str = "local",
    ) -> JsonDict:
        normalized = str(command).strip().lower()
        previous = self.control_state
        if normalized == "pause":
            self.control_state = RunControlState.PAUSED
        elif normalized == "resume":
            self.control_state = RunControlState.ACTIVE
        elif normalized == "cancel":
            self.control_state = RunControlState.CANCELED
        else:
            raise ValueError(f"unknown run control command: {command}")
        self.updated_at = datetime.now(timezone.utc)
        event = {
            "type": "run.control",
            "run_id": self.id,
            "command": normalized,
            "previous_control_state": previous.value,
            "control_state": self.control_state.value,
            "status": self.status.value,
            "reason": reason,
            "actor_id": actor_id,
            "submitted_by": submitted_by,
            "timestamp": self.updated_at.isoformat(),
        }
        self.control_events.append(event)
        self.status_events.append(
            {
                "type": "run.status",
                "run_id": self.id,
                "status": self.status.value,
                "message": f"Run control {normalized}",
                "control_state": self.control_state.value,
                "timestamp": self.updated_at.isoformat(),
            }
        )
        return event


def _dict(value: object) -> JsonDict:
    return dict(value) if isinstance(value, dict) else {}


def _optional_dict(value: object) -> JsonDict | None:
    return dict(value) if isinstance(value, dict) else None


def _list_of_dicts(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _datetime(value: object) -> datetime:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)


def _public_runtime_state(value: object) -> JsonDict:
    state = _dict(value)
    forbidden = {
        "session_checkpoint",
        "checkpoint",
        "world_snapshot",
        "pending_context",
        "context_packet",
    }
    result = {key: item for key, item in state.items() if key not in forbidden}
    pending = result.get("provider_pending")
    if isinstance(pending, list):
        result["provider_pending"] = [
            {
                key: item
                for key, item in entry.items()
                if key not in {"context_packet", "snapshot", "prompt", "response"}
            }
            for entry in pending[-32:]
            if isinstance(entry, dict)
        ]
    return result


def _public_bootstrap_state(
    value: object, scenario: str = "", projection: object = None
) -> JsonDict:
    state = _dict(value)
    bootstrap = _dict(state.get("bootstrap_state"))
    if not bootstrap and isinstance(projection, dict) and projection.get("summary"):
        bootstrap = {
            "phase": "legacy_ready",
            "scenario_id": str(scenario),
            "provider_mode": str(state.get("provider_mode", "legacy")),
            "provenance": "legacy",
            "ready": True,
            "retryable": False,
        }
    forbidden = {"api_key", "authorization", "prompt", "response", "headers"}
    return {
        key: item
        for key, item in bootstrap.items()
        if str(key).lower() not in forbidden
    }


def _event_type(status: RunStatus) -> str:
    if status == RunStatus.COMPLETED:
        return "run.completed"
    if status == RunStatus.FAILED:
        return "run.failed"
    return "run.status"
