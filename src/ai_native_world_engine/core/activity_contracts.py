"""Serializable coordination contracts above atomic Action Runtime V2."""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import json_copy


JsonDict = dict[str, object]
ACTIVE_ACTIVITY_STATUSES = frozenset({"planned", "running", "waiting"})
TERMINAL_ACTIVITY_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
MAX_ACTIVITY_HISTORY = 128
MAX_ACTIVITY_STEPS = 24
MAX_ACTIVITY_PARTICIPANTS = 16


@dataclass(slots=True)
class ActivityStep:
    action: str
    role: str
    behavior_label: str
    duration_ticks: int = 1
    channel: str = "physical"
    locks: list[str] = field(default_factory=list)
    parameters: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "action": self.action,
            "role": self.role,
            "behavior_label": self.behavior_label,
            "duration_ticks": max(int(self.duration_ticks), 1),
            "channel": self.channel,
            "locks": json_copy(self.locks[:16]),
            "parameters": json_copy(self.parameters),
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "ActivityStep":
        return cls(
            action=str(value.get("action", "")),
            role=str(value.get("role", "")),
            behavior_label=str(value.get("behavior_label", "")),
            duration_ticks=max(int(value.get("duration_ticks", 1) or 1), 1),
            channel=str(value.get("channel", "physical")),
            locks=[str(item) for item in _list(value.get("locks"))][:16],
            parameters=json_copy(_dict(value.get("parameters"))),
        )


@dataclass(slots=True)
class ActivityInstance:
    id: str
    definition_id: str
    status: str
    started_tick: int
    updated_tick: int
    steps: list[ActivityStep]
    participant_roles: dict[str, str]
    current_step: int = 0
    shared_target_id: str = ""
    root_causality_id: str = ""
    caused_by: list[str] = field(default_factory=list)
    status_reason: str = ""

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_ACTIVITY_STATUSES

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_ACTIVITY_STATUSES

    def to_dict(self) -> JsonDict:
        return {
            "schema": "ai-native-world.activity-instance.v1",
            "id": self.id,
            "definition_id": self.definition_id,
            "status": self.status,
            "started_tick": int(self.started_tick),
            "updated_tick": int(self.updated_tick),
            "steps": [item.to_dict() for item in self.steps[:MAX_ACTIVITY_STEPS]],
            "participant_roles": json_copy(
                dict(list(self.participant_roles.items())[:MAX_ACTIVITY_PARTICIPANTS])
            ),
            "current_step": max(int(self.current_step), 0),
            "shared_target_id": self.shared_target_id,
            "root_causality_id": self.root_causality_id,
            "caused_by": json_copy(self.caused_by[:16]),
            "status_reason": self.status_reason,
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "ActivityInstance":
        status = str(value.get("status", "planned"))
        if status not in ACTIVE_ACTIVITY_STATUSES | TERMINAL_ACTIVITY_STATUSES:
            raise ValueError(f"unknown activity status: {status}")
        roles = _dict(value.get("participant_roles"))
        return cls(
            id=str(value.get("id", "")),
            definition_id=str(value.get("definition_id", "")),
            status=status,
            started_tick=int(value.get("started_tick", 0) or 0),
            updated_tick=int(value.get("updated_tick", 0) or 0),
            steps=[
                ActivityStep.from_dict(item)
                for item in _list(value.get("steps"))[:MAX_ACTIVITY_STEPS]
                if isinstance(item, dict)
            ],
            participant_roles={str(key): str(item) for key, item in roles.items()},
            current_step=max(int(value.get("current_step", 0) or 0), 0),
            shared_target_id=str(value.get("shared_target_id", "")),
            root_causality_id=str(value.get("root_causality_id", "")),
            caused_by=[str(item) for item in _list(value.get("caused_by"))][:16],
            status_reason=str(value.get("status_reason", "")),
        )


def _dict(value: object) -> dict[str, object]:
    return json_copy(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
