"""Serializable contracts for authoritative actor actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TYPE_CHECKING

from .events import json_copy

if TYPE_CHECKING:
    from .feedback import WorldEffect
    from .rule_contracts import RuleCandidate
    from .world import World, WorldNode


JsonDict = dict[str, object]

ACTION_RUNTIME_VERSION = 2
ACTIVE_ACTION_STATUSES = frozenset({"starting", "running"})
TERMINAL_ACTION_STATUSES = frozenset(
    {"succeeded", "failed", "interrupted", "cancelled"}
)
ACTION_CHANNELS = frozenset({"physical", "social"})
MAX_ACTION_HISTORY = 256
MAX_ACTION_TARGETS = 16
MAX_ACTION_LOCKS = 16
MAX_ACTION_CAUSES = 16


@dataclass(slots=True)
class ActionInstance:
    id: str
    definition_id: str
    package_id: str
    package_version: str
    actor_type: str
    actor_id: str
    channel: str
    target_ids: list[str] = field(default_factory=list)
    parameters: JsonDict = field(default_factory=dict)
    status: str = "running"
    started_tick: int = 0
    updated_tick: int = 0
    deadline_tick: int | None = None
    progress: float = 0.0
    locks: list[str] = field(default_factory=list)
    interruptible: bool = True
    interrupt_priority: float = 0.0
    root_causality_id: str = ""
    caused_by: list[str] = field(default_factory=list)
    behavior_label: str = ""
    salience: float = 0.5
    status_reason: str = ""

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_ACTION_STATUSES

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_ACTION_STATUSES

    def to_dict(self) -> JsonDict:
        return {
            "schema": "ai-native-world.action-instance.v2",
            "id": self.id,
            "definition_id": self.definition_id,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "channel": self.channel,
            "target_ids": json_copy(self.target_ids[:MAX_ACTION_TARGETS]),
            "parameters": json_copy(self.parameters),
            "status": self.status,
            "started_tick": int(self.started_tick),
            "updated_tick": int(self.updated_tick),
            "deadline_tick": self.deadline_tick,
            "progress": _clamp(float(self.progress), 0.0, 1.0),
            "locks": json_copy(self.locks[:MAX_ACTION_LOCKS]),
            "interruptible": bool(self.interruptible),
            "interrupt_priority": float(self.interrupt_priority),
            "root_causality_id": self.root_causality_id,
            "caused_by": json_copy(self.caused_by[:MAX_ACTION_CAUSES]),
            "behavior_label": self.behavior_label,
            "salience": _clamp(float(self.salience), 0.0, 1.0),
            "status_reason": self.status_reason,
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "ActionInstance":
        status = str(value.get("status", "running"))
        if status not in ACTIVE_ACTION_STATUSES | TERMINAL_ACTION_STATUSES | {
            "planned"
        }:
            raise ValueError(f"unknown action status: {status}")
        channel = str(value.get("channel", "physical"))
        if channel not in ACTION_CHANNELS:
            raise ValueError(f"unknown action channel: {channel}")
        raw_targets = value.get("target_ids", [])
        raw_locks = value.get("locks", [])
        raw_causes = value.get("caused_by", [])
        raw_parameters = value.get("parameters", {})
        deadline = value.get("deadline_tick")
        return cls(
            id=str(value.get("id", "")),
            definition_id=str(value.get("definition_id", "")),
            package_id=str(value.get("package_id", "")),
            package_version=str(value.get("package_version", "1")),
            actor_type=str(value.get("actor_type", "node")),
            actor_id=str(value.get("actor_id", "")),
            channel=channel,
            target_ids=[str(item) for item in raw_targets][:MAX_ACTION_TARGETS]
            if isinstance(raw_targets, list)
            else [],
            parameters=json_copy(raw_parameters)
            if isinstance(raw_parameters, dict)
            else {},
            status=status,
            started_tick=int(value.get("started_tick", 0) or 0),
            updated_tick=int(value.get("updated_tick", 0) or 0),
            deadline_tick=int(deadline) if deadline is not None else None,
            progress=_clamp(float(value.get("progress", 0.0) or 0.0), 0.0, 1.0),
            locks=[str(item) for item in raw_locks][:MAX_ACTION_LOCKS]
            if isinstance(raw_locks, list)
            else [],
            interruptible=bool(value.get("interruptible", True)),
            interrupt_priority=float(value.get("interrupt_priority", 0.0) or 0.0),
            root_causality_id=str(value.get("root_causality_id", "")),
            caused_by=[str(item) for item in raw_causes][:MAX_ACTION_CAUSES]
            if isinstance(raw_causes, list)
            else [],
            behavior_label=str(value.get("behavior_label", "")),
            salience=_clamp(float(value.get("salience", 0.5) or 0.0), 0.0, 1.0),
            status_reason=str(value.get("status_reason", "")),
        )


@dataclass(slots=True)
class ActionTransition:
    """Pure package result; ActionRuntime owns ids, persistence and ingestion."""

    status: str = "running"
    summary: str = ""
    channel: str = "physical"
    target_ids: list[str] = field(default_factory=list)
    parameters: JsonDict = field(default_factory=dict)
    progress: float = 0.0
    locks: list[str] = field(default_factory=list)
    interruptible: bool = True
    interrupt_priority: float = 0.0
    deadline_tick: int | None = None
    behavior_label: str = ""
    salience: float = 0.5
    status_reason: str = ""
    effects: list[WorldEffect] = field(default_factory=list)


class ActionRulePackageV2(Protocol):
    name: str
    version: str
    action_runtime_version: int

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        ...

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        ...

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        ...

    def interrupt(
        self, world: World, action: ActionInstance, reason: str
    ) -> ActionTransition:
        ...


def _clamp(value: float, floor: float, ceiling: float) -> float:
    return min(max(value, floor), ceiling)

