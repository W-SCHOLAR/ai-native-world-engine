"""Authoritative domain lifecycle feedback helpers."""

from .events import TraceRecord
from .feedback import APPLY_AUTHORITATIVE, ActionFeedback, effect, target
from .rule_contracts import JsonDict, RuleCandidate
from .rule_support import _clamp
from .world import Position, World, WorldNode

def _feedback(
    decision: RuleCandidate,
    node: WorldNode,
    action: str,
    summary: str,
    effects: list[object],
    target_id: str | None = None,
) -> ActionFeedback:
    return ActionFeedback(
        source="rule_engine_set",
        actor_type="node",
        actor_id=node.id,
        action=action,
        summary=summary,
        targets=[target("node", target_id or node.id)],
        effects=effects,  # type: ignore[arg-type]
        apply_mode=APPLY_AUTHORITATIVE,
        metadata={"decision_trace": decision.to_dict()},
    )


def _domain_lifecycle_feedback(world: World, node: WorldNode) -> list[ActionFeedback]:
    feedbacks: list[ActionFeedback] = []
    infection = node.attributes.get("infection")
    if isinstance(infection, dict):
        feedback = _infection_lifecycle_feedback(world, node, infection)
        if feedback is not None:
            feedbacks.append(feedback)
    policies = node.attributes.get("policies")
    if isinstance(policies, dict):
        feedback = _policy_lifecycle_feedback(node, policies)
        if feedback is not None:
            feedbacks.append(feedback)
    migration = node.attributes.get("migration")
    if isinstance(migration, dict):
        feedback = _migration_lifecycle_feedback(node, migration)
        if feedback is not None:
            feedbacks.append(feedback)
    if feedbacks:
        world.traces.record(
            TraceRecord(
                tick=world.tick,
                kind="domain_lifecycle",
                source="rule_engine_set",
                observed={"node_id": node.id},
                delta={"feedback_count": len(feedbacks)},
            )
        )
    return feedbacks


def _infection_lifecycle_feedback(world: World, node: WorldNode, infection: JsonDict) -> ActionFeedback | None:
    status = str(infection.get("status", ""))
    if status not in {"exposed", "infectious"}:
        return None
    if int(infection.get("tick", -1) or -1) >= world.tick:
        return None
    age = int(infection.get("age", 0) or 0) + 1
    incubation_ticks = max(int(infection.get("incubation_ticks", 1) or 1), 0)
    infectious_ticks = max(int(infection.get("infectious_ticks", 2) or 2), 0)
    next_status = status
    if status == "exposed" and age >= incubation_ticks:
        next_status = "infectious"
    if next_status == "infectious" and age >= incubation_ticks + infectious_ticks:
        next_status = "recovered"
    effects = [
        effect(
            "infection_state",
            target=f"node:{node.id}",
            pathogen=str(infection.get("pathogen", "scenario_pathogen")),
            status=next_status,
            severity=float(infection.get("severity", 1.0) or 1.0),
            age=age,
            incubation_ticks=incubation_ticks,
            infectious_ticks=infectious_ticks,
            damage_per_tick=float(infection.get("damage_per_tick", 0.0) or 0.0),
        )
    ]
    if next_status == "infectious":
        damage = float(infection.get("damage_per_tick", 0.0) or 0.0)
        if damage > 0:
            effects.append(effect("health_delta", target=f"node:{node.id}", delta=-damage, floor=0))
        source_contact_factor = _contact_factor(node)
        if not _is_quarantined(node) and source_contact_factor > 0:
            pathogen = str(infection.get("pathogen", "scenario_pathogen"))
            spread_limit = max(int(infection.get("spread_limit", 3) or 3), 0)
            effective_spread_limit = int(spread_limit * source_contact_factor)
            spread_count = 0
            for target_node in _contact_targets(world, node):
                if spread_count >= effective_spread_limit:
                    break
                if (
                    _is_quarantined(target_node)
                    or _contact_factor(target_node) <= 0
                    or not _is_susceptible(target_node, pathogen)
                ):
                    continue
                spread_count += 1
                effects.extend(
                    [
                        effect(
                            "infection_state",
                            target=f"node:{target_node.id}",
                            pathogen=pathogen,
                            status="exposed",
                            severity=float(infection.get("severity", 1.0) or 1.0),
                            age=0,
                            incubation_ticks=infection.get("incubation_ticks", 1),
                            infectious_ticks=infection.get("infectious_ticks", 2),
                            damage_per_tick=infection.get("damage_per_tick", 0.0),
                            spread_from=f"node:{node.id}",
                        ),
                        effect(
                            "action_bullet_add",
                            target=f"node:{target_node.id}",
                            text="接触暴露",
                            source="infection_lifecycle",
                            salience=0.5,
                        ),
                    ]
                )
    if next_status != status:
        effects.append(
            effect(
                "action_bullet_add",
                target=f"node:{node.id}",
                text=f"感染{next_status}",
                source="infection_lifecycle",
                salience=0.5,
            )
        )
    return ActionFeedback(
        source="rule_lifecycle",
        actor_type="node",
        actor_id=node.id,
        action="infection_progress",
        summary=f"{node.name} infection state progressed to {next_status}",
        targets=[target("node", node.id)],
        effects=effects,
        apply_mode=APPLY_AUTHORITATIVE,
        metadata={"lifecycle": {"kind": "infection", "previous_status": status, "next_status": next_status}},
    )


def _policy_lifecycle_feedback(node: WorldNode, policies: JsonDict) -> ActionFeedback | None:
    effects: list[object] = []
    for policy, state in sorted(policies.items()):
        if not isinstance(state, dict) or state.get("status") != "active":
            continue
        if "remaining_ticks" not in state:
            continue
        remaining = max(int(state.get("remaining_ticks", 0) or 0) - 1, 0)
        effects.append(
            effect(
                "policy_state",
                target=f"node:{node.id}",
                policy=str(policy),
                status="expired" if remaining == 0 else "active",
                remaining_ticks=remaining,
            )
        )
    if not effects:
        return None
    return ActionFeedback(
        source="rule_lifecycle",
        actor_type="node",
        actor_id=node.id,
        action="policy_lifecycle",
        summary=f"{node.name} policy durations advanced",
        targets=[target("node", node.id)],
        effects=effects,  # type: ignore[arg-type]
        apply_mode=APPLY_AUTHORITATIVE,
        metadata={"lifecycle": {"kind": "policy", "updated": len(effects)}},
    )


def _contact_targets(world: World, node: WorldNode) -> list[WorldNode]:
    contact_types = {"contact", "proximity", "cohort_contact", "co_location", "接触"}
    targets: list[WorldNode] = []
    seen: set[str] = set()
    for edge in world.relationships.values():
        if edge.type not in contact_types:
            continue
        target_id = ""
        if edge.source == node.id:
            target_id = edge.target
        elif edge.target == node.id:
            target_id = edge.source
        if not target_id or target_id in seen or not world.has_node(target_id):
            continue
        seen.add(target_id)
        targets.append(world.node(target_id))
    targets.sort(key=lambda item: item.id)
    return targets


def _is_susceptible(node: WorldNode, pathogen: str) -> bool:
    infection = node.attributes.get("infection")
    if not isinstance(infection, dict):
        return True
    if str(infection.get("pathogen", "")) != pathogen:
        return True
    return str(infection.get("status", "")) not in {"exposed", "infectious", "recovered"}


def _is_quarantined(node: WorldNode) -> bool:
    policies = node.attributes.get("policies")
    if not isinstance(policies, dict):
        return False
    for name, state in policies.items():
        if not isinstance(state, dict):
            continue
        policy_name = str(name).lower()
        status = str(state.get("status", "")).lower()
        if status != "active":
            continue
        if policy_name in {"quarantine", "isolation", "district_lockdown"}:
            return True
        if bool(state.get("blocks_movement")) or bool(state.get("blocks_contact")):
            return True
    return False


def _contact_factor(node: WorldNode) -> float:
    return _policy_factor(
        node,
        multiplier_keys={"contact_multiplier", "contact_factor"},
        reduction_keys={"contact_reduction", "contact_reduction_ratio"},
        block_keys={"blocks_contact"},
    )


def _movement_factor(node: WorldNode) -> float:
    return _policy_factor(
        node,
        multiplier_keys={"movement_multiplier", "movement_factor"},
        reduction_keys={"movement_reduction", "movement_reduction_ratio"},
        block_keys={"blocks_movement"},
    )


def _policy_factor(
    node: WorldNode,
    *,
    multiplier_keys: set[str],
    reduction_keys: set[str],
    block_keys: set[str],
) -> float:
    policies = node.attributes.get("policies")
    if not isinstance(policies, dict):
        return 1.0
    factor = 1.0
    for name, state in policies.items():
        if not isinstance(state, dict) or str(state.get("status", "")).lower() != "active":
            continue
        if str(name).lower() in {"quarantine", "isolation", "district_lockdown"}:
            return 0.0
        if any(bool(state.get(key)) for key in block_keys):
            return 0.0
        for key in multiplier_keys:
            if key in state:
                factor *= _clamp(float(state.get(key, 1.0) or 0.0), 0.0, 1.0)
        for key in reduction_keys:
            if key in state:
                factor *= 1.0 - _clamp(float(state.get(key, 0.0) or 0.0), 0.0, 1.0)
    return _clamp(factor, 0.0, 1.0)


def _migration_lifecycle_feedback(node: WorldNode, migration: JsonDict) -> ActionFeedback | None:
    if migration.get("status") != "migrating":
        return None
    destination_position = migration.get("destination_position")
    if destination_position in (None, "", {}):
        return None
    base_speed = float(migration.get("base_speed", migration.get("speed", 0.0)) or 0.0)
    speed = base_speed * _movement_factor(node)
    if base_speed <= 0:
        return None
    if _is_quarantined(node) or speed <= 0:
        return ActionFeedback(
            source="rule_lifecycle",
            actor_type="node",
            actor_id=node.id,
            action="migration_blocked",
            summary=f"{node.name} migration blocked by policy",
            targets=[target("node", node.id)],
            effects=[
                effect(
                    "migration_state",
                    target=f"node:{node.id}",
                    destination=str(migration.get("destination", "")),
                    status="migrating",
                    destination_position=destination_position,
                    speed=base_speed,
                    base_speed=base_speed,
                    effective_speed=speed,
                    progress=float(migration.get("progress", 0.0) or 0.0),
                    blocked_by_policy="quarantine" if _is_quarantined(node) else "movement",
                    blocked_ticks=int(migration.get("blocked_ticks", 0) or 0) + 1,
                )
            ],
            apply_mode=APPLY_AUTHORITATIVE,
            metadata={"lifecycle": {"kind": "migration", "blocked": True}},
        )
    target_position = Position.from_value(destination_position)  # type: ignore[arg-type]
    next_position, arrived = node.position.step_toward(target_position, speed)
    distance_total = node.position.distance_to(target_position)
    remaining_after = next_position.distance_to(target_position)
    progress = 1.0 if arrived or distance_total == 0 else max(0.0, min(1.0, 1.0 - remaining_after / distance_total))
    effects = [
        effect("node_position", target=f"node:{node.id}", position=next_position.to_dict(), arrived=arrived),
        effect(
            "migration_state",
            target=f"node:{node.id}",
            destination=str(migration.get("destination", "")),
            status="arrived" if arrived else "migrating",
            destination_position=target_position.to_dict(),
            speed=base_speed,
            base_speed=base_speed,
            effective_speed=speed,
            progress=round(progress, 4),
        ),
    ]
    if arrived:
        effects.append(
            effect("action_bullet_add", target=f"node:{node.id}", text="抵达", source="migration_lifecycle", salience=0.52)
        )
    return ActionFeedback(
        source="rule_lifecycle",
        actor_type="node",
        actor_id=node.id,
        action="migration_progress",
        summary=f"{node.name} migration progressed",
        targets=[target("node", node.id)],
        effects=effects,
        apply_mode=APPLY_AUTHORITATIVE,
        metadata={
            "lifecycle": {
                "kind": "migration",
                "destination": migration.get("destination", ""),
                "arrived": arrived,
            }
        },
    )


