"""Deterministic staged activities for the Tribe Survival worldline."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any

from ai_native_world_engine.core.action_contracts import ActionInstance, ActionTransition
from ai_native_world_engine.core.activity_contracts import ActivityInstance, ActivityStep
from ai_native_world_engine.core.events import json_copy
from ai_native_world_engine.core.feedback import APPLY_AUTHORITATIVE, ActionFeedback, effect, target
from ai_native_world_engine.core.rule_contracts import JsonDict, RuleCandidate
from ai_native_world_engine.core.world import World, WorldNode


FOOD_STEPS = (
    ActivityStep("food_assess", "quartermaster", "盘点粮食", 1, locks=["attention"]),
    ActivityStep("food_source_select", "hunter", "选择采集路线", 1, locks=["attention"]),
    ActivityStep("food_travel_out", "hunter", "前往河谷猎场", 2, locks=["locomotion"]),
    ActivityStep("food_gather", "hunter", "采集并狩猎", 2, locks=["hands", "attention"]),
    ActivityStep("food_return", "carrier", "搬运食物返回", 2, locks=["locomotion", "hands"]),
    ActivityStep("food_store", "quartermaster", "清点食物入仓", 1, locks=["hands"]),
    ActivityStep("food_distribute", "quartermaster", "分配今日口粮", 1, locks=["hands", "attention"]),
    ActivityStep("food_eat", "consumer", "进食恢复体力", 1, locks=["hands"]),
)

DEFENSE_STEPS = (
    ActivityStep("defense_inspect", "guard", "检查北门缺口", 1, locks=["attention"]),
    ActivityStep("material_haul", "carrier", "搬运修墙木材", 2, locks=["locomotion", "hands"]),
    ActivityStep("gate_repair", "builder", "修补北门木墙", 3, locks=["hands", "attention"]),
    ActivityStep("guard_patrol", "guard", "沿北门防线巡逻", 2, locks=["locomotion", "attention"]),
    ActivityStep("stand_watch", "guard", "守卫施工现场", 2, locks=["attention"]),
)

CARE_STEPS = (
    ActivityStep("injury_assess", "healer", "检查伤员伤势", 1, locks=["attention"]),
    ActivityStep("wounded_carry", "carrier", "搬运伤员", 2, locks=["locomotion", "hands"]),
    ActivityStep("medical_treat", "healer", "清创并施药", 2, locks=["hands", "attention"]),
    ActivityStep("patient_aftercare", "healer", "照料伤员恢复", 2, locks=["hands"]),
)

DAILY_STEPS = (
    ActivityStep("meal_prepare", "quartermaster", "准备公共餐食", 2, locks=["hands"]),
    ActivityStep("equipment_maintain", "builder", "维护工具装备", 2, locks=["hands"]),
    ActivityStep("fire_tend", "healer", "照看公共篝火", 2, locks=["hands"]),
    ActivityStep("stores_inspect", "quartermaster", "检查粮仓库存", 2, locks=["attention"]),
    ActivityStep("social_check_in", "guard", "询问同伴近况", 1, channel="social", locks=["voice"]),
)

DUTY_STEPS_BY_NETWORK = {
    "ember-guard": (
        ActivityStep("duty_patrol", "member", "巡查营地边界", 3, locks=["locomotion", "attention"]),
        ActivityStep("duty_equipment", "member", "整理守卫装备", 2, locks=["hands"]),
    ),
    "river-scouts": (
        ActivityStep("duty_tracks", "member", "辨认河谷足迹", 3, locks=["attention"]),
        ActivityStep("duty_map", "member", "修订侦察地图", 2, locks=["hands", "attention"]),
    ),
    "stone-builders": (
        ActivityStep("duty_tools", "member", "保养石木工具", 2, locks=["hands"]),
        ActivityStep("duty_materials", "member", "清点修墙材料", 3, locks=["hands", "attention"]),
    ),
    "dawn-hunters": (
        ActivityStep("duty_arrows", "member", "检查狩猎箭矢", 2, locks=["hands"]),
        ActivityStep("duty_traps", "member", "查看河谷陷阱", 3, locks=["locomotion", "attention"]),
    ),
    "elder-council": (
        ActivityStep("duty_records", "member", "整理部落记录", 3, locks=["hands", "attention"]),
        ActivityStep("duty_rations", "member", "核对今日配给", 2, locks=["attention"]),
    ),
    "ash-shamans": (
        ActivityStep("duty_herbs", "member", "整理疗伤草药", 2, locks=["hands"]),
        ActivityStep("duty_fire", "member", "照看仪式火种", 3, locks=["hands", "attention"]),
    ),
    "granary-keepers": (
        ActivityStep("duty_inventory", "member", "检查粮仓库存", 3, locks=["attention"]),
        ActivityStep("duty_seeds", "member", "翻晒储备种子", 2, locks=["hands"]),
    ),
    "fire-diplomats": (
        ActivityStep("duty_gifts", "member", "整理会谈礼物", 2, locks=["hands"]),
        ActivityStep("duty_translation", "member", "校对部落口信", 3, locks=["attention"]),
    ),
    "black-hill-tribe": (
        ActivityStep("duty_enemy_scout", "member", "侦察我方营火", 3, locks=["locomotion", "attention"]),
        ActivityStep("duty_enemy_arms", "member", "打磨黑山武器", 2, locks=["hands"]),
    ),
    "wolf-tooth-raiders": (
        ActivityStep("duty_raider_scout", "member", "寻找夜袭路线", 3, locks=["locomotion", "attention"]),
        ActivityStep("duty_raider_arms", "member", "检查掠夺装备", 2, locks=["hands"]),
    ),
    "salt-road-caravan": (
        ActivityStep("duty_trade_goods", "member", "清点盐路货物", 2, locks=["hands", "attention"]),
        ActivityStep("duty_pack", "member", "捆扎商队行囊", 3, locks=["hands"]),
    ),
}

KEY_CHARACTER_DUTIES = {
    "chieftain-aya": ActivityStep("duty_lead", "member", "巡视部落营地", 3, locks=["locomotion", "attention"]),
    "captain-tor": ActivityStep("duty_command", "member", "检查北门守备", 3, locks=["locomotion", "attention"]),
    "scout-nara": ActivityStep("duty_recon", "member", "复核敌方足迹", 3, locks=["locomotion", "attention"]),
    "shaman-ru": ActivityStep("duty_medicine", "member", "准备疗伤药材", 2, locks=["hands"]),
    "builder-kun": ActivityStep("duty_build_plan", "member", "检查木墙结构", 3, locks=["attention"]),
    "young-chief-ren": ActivityStep("duty_training", "member", "操练年轻战士", 3, locks=["body", "attention"]),
    "injured-scout": ActivityStep("duty_recover", "member", "静养恢复伤势", 3, locks=["body"]),
}

MEMBER_DUTY_ACTIONS = {
    step.action
    for steps in DUTY_STEPS_BY_NETWORK.values()
    for step in steps
} | {step.action for step in KEY_CHARACTER_DUTIES.values()}

ALL_ACTIONS = {
    step.action
    for step in (*FOOD_STEPS, *DEFENSE_STEPS, *CARE_STEPS, *DAILY_STEPS)
} | MEMBER_DUTY_ACTIONS

URGENT_PHYSICAL_PRESSURES = (ALL_ACTIONS - MEMBER_DUTY_ACTIONS) | {
    "combat",
    "combat_attack",
    "move",
    "movement",
}


@dataclass(slots=True)
class TribeActivityRulePackage:
    name: str = "tribe_activity_actions"
    version: str = "1"
    action_runtime_version: int = 2

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        result: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            action = str(pressure.get("rule", ""))
            if action not in ALL_ACTIONS:
                continue
            result.append(
                RuleCandidate(
                    node_id=node.id,
                    action=action,
                    score=3.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", action)),
                    metadata={
                        "pressure": json_copy(pressure),
                        "channel": str(pressure.get("channel", "physical")),
                        "locks": _strings(pressure.get("locks")),
                        "activity_id": str(pressure.get("activity_id", "")),
                        "activity_step": int(pressure.get("activity_step", 0) or 0),
                        "interrupt_priority": float(
                            pressure.get("interrupt_priority", 0.0) or 0.0
                        ),
                    },
                )
            )
        return result

    def derive_pressures(self, world: World) -> list[ActionFeedback]:
        if world.attributes.get("scenario") != "tribe_survival":
            return []
        effects: list[Any] = []
        for activity in sorted(world.active_activities.values(), key=lambda item: item.id):
            if activity.definition_id not in {"food_cycle", "defense_cycle", "care_cycle", "daily_duty"}:
                continue
            queued = _step_pressure(world, activity)
            if queued is not None:
                effects.append(queued)

        if not _has_activity(world, "food_cycle") and _resource(world, "granary-keepers", "food") < 24:
            effects.extend(self._create_activity(world, "food_cycle", FOOD_STEPS, "granary-keepers"))
        if not _has_activity(world, "defense_cycle") and _number(world.node("ember-guard").attributes.get("defense_rating")) < 9:
            effects.extend(self._create_activity(world, "defense_cycle", DEFENSE_STEPS, "ember-guard"))
        injured = world.node("injured-scout")
        if not _has_activity(world, "care_cycle") and _number(injured.attributes.get("health")) < _number(injured.attributes.get("max_health", 10)):
            effects.extend(self._create_activity(world, "care_cycle", CARE_STEPS, injured.id))
        urgent = sum(
            1
            for item in world.active_activities.values()
            if item.definition_id in {"food_cycle", "defense_cycle", "care_cycle"}
        )
        if urgent == 0 and not _has_activity(world, "daily_duty"):
            step = DAILY_STEPS[world.activity_sequence % len(DAILY_STEPS)]
            effects.extend(self._create_activity(world, "daily_duty", (step,), "ember-guard"))
        effects.extend(_member_duty_pressures(world))
        if not effects:
            return []
        return [
            ActionFeedback(
                source=self.name,
                actor_type="system",
                actor_id=self.name,
                action="coordinate_tribe_activities",
                summary=f"协调 {len(effects)} 项部落活动状态",
                targets=[target("world", world.id)],
                effects=effects,
                apply_mode=APPLY_AUTHORITATIVE,
            )
        ]

    def _create_activity(
        self,
        world: World,
        definition_id: str,
        steps: tuple[ActivityStep, ...],
        shared_target_id: str,
    ) -> list[Any]:
        activity_id = f"activity:{world.tick}:{world.activity_sequence + len(world.active_activities) + 1}:{definition_id}"
        roles = sorted({step.role for step in steps})
        assignments: dict[str, str] = {}
        assigned_actor_ids: set[str] = set()
        for role in roles:
            actor_id = _assign_role(
                world, role, shared_target_id, excluded_actor_ids=assigned_actor_ids
            )
            assignments[role] = actor_id
            assigned_actor_ids.add(actor_id)
        activity = ActivityInstance(
            id=activity_id,
            definition_id=definition_id,
            status="running",
            started_tick=world.tick,
            updated_tick=world.tick,
            steps=list(steps),
            participant_roles=assignments,
            current_step=0,
            shared_target_id=shared_target_id,
            root_causality_id=activity_id,
            caused_by=[f"need:{definition_id}:{world.tick}"],
        )
        return [
            effect("activity_state_upsert", activity=activity.to_dict()),
            _pressure_for(activity, activity.steps[0]),
        ]

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        pressure = _dict(candidate.metadata.get("pressure"))
        if candidate.action in MEMBER_DUTY_ACTIONS:
            return _start_member_duty(world, candidate, pressure)
        activity_id = str(pressure.get("activity_id", ""))
        activity = world.active_activities.get(activity_id)
        step_index = int(pressure.get("activity_step", 0) or 0)
        if activity is None or activity.current_step != step_index or step_index >= len(activity.steps):
            return ActionTransition(status="failed", summary="活动步骤已失效", status_reason="stale_activity_step")
        step = activity.steps[step_index]
        return ActionTransition(
            status="running",
            summary=f"{world.node(candidate.node_id).name} 开始{step.behavior_label}",
            channel=step.channel,
            target_ids=[activity.shared_target_id] if activity.shared_target_id else [],
            parameters={"activity_id": activity.id, "activity_step": step_index, "activity_role": step.role},
            progress=0.0,
            locks=step.locks,
            interrupt_priority=0.82,
            deadline_tick=world.tick + step.duration_ticks,
            behavior_label=step.behavior_label,
            salience=0.72,
        )

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        if action.definition_id in MEMBER_DUTY_ACTIONS:
            return _advance_member_duty(world, action)
        activity_id = str(action.parameters.get("activity_id", ""))
        activity = world.active_activities.get(activity_id)
        if activity is None:
            return _terminal(action, "failed", "所属活动不存在", "activity_missing")
        step_index = int(action.parameters.get("activity_step", 0) or 0)
        if step_index != activity.current_step:
            return _terminal(action, "cancelled", "活动已经推进", "step_already_advanced")
        deadline = action.deadline_tick or action.started_tick + 1
        if world.tick < deadline:
            duration = max(deadline - action.started_tick, 1)
            return ActionTransition(
                status="running",
                summary=f"{world.node(action.actor_id).name} 正在{action.behavior_label}",
                channel=action.channel,
                target_ids=action.target_ids,
                parameters=action.parameters,
                progress=min(1.0, (world.tick - action.started_tick) / duration),
                locks=action.locks,
                interrupt_priority=action.interrupt_priority,
                deadline_tick=deadline,
                behavior_label=action.behavior_label,
                salience=action.salience,
            )
        effects = _step_effects(world, action.definition_id, activity)
        advanced = ActivityInstance.from_dict(activity.to_dict())
        advanced.current_step += 1
        advanced.updated_tick = world.tick
        if advanced.current_step >= len(advanced.steps):
            advanced.status = "succeeded"
            advanced.status_reason = "completed"
        effects.append(effect("activity_state_upsert", activity=advanced.to_dict()))
        if advanced.active:
            effects.append(_pressure_for(advanced, advanced.steps[advanced.current_step]))
        return ActionTransition(
            status="succeeded",
            summary=f"{world.node(action.actor_id).name} 完成{action.behavior_label}",
            channel=action.channel,
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=1.0,
            locks=action.locks,
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason="completed",
            effects=effects,
        )

    def interrupt(self, world: World, action: ActionInstance, reason: str) -> ActionTransition:
        return _terminal(action, "interrupted", f"{world.node(action.actor_id).name} 中断{action.behavior_label}", reason)


def _step_effects(world: World, action: str, activity: ActivityInstance) -> list[Any]:
    actors = activity.participant_roles
    if action == "food_travel_out":
        return [effect("node_position", target=f"node:{actors['hunter']}", position={"x": 35, "y": 62})]
    if action == "food_gather":
        return [effect("resource_delta", target=f"node:{actors['hunter']}", resource="food", delta=6)]
    if action == "food_return":
        return [effect("node_position", target=f"node:{actors['carrier']}", position=world.node("granary-keepers").position.to_dict())]
    if action == "food_store":
        return [effect("resource_transfer", **{"from": f"node:{actors['hunter']}", "to": "node:granary-keepers", "resource": "food", "amount": 6})]
    if action == "food_distribute":
        return [effect("resource_transfer", **{"from": "node:granary-keepers", "to": f"node:{actors['consumer']}", "resource": "food", "amount": 2})]
    if action == "food_eat":
        return [effect("resource_delta", target=f"node:{actors['consumer']}", resource="food", delta=-1, floor=0), effect("health_delta", target=f"node:{actors['consumer']}", delta=1, ceiling=10)]
    if action == "gate_repair":
        return [effect("resource_delta", target=f"node:{actors['builder']}", resource="wood", delta=-3, floor=0), effect("node_attribute_delta", target="node:ember-guard", field="defense_rating", delta=2, ceiling=10)]
    if action == "medical_treat":
        return [effect("resource_delta", target=f"node:{actors['healer']}", resource="medicine", delta=-1, floor=0), effect("health_delta", target="node:injured-scout", delta=4, ceiling=10)]
    if action == "patient_aftercare":
        return [effect("health_delta", target="node:injured-scout", delta=1, ceiling=10), effect("memory_add", target="node:injured-scout", text="同伴完成了搬运、治疗和后续照料。", source="tribe_activity_actions", importance=0.8)]
    return []


def _assign_role(
    world: World,
    role: str,
    target_id: str,
    *,
    excluded_actor_ids: set[str] | None = None,
) -> str:
    target_node = world.node(target_id) if world.has_node(target_id) else None
    scored: list[tuple[float, str]] = []
    excluded = excluded_actor_ids or set()
    for node in world.nodes.values():
        if node.attributes.get("faction") != "home_tribe" or node.attributes.get("alive", True) is False:
            continue
        if node.id in excluded:
            continue
        if node.type not in {"organization_member", "key_character", "person"}:
            continue
        if node.type == "organization_member" and not node.attributes.get(
            "viewer_behavior_actor", False
        ):
            continue
        if any(
            item.actor_id == node.id
            and item.channel == "physical"
            and item.definition_id not in MEMBER_DUTY_ACTIONS
            for item in world.active_actions.values()
        ):
            continue
        if node.movement_target is not None and not node.attributes.get(
            "movement_arrived", False
        ):
            continue
        if any(
            str(item.get("rule", "")) in URGENT_PHYSICAL_PRESSURES
            for item in node.rule_pressures
        ):
            continue
        score = _role_score(node, role)
        if target_node is not None:
            score -= hypot(node.position.x - target_node.position.x, node.position.y - target_node.position.y) * 0.01
        scored.append((score, node.id))
    if not scored:
        raise ValueError(f"no activity participant for role {role}")
    return max(scored, key=lambda item: (item[0], tuple(-ord(ch) for ch in item[1])))[1]


def _role_score(node: WorldNode, role: str) -> float:
    loop = str(node.attributes.get("survival_loop", ""))
    kind = str(node.attributes.get("role", node.attributes.get("organization_kind", "")))
    parent = str(node.attributes.get("parent_network", ""))
    identity = str(node.attributes.get("identity", ""))
    resources = _dict(node.attributes.get("resources"))
    expected = {
        "hunter": "food", "carrier": "scouting", "quartermaster": "food",
        "consumer": "tribe_leader", "builder": "shelter", "guard": "defense",
        "healer": "memory_keeper",
    }
    score = 10.0 if expected.get(role, "") in {loop, kind} else 0.0
    preferred_network = {
        "hunter": "dawn-hunters",
        "carrier": "river-scouts",
        "quartermaster": "granary-keepers",
        "builder": "stone-builders",
        "guard": "ember-guard",
        "healer": "ash-shamans",
    }
    if preferred_network.get(role) == parent:
        score += 30
    if node.type == "organization_member":
        score += 8
    role_tokens = {
        "hunter": ("猎", "弓", "采集"),
        "carrier": ("信使", "斥候", "搬", "补给"),
        "quartermaster": ("配给", "账房", "仓", "种子"),
        "builder": ("匠", "塔工", "仓屋"),
        "guard": ("哨", "盾", "火把", "战士"),
        "healer": ("医", "草药", "祭司"),
    }
    if any(token in kind for token in role_tokens.get(role, ())):
        score += 12
    if role == "consumer" and identity == "tribe_leader":
        score += 20
    if role == "hunter" and "arrows" in resources:
        score += 5
    if role == "quartermaster" and "seed" in resources:
        score += 6
    if role == "builder" and "wood" in resources:
        score += 6
    if role == "healer" and "medicine" in resources:
        score += 7
    if role == "consumer" and node.id == "chieftain-aya":
        score += 6
    return score


def _member_duty_pressures(world: World) -> list[Any]:
    effects: list[Any] = []
    for node in sorted(world.nodes.values(), key=lambda item: item.id):
        if not node.attributes.get("viewer_behavior_actor", False):
            continue
        if node.attributes.get("alive", True) is False:
            continue
        if any(
            item.actor_id == node.id and item.channel == "physical"
            for item in world.active_actions.values()
        ):
            continue
        if node.movement_target is not None and not node.attributes.get(
            "movement_arrived", False
        ):
            continue
        if any(
            str(item.get("rule", "")) in URGENT_PHYSICAL_PRESSURES
            for item in node.rule_pressures
        ):
            continue
        if any(
            str(item.get("rule", "")) in MEMBER_DUTY_ACTIONS
            for item in node.rule_pressures
        ):
            continue
        duty = _duty_for_node(world, node)
        if duty is None:
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{node.id}",
                rule=duty.action,
                weight=0.36,
                ttl=max(duty.duration_ticks + 2, 4),
                source="tribe_member_duty",
                reason="没有更高优先级任务时继续角色日常",
                pressure_id=f"tribe-duty:{node.id}:{world.tick}",
                channel=duty.channel,
                locks=duty.locks,
                behavior_label=duty.behavior_label,
                duration_ticks=duty.duration_ticks,
                root_causality_id=f"tribe-duty:{node.id}",
                interrupt_priority=0.1,
            )
        )
    return effects


def _duty_for_node(world: World, node: WorldNode) -> ActivityStep | None:
    direct = KEY_CHARACTER_DUTIES.get(node.id)
    if direct is not None:
        return direct
    parent = str(node.attributes.get("parent_network", ""))
    options = DUTY_STEPS_BY_NETWORK.get(parent)
    if not options:
        return None
    offset = sum(ord(character) for character in node.id)
    return options[(world.tick // 2 + offset) % len(options)]


def _start_member_duty(
    world: World, candidate: RuleCandidate, pressure: JsonDict
) -> ActionTransition:
    label = str(pressure.get("behavior_label", candidate.action))
    # Ordinary life should remain legible for several world ticks while its
    # caption pulses every 0.5 seconds; rapid duty churn only pollutes history.
    duration = max(int(pressure.get("duration_ticks", 2) or 2), 8)
    return ActionTransition(
        status="running",
        summary=f"{world.node(candidate.node_id).name} 开始{label}",
        channel=str(pressure.get("channel", "physical")),
        parameters={"duty_source": "role_specific_daily_duty"},
        progress=0.0,
        locks=_strings(pressure.get("locks")),
        interrupt_priority=0.1,
        deadline_tick=world.tick + duration,
        behavior_label=label,
        salience=0.52,
    )


def _advance_member_duty(world: World, action: ActionInstance) -> ActionTransition:
    deadline = action.deadline_tick or action.started_tick + 1
    duration = max(deadline - action.started_tick, 1)
    if world.tick < deadline:
        return ActionTransition(
            status="running",
            summary=f"{world.node(action.actor_id).name} 正在{action.behavior_label}",
            channel=action.channel,
            parameters=action.parameters,
            progress=min(1.0, (world.tick - action.started_tick) / duration),
            locks=action.locks,
            interrupt_priority=action.interrupt_priority,
            deadline_tick=deadline,
            behavior_label=action.behavior_label,
            salience=action.salience,
        )
    return ActionTransition(
        status="succeeded",
        summary=f"{world.node(action.actor_id).name} 完成{action.behavior_label}",
        channel=action.channel,
        parameters=action.parameters,
        progress=1.0,
        locks=action.locks,
        behavior_label=action.behavior_label,
        salience=action.salience,
        status_reason="duty_rotated",
    )


def _pressure_for(activity: ActivityInstance, step: ActivityStep) -> Any:
    actor_id = activity.participant_roles[step.role]
    return effect(
        "rule_pressure_add", target=f"node:{actor_id}", rule=step.action,
        weight=0.95, ttl=max(step.duration_ticks + 3, 4), source="tribe_activity_actions",
        reason=f"{activity.definition_id} 第 {activity.current_step + 1} 步",
        pressure_id=f"{activity.id}:step:{activity.current_step}",
        activity_id=activity.id, activity_step=activity.current_step,
        channel=step.channel, locks=step.locks,
        root_causality_id=activity.root_causality_id,
        caused_by=[activity.id],
        interrupt_priority=0.82,
    )


def _step_pressure(world: World, activity: ActivityInstance) -> Any | None:
    if activity.current_step >= len(activity.steps):
        return None
    step = activity.steps[activity.current_step]
    actor_id = activity.participant_roles.get(step.role, "")
    pressure_id = f"{activity.id}:step:{activity.current_step}"
    if any(item.actor_id == actor_id and item.parameters.get("activity_id") == activity.id for item in world.active_actions.values()):
        return None
    if any(str(item.get("pressure_id", "")) == pressure_id for item in world.node(actor_id).rule_pressures):
        return None
    return _pressure_for(activity, step)


def _has_activity(world: World, definition_id: str) -> bool:
    return any(item.definition_id == definition_id for item in world.active_activities.values())


def _resource(world: World, node_id: str, name: str) -> float:
    return _number(_dict(world.node(node_id).attributes.get("resources")).get(name, 0))


def _terminal(action: ActionInstance, status: str, summary: str, reason: str) -> ActionTransition:
    return ActionTransition(status=status, summary=summary, channel=action.channel, target_ids=action.target_ids, parameters=action.parameters, progress=action.progress, locks=action.locks, behavior_label=action.behavior_label, salience=action.salience, status_reason=reason)


def _dict(value: object) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _number(value: object) -> float:
    return float(value or 0.0)
