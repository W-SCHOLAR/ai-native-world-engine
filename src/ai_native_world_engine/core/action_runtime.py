"""Authoritative lifecycle orchestration for V2 action packages."""

from __future__ import annotations

from typing import Iterable

from .action_contracts import (
    ACTION_RUNTIME_VERSION,
    ACTIVE_ACTION_STATUSES,
    TERMINAL_ACTION_STATUSES,
    ActionInstance,
    ActionRulePackageV2,
    ActionTransition,
)
from .events import TraceRecord, json_copy
from .feedback import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    FeedbackIngestor,
    effect,
    target,
)
from .rule_contracts import RuleCandidate
from .world import World


class LegacyRulePackageAdapter:
    """Marks V1 feedback as a same-tick terminal compatibility action."""

    runtime_version = 1

    def decorate(
        self, world: World, decision: RuleCandidate, feedback: ActionFeedback
    ) -> ActionFeedback:
        metadata = feedback.metadata.setdefault("action_lifecycle", {})
        if isinstance(metadata, dict):
            metadata.update(
                {
                    "runtime": "v1-adapter",
                    "status": "succeeded",
                    "started_tick": world.tick,
                    "updated_tick": world.tick,
                    "channel": str(decision.metadata.get("channel", "physical")),
                    "instantaneous": True,
                }
            )
        return feedback


class ActionRuntime:
    def __init__(self, ingestor: FeedbackIngestor | None = None) -> None:
        self.ingestor = ingestor or FeedbackIngestor()

    def advance(
        self,
        world: World,
        packages: dict[str, ActionRulePackageV2],
    ) -> None:
        for action_id in sorted(list(world.active_actions)):
            action = world.active_actions.get(action_id)
            if action is None:
                continue
            package = packages.get(action.package_id)
            if package is None:
                self._orphan(world, action)
                continue
            transition = package.advance(world, action)
            self._apply_transition(world, action, transition, phase="advance")

    def can_start(
        self,
        world: World,
        actor_id: str,
        channel: str,
        locks: Iterable[str] = (),
        *,
        interrupt_priority: float | None = None,
    ) -> bool:
        conflicts = self._conflicts(world, actor_id, channel, locks)
        if not conflicts:
            return True
        if interrupt_priority is None:
            return False
        priority = float(interrupt_priority)
        return all(
            action.interruptible and priority > action.interrupt_priority
            for action in conflicts
        )

    def start(
        self,
        world: World,
        package: ActionRulePackageV2,
        decision: RuleCandidate,
        packages: dict[str, ActionRulePackageV2] | None = None,
    ) -> dict[str, object] | None:
        transition = package.start(world, decision)
        if transition.status not in ACTIVE_ACTION_STATUSES | TERMINAL_ACTION_STATUSES:
            raise ValueError(f"invalid start transition status: {transition.status}")
        conflicts = self._conflicts(
            world, decision.node_id, transition.channel, transition.locks
        )
        if conflicts and not all(
            action.interruptible
            and transition.interrupt_priority > action.interrupt_priority
            for action in conflicts
        ):
            return None
        for current in conflicts:
            owner = (packages or {}).get(current.package_id)
            if owner is None:
                self._orphan(world, current)
                continue
            interrupted = self.interrupt(
                world,
                owner,
                current,
                reason=(
                    f"preempted_by:{decision.action}:"
                    f"{decision.node_id}:{transition.channel}"
                ),
            )
            if interrupted is None or interrupted.get("errors"):
                return None
        if not self.can_start(
            world, decision.node_id, transition.channel, transition.locks
        ):
            return None
        action_number = world.action_sequence + 1
        action_id = (
            f"action:{world.tick}:{action_number}:"
            f"{decision.node_id}:{transition.channel}"
        )
        pressure = decision.metadata.get("pressure", {})
        pressure_data = pressure if isinstance(pressure, dict) else {}
        causes = _string_list(decision.metadata.get("caused_by"))
        pressure_id = str(pressure_data.get("pressure_id", "")).strip()
        if pressure_id and pressure_id not in causes:
            causes.append(pressure_id)
        root_causality_id = str(
            decision.metadata.get("root_causality_id")
            or pressure_data.get("root_causality_id")
            or pressure_id
            or action_id
        )
        parameters = json_copy(transition.parameters)
        parameters["_causality"] = _decision_causality(decision)
        action = ActionInstance(
            id=action_id,
            definition_id=decision.action,
            package_id=package.name,
            package_version=str(package.version),
            actor_type="node",
            actor_id=decision.node_id,
            channel=transition.channel,
            target_ids=transition.target_ids,
            parameters=parameters,
            status=transition.status,
            started_tick=world.tick,
            updated_tick=world.tick,
            deadline_tick=transition.deadline_tick,
            progress=transition.progress,
            locks=transition.locks,
            interruptible=transition.interruptible,
            interrupt_priority=transition.interrupt_priority,
            root_causality_id=root_causality_id,
            caused_by=causes,
            behavior_label=transition.behavior_label or decision.action,
            salience=transition.salience,
            status_reason=transition.status_reason,
        )
        return self._apply_transition(
            world, action, transition, phase="start", decision=decision
        )

    def bind_pressure(
        self,
        world: World,
        action: ActionInstance,
        pressure: dict[str, object],
    ) -> dict[str, object] | None:
        """Ground a newly arrived pressure in an already-running action.

        This records an authoritative lifecycle update rather than restarting
        the action or replaying its start effects.
        """

        pressure_id = str(pressure.get("pressure_id", "")).strip()
        if not action.active or not pressure_id:
            return None
        causality = _action_causality(action)
        pressure_ids = causality["pressure_ids"]
        if pressure_id in pressure_ids:
            return None
        pressure_ids.append(pressure_id)
        provider_job_id = str(pressure.get("provider_job_id", "")).strip()
        if provider_job_id and provider_job_id not in causality["provider_job_ids"]:
            causality["provider_job_ids"].append(provider_job_id)
        option_id = str(pressure.get("option_id", "")).strip()
        if option_id:
            causality["selected_action_option_id"] = option_id
        causes = list(action.caused_by)
        if pressure_id not in causes:
            causes.append(pressure_id)
        rebound = ActionInstance.from_dict(action.to_dict())
        rebound.caused_by = causes[-16:]
        rebound.parameters["_causality"] = causality
        transition = ActionTransition(
            status=rebound.status,
            summary=(
                f"{rebound.actor_id} continues {rebound.definition_id} "
                f"for pressure {pressure_id}"
            ),
            channel=rebound.channel,
            target_ids=rebound.target_ids,
            parameters=rebound.parameters,
            progress=rebound.progress,
            locks=rebound.locks,
            interruptible=rebound.interruptible,
            interrupt_priority=rebound.interrupt_priority,
            deadline_tick=rebound.deadline_tick,
            behavior_label=rebound.behavior_label,
            salience=rebound.salience,
            status_reason=rebound.status_reason,
        )
        return self._apply_transition(
            world, rebound, transition, phase="pressure_bind"
        )

    def _conflicts(
        self,
        world: World,
        actor_id: str,
        channel: str,
        locks: Iterable[str],
    ) -> list[ActionInstance]:
        requested_locks = {str(item) for item in locks if str(item)}
        conflicts = [
            action
            for action in world.active_actions.values()
            if action.actor_id == actor_id
            and (
                action.channel == channel
                or bool(requested_locks.intersection(action.locks))
            )
        ]
        return sorted(conflicts, key=lambda item: item.id)

    def interrupt(
        self,
        world: World,
        package: ActionRulePackageV2,
        action: ActionInstance,
        reason: str,
    ) -> dict[str, object] | None:
        if not action.interruptible or not action.active:
            return None
        transition = package.interrupt(world, action, reason)
        if transition.status != "interrupted":
            raise ValueError("interrupt transition must use interrupted status")
        return self._apply_transition(world, action, transition, phase="interrupt")

    def _apply_transition(
        self,
        world: World,
        action: ActionInstance,
        transition: ActionTransition,
        *,
        phase: str,
        decision: RuleCandidate | None = None,
    ) -> dict[str, object]:
        next_action = ActionInstance.from_dict(action.to_dict())
        next_action.status = transition.status
        next_action.updated_tick = world.tick
        next_action.progress = transition.progress
        next_action.status_reason = transition.status_reason
        if transition.parameters:
            next_action.parameters.update(json_copy(transition.parameters))
        if transition.behavior_label:
            next_action.behavior_label = transition.behavior_label
        next_action.salience = transition.salience

        state_effect = (
            effect("action_state_finish", action=next_action.to_dict())
            if next_action.terminal
            else effect(
                "action_state_start" if phase == "start" else "action_state_update",
                action=next_action.to_dict(),
            )
        )
        feedback = ActionFeedback(
            source=f"action_runtime:{action.package_id}",
            actor_type=action.actor_type,
            actor_id=action.actor_id,
            action=action.definition_id,
            summary=transition.summary
            or f"{action.actor_id} {phase} {action.definition_id}",
            targets=[target("node", item) for item in action.target_ids],
            effects=[*transition.effects, state_effect],
            apply_mode=APPLY_AUTHORITATIVE,
            metadata={
                "action_lifecycle": {
                    "runtime_version": ACTION_RUNTIME_VERSION,
                    "action_id": action.id,
                    "phase": phase,
                    "status": next_action.status,
                    "channel": next_action.channel,
                    "progress": next_action.progress,
                },
                "root_causality_id": next_action.root_causality_id,
                "caused_by": json_copy(next_action.caused_by),
                **_feedback_causality(next_action),
                **(
                    {"decision_trace": decision.to_dict()}
                    if decision is not None
                    else {}
                ),
            },
        )
        recorded = self.ingestor.ingest(world, feedback)
        world.traces.record(
            TraceRecord(
                tick=world.tick,
                kind="action_lifecycle",
                source=feedback.source,
                observed={
                    "action_id": action.id,
                    "actor_id": action.actor_id,
                    "phase": phase,
                    "previous_status": action.status,
                    "root_causality_id": next_action.root_causality_id,
                    "caused_by": json_copy(next_action.caused_by),
                },
                selected={
                    "definition_id": action.definition_id,
                    "channel": action.channel,
                    "package_id": action.package_id,
                },
                delta={
                    "status": next_action.status,
                    "progress": next_action.progress,
                    "errors": json_copy(recorded.get("errors", [])),
                },
            )
        )
        if action.definition_id == "move":
            world.traces.record(
                TraceRecord(
                    tick=world.tick,
                    kind="movement",
                    source=feedback.source,
                    observed={
                        "node_id": action.actor_id,
                        "action_id": action.id,
                    },
                    selected={
                        "status": next_action.status,
                        "progress": next_action.progress,
                    },
                )
            )
        return recorded

    def _orphan(self, world: World, action: ActionInstance) -> None:
        transition = ActionTransition(
            status="failed",
            summary=f"{action.actor_id} action package is unavailable",
            channel=action.channel,
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=action.progress,
            locks=action.locks,
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason="package_unavailable_after_restore",
        )
        self._apply_transition(world, action, transition, phase="advance")


def is_v2_action_package(package: object) -> bool:
    return int(getattr(package, "action_runtime_version", 0) or 0) == 2


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)][:16]


def _decision_causality(decision: RuleCandidate) -> dict[str, object]:
    pressure = decision.metadata.get("pressure", {})
    pressure_data = pressure if isinstance(pressure, dict) else {}
    pressure_id = str(pressure_data.get("pressure_id", "")).strip()
    provider_job_id = str(pressure_data.get("provider_job_id", "")).strip()
    option_id = str(pressure_data.get("option_id", "")).strip()
    return {
        "pressure_ids": [pressure_id] if pressure_id else [],
        "provider_job_ids": [provider_job_id] if provider_job_id else [],
        "selected_action_option_id": option_id,
    }


def _action_causality(action: ActionInstance) -> dict[str, object]:
    raw = action.parameters.get("_causality", {})
    value = raw if isinstance(raw, dict) else {}
    return {
        "pressure_ids": _string_list(value.get("pressure_ids")),
        "provider_job_ids": _string_list(value.get("provider_job_ids")),
        "selected_action_option_id": str(
            value.get("selected_action_option_id", "")
        ),
    }


def _feedback_causality(action: ActionInstance) -> dict[str, object]:
    causality = _action_causality(action)
    result: dict[str, object] = {
        "caused_by_pressure_ids": json_copy(causality["pressure_ids"]),
        "caused_by_provider_job_ids": json_copy(causality["provider_job_ids"]),
    }
    option_id = str(causality["selected_action_option_id"])
    if option_id:
        result["selected_action_option_id"] = option_id
    return result
