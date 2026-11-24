"""Deterministic engine-backed Tribe Survival vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any

from ai_native_world_engine.core.action_contracts import (
    ActionInstance,
    ActionTransition,
)
from ai_native_world_engine.core.events import json_copy
from ai_native_world_engine.core.feedback import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    FeedbackIngestor,
    effect,
    target,
)
from ai_native_world_engine.core.rules import RuleCandidate
from ai_native_world_engine.core.world import World, WorldNode


JsonDict = dict[str, Any]

TRIBE_SURVIVAL_VIEWER_SCENE = "tribe_survival_world"
# One completed relationship round always covers 10 active people plus 30
# distinct ripple recipients. Keeping 56 persistent members leaves 16 visible
# background people without changing the round's cognition or rule authority.
RELATIONSHIP_MEMBERS_PER_NETWORK = 56

HOME_ORGANIZATIONS = [
    ("ember-guard", "余烬守卫队", "defense", (49, 47), {"spears": 14, "torches": 8}),
    ("river-scouts", "河谷斥候营", "scouting", (42, 39), {"maps": 3, "warnings": 2}),
    ("stone-builders", "石木工匠营", "shelter", (50, 55), {"wood": 12, "stone": 7}),
    ("dawn-hunters", "晨猎队", "food", (39, 56), {"food": 2, "arrows": 15}),
    ("elder-council", "长老会", "memory", (52, 43), {"trust": 8, "promises": 3}),
    ("ash-shamans", "灰火祭司团", "morale", (58, 48), {"medicine": 3, "rituals": 2}),
    ("granary-keepers", "粮仓看守组", "food", (47, 61), {"food": 18, "seed": 12}),
    ("fire-diplomats", "篝火使者团", "diplomacy", (60, 58), {"gifts": 4, "promises": 2}),
]

EXTERNAL_FACTIONS = [
    ("black-hill-tribe", "黑山部落", "autonomous_enemy", (72, 30), {"warriors": 18, "hunger": 7}),
    ("wolf-tooth-raiders", "狼牙掠夺队", "autonomous_enemy", (78, 62), {"warriors": 24, "hunger": 6}),
    ("salt-road-caravan", "盐路商队", "neutral_external", (25, 68), {"salt": 12, "rumor": 4}),
]

KEY_CHARACTERS = [
    ("chieftain-aya", "首领阿娅", "tribe_leader", (50, 50), "把旨意变成部落内部可执行的生存优先级"),
    ("captain-tor", "守卫队长托尔", "defense_captain", (48, 45), "守住北门并控制反击代价"),
    ("scout-nara", "斥候首领娜拉", "scout_leader", (41, 37), "确认敌方行动并把足迹带回部落"),
    ("shaman-ru", "祭司茹", "memory_keeper", (58, 47), "救治伤员并压住夜袭后的恐慌"),
    ("builder-kun", "工匠大师昆", "master_builder", (51, 57), "在木材不足时先修北门防线"),
    ("young-chief-ren", "少壮派仁", "young_war_leader", (56, 42), "恢复体力后再判断是否有限反击"),
]

MEMBER_ROLES = {
    "ember-guard": ("哨兵", "盾手", "弓手", "火把手"),
    "river-scouts": ("足迹师", "河谷眼线", "信使", "地图师"),
    "stone-builders": ("木匠", "石匠", "塔工", "仓屋工"),
    "dawn-hunters": ("猎人", "剥皮手", "弓箭手", "采集者"),
    "elder-council": ("长老", "记录员", "配给员", "调停者"),
    "ash-shamans": ("祭司", "医者", "梦兆记录员", "草药师"),
    "granary-keepers": ("账房", "仓卫", "种子看守", "配粮员"),
    "fire-diplomats": ("使者", "译者", "贡礼看守", "谈判员"),
}

EXTERNAL_MEMBER_ROLES = ("侦察者", "战士", "谈判者", "补给手")


def create_tribe_survival_world(seed: int = 7) -> World:
    rng = Random(seed)
    world = World(
        "tribe-survival-world",
        {
            "seed": seed,
            "scenario": "tribe_survival",
            "viewer_scene": TRIBE_SURVIVAL_VIEWER_SCENE,
            "scene_title": "蛮荒世界",
            "viewer_title": "蛮荒世界",
            "sovereign_scope": {
                "label": "国王视角只作用于我方部落",
                "commandable": "我方组织、将领、关键角色",
                "not_commandable": "敌对部落、掠夺队、中立商队",
                "rule": "敌方只能通过侦察、外交、威慑、战斗和世界事件间接影响。",
            },
            "survival_loops": [
                "food",
                "shelter",
                "defense",
                "scouting",
                "diplomacy",
                "memory",
                "morale",
            ],
            "governance": {
                "mode": "entertainment_survival_sandbox",
                "home_tribe": "sovereign_commandable",
                "external_factions": "autonomous_not_commandable",
                "people": "synthetic_personas",
            },
        },
    )
    _add_organizations(world, rng)
    _add_key_characters(world)
    _add_special_members(world)
    _add_relationships(world)
    _seed_survival_pressures(world)
    _seed_display_payloads(world)
    return world


@dataclass(slots=True)
class TribeSurvivalRulePackage:
    """Scenario-owned action pack; no Tribe verbs are registered in core rules."""

    name: str = "tribe_survival_actions"
    version: str = "2"
    action_runtime_version: int = 2

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            action = str(pressure.get("rule", ""))
            if action not in {
                "survival_forage",
                "survival_eat",
                "survival_rest",
                "survival_build",
                "survival_rescue",
            }:
                continue
            failure = _survival_precondition_failure(world, node, action, pressure)
            if failure:
                continue
            channel, locks = _survival_channel_and_locks(action)
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action=action,
                    score=2.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", action)),
                    metadata={
                        "pressure": json_copy(pressure),
                        "channel": channel,
                        "locks": locks,
                        "interrupt_priority": float(
                            pressure.get("interrupt_priority", 0.4) or 0.4
                        ),
                    },
                )
            )
        return candidates

    def derive_pressures(self, world: World) -> list[ActionFeedback]:
        """Regenerate bounded survival and dialogue pressure from world facts."""

        if world.attributes.get("scenario") != "tribe_survival":
            return []
        effects: list[Any] = []
        legacy_loops = bool(
            world.attributes.get("enable_legacy_tribe_survival_loops", False)
        )

        def queue(
            node_id: str,
            rule: str,
            *,
            weight: float,
            reason: str,
            **fields: Any,
        ) -> None:
            if _has_pending_or_active_action(world, node_id, rule):
                return
            action_target = fields.pop("target", None)
            if action_target is not None:
                fields["to"] = action_target
            effects.append(
                effect(
                    "rule_pressure_add",
                    target=f"node:{node_id}",
                    rule=rule,
                    weight=weight,
                    ttl=max(int(fields.pop("ttl", 4) or 4), 1),
                    source="tribe_survival_pressure_system",
                    reason=reason,
                    pressure_id=f"tribe-loop:{rule}:{node_id}:{world.tick}",
                    **fields,
                )
            )

        hunters = world.node("dawn-hunters")
        if legacy_loops and _resource_amount(hunters, "food") < 8:
            queue(
                hunters.id,
                "survival_forage",
                weight=0.72,
                reason="猎队库存低于持续采集阈值",
                resource="food",
                amount=3,
                duration_ticks=2,
            )

        chieftain = world.node("chieftain-aya")
        if legacy_loops and (
            float(chieftain.attributes.get("health", 0.0) or 0.0)
            < float(chieftain.attributes.get("max_health", 10.0) or 10.0)
            and _resource_amount(chieftain, "food") >= 1
        ):
            queue(
                chieftain.id,
                "survival_eat",
                weight=0.64,
                reason="首领仍未完全恢复",
                resource="food",
                amount=1,
                heal=2,
                duration_ticks=1,
            )

        young_chief = world.node("young-chief-ren")
        if legacy_loops and float(
            young_chief.attributes.get("fatigue", 0.0) or 0.0
        ) > 0:
            queue(
                young_chief.id,
                "survival_rest",
                weight=0.58,
                reason="疲劳仍在累积判断风险",
                fatigue_recovery=3,
                morale=0.12,
                duration_ticks=2,
            )

        builders = world.node("stone-builders")
        gate = world.node("ember-guard")
        if legacy_loops and (
            float(gate.attributes.get("defense_rating", 0.0) or 0.0) < 9
            and _resource_amount(builders, "wood") >= 5
        ):
            queue(
                builders.id,
                "survival_build",
                weight=0.76,
                reason="北门防御尚未达到安全阈值",
                target="node:ember-guard",
                wood_cost=5,
                defense_gain=2,
                duration_ticks=3,
            )

        shaman = world.node("shaman-ru")
        injured = world.node("injured-scout")
        if legacy_loops and (
            float(injured.attributes.get("health", 0.0) or 0.0)
            < float(injured.attributes.get("max_health", 10.0) or 10.0)
            and _resource_amount(shaman, "medicine") >= 1
        ):
            queue(
                shaman.id,
                "survival_rescue",
                weight=0.8,
                reason="伤员仍需继续治疗",
                target="node:injured-scout",
                medicine_cost=1,
                heal=4,
                duration_ticks=2,
            )

        for enemy_id in (
            ("black-hill-tribe", "wolf-tooth-raiders") if legacy_loops else ()
        ):
            enemy = world.node(enemy_id)
            if _resource_amount(enemy, "hunger") > 4:
                queue(
                    enemy.id,
                    "survival_forage",
                    weight=0.7,
                    reason="敌方饥饿迫使其继续寻找食物",
                    resource="food",
                    amount=2,
                    hunger_reduction=2,
                    duration_ticks=2,
                )

        warning = next(
            (
                item
                for item in reversed(world.speech_events)
                if item.get("speaker_id") == "scout-nara"
                and item.get("intent") == "warn"
            ),
            None,
        )
        if warning is None:
            queue(
                "scout-nara",
                "speak",
                weight=0.94,
                reason="斥候必须把北门敌踪报告给守卫队长",
                intent="warn",
                target="captain-tor",
                facts=["north_gate_enemy_trace"],
                max_range=20,
                duration_ticks=1,
                root_causality_id="tribe-defense:north-gate",
                caused_by=["observation:north-gate-enemy-trace"],
            )
        elif not any(
            item.get("speaker_id") == "captain-tor"
            and item.get("reply_to") == warning.get("id")
            for item in world.speech_events
        ):
            queue(
                "captain-tor",
                "speak",
                weight=0.9,
                reason="守卫队长需要回应斥候警告",
                intent="reply",
                target="scout-nara",
                content="收到警告，我会加强北门警戒。",
                max_range=20,
                duration_ticks=1,
                conversation_id=str(warning.get("conversation_id", "")),
                reply_to=str(warning.get("id", "")),
                root_causality_id=str(warning.get("root_causality_id", "")),
                caused_by=[str(warning.get("id", ""))],
            )

        if not effects:
            return []
        return [
            ActionFeedback(
                source="tribe_survival_pressure_system",
                actor_type="system",
                actor_id="tribe_survival_pressure_system",
                action="derive_survival_pressures",
                summary=f"从部落世界状态生成 {len(effects)} 个行动压力",
                targets=[target("world", world.id)],
                effects=effects,
                apply_mode=APPLY_AUTHORITATIVE,
            )
        ]

    def start(
        self,
        world: World,
        candidate: RuleCandidate,
    ) -> ActionTransition:
        node = world.node(candidate.node_id)
        action = candidate.action
        raw_pressure = candidate.metadata.get("pressure", {})
        pressure = json_copy(raw_pressure) if isinstance(raw_pressure, dict) else {}
        channel, locks = _survival_channel_and_locks(action)
        failure = _survival_precondition_failure(world, node, action, pressure)
        if failure:
            return ActionTransition(
                status="failed",
                summary=f"{node.name} 无法开始{_survival_behavior_label(action)}",
                channel=channel,
                progress=0.0,
                locks=locks,
                behavior_label=_survival_behavior_label(action),
                status_reason=failure,
            )
        duration = max(
            int(
                pressure.get(
                    "duration_ticks",
                    {
                        "survival_eat": 1,
                        "survival_forage": 2,
                        "survival_rest": 2,
                        "survival_build": 3,
                        "survival_rescue": 2,
                    }.get(action, 1),
                )
                or 1
            ),
            1,
        )
        target_id = _node_id(pressure.get("target", pressure.get("to", "")))
        return ActionTransition(
            status="running",
            summary=f"{node.name} 开始{_survival_behavior_label(action)}",
            channel=channel,
            target_ids=[target_id] if target_id else [],
            parameters={"pressure": pressure},
            progress=0.0,
            locks=locks,
            interruptible=True,
            interrupt_priority=float(
                pressure.get("interrupt_priority", 0.4) or 0.4
            ),
            deadline_tick=world.tick + duration,
            behavior_label=_survival_behavior_label(action),
            salience=float(pressure.get("salience", 0.68) or 0.68),
        )

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        node = world.node(action.actor_id)
        raw_pressure = action.parameters.get("pressure", {})
        pressure = json_copy(raw_pressure) if isinstance(raw_pressure, dict) else {}
        deadline = action.deadline_tick or action.started_tick + 1
        duration = max(deadline - action.started_tick, 1)
        progress = max(
            action.progress,
            min(1.0, (world.tick - action.started_tick) / duration),
        )
        if world.tick < deadline:
            return ActionTransition(
                status="running",
                summary=f"{node.name} 正在{_survival_behavior_label(action.definition_id)}",
                channel=action.channel,
                target_ids=action.target_ids,
                parameters=action.parameters,
                progress=progress,
                locks=action.locks,
                interruptible=action.interruptible,
                interrupt_priority=action.interrupt_priority,
                deadline_tick=deadline,
                behavior_label=action.behavior_label,
                salience=action.salience,
            )
        failure = _survival_precondition_failure(
            world, node, action.definition_id, pressure
        )
        if failure:
            return ActionTransition(
                status="failed",
                summary=f"{node.name} 未能完成{action.behavior_label}",
                channel=action.channel,
                target_ids=action.target_ids,
                parameters=action.parameters,
                progress=progress,
                locks=action.locks,
                behavior_label=action.behavior_label,
                salience=action.salience,
                status_reason=failure,
            )
        return self._completion_transition(world, node, action, pressure)

    def interrupt(
        self, world: World, action: ActionInstance, reason: str
    ) -> ActionTransition:
        node = world.node(action.actor_id)
        return ActionTransition(
            status="interrupted",
            summary=f"{node.name} 中断{action.behavior_label}",
            channel=action.channel,
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=action.progress,
            locks=action.locks,
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason=reason,
        )

    def _completion_transition(
        self,
        world: World,
        node: WorldNode,
        instance: ActionInstance,
        pressure: JsonDict,
    ) -> ActionTransition:
        action = instance.definition_id
        summary = f"{node.name} 完成{instance.behavior_label}"
        effects: list[Any] = []
        if action == "survival_forage":
            resource = str(pressure.get("resource", "food"))
            amount = float(pressure.get("amount", 1.0) or 1.0)
            summary = f"{node.name} 从河谷带回 {amount:g} 份{resource}"
            effects = [
                effect("resource_delta", target=f"node:{node.id}", resource=resource, delta=amount),
                effect("memory_add", target=f"node:{node.id}", text="河谷采集路线仍然可用，但留下了敌方观察痕迹。", source=self.name, importance=0.68),
                effect("action_bullet_add", target=f"node:{node.id}", text="带回食物", source=self.name, salience=0.7),
            ]
            hunger_reduction = float(pressure.get("hunger_reduction", 0.0) or 0.0)
            if hunger_reduction > 0:
                effects.append(
                    effect(
                        "resource_delta",
                        target=f"node:{node.id}",
                        resource="hunger",
                        delta=-hunger_reduction,
                        floor=0,
                    )
                )
        elif action == "survival_eat":
            resource = str(pressure.get("resource", "food"))
            amount = float(pressure.get("amount", 1.0) or 1.0)
            summary = f"{node.name} 消耗口粮恢复体力"
            effects = [
                effect("resource_delta", target=f"node:{node.id}", resource=resource, delta=-amount, floor=0),
                effect("health_delta", target=f"node:{node.id}", delta=float(pressure.get("heal", 2.0) or 2.0), ceiling=float(node.attributes.get("max_health", 10) or 10)),
                effect("action_bullet_add", target=f"node:{node.id}", text="进食恢复", source=self.name, salience=0.62),
            ]
        elif action == "survival_rest":
            summary = f"{node.name} 退出夜间争执并完成休整"
            effects = [
                effect("node_attribute_delta", target=f"node:{node.id}", field="fatigue", delta=-float(pressure.get("fatigue_recovery", 3.0) or 3.0), floor=0),
                effect("node_attribute_delta", target=f"node:{node.id}", field="morale", delta=float(pressure.get("morale", 0.15) or 0.15), ceiling=1),
                effect("action_bullet_add", target=f"node:{node.id}", text="完成休整", source=self.name, salience=0.58),
            ]
        elif action == "survival_build":
            target_id = _node_id(pressure.get("target", pressure.get("to", "")))
            wood_cost = float(pressure.get("wood_cost", 1.0) or 1.0)
            target_node = world.node(target_id)
            summary = f"{node.name} 为 {target_node.name} 修补木墙和哨塔"
            effects = [
                effect("resource_delta", target=f"node:{node.id}", resource="wood", delta=-wood_cost, floor=0),
                effect("node_attribute_delta", target=f"node:{target_id}", field="defense_rating", delta=float(pressure.get("defense_gain", 2.0) or 2.0), ceiling=10),
                effect("node_attribute_merge", target=f"node:{target_id}", field="shelter", value={"north_gate_repaired": True, "tick": world.tick}),
                effect("action_bullet_add", target=f"node:{node.id}", text="修补北门", source=self.name, salience=0.74),
            ]
        elif action == "survival_rescue":
            target_id = _node_id(pressure.get("target", pressure.get("to", "")))
            medicine_cost = float(pressure.get("medicine_cost", 1.0) or 1.0)
            target_node = world.node(target_id)
            summary = f"{node.name} 救治 {target_node.name}"
            effects = [
                effect("resource_delta", target=f"node:{node.id}", resource="medicine", delta=-medicine_cost, floor=0),
                effect("health_delta", target=f"node:{target_id}", delta=float(pressure.get("heal", 4.0) or 4.0), ceiling=float(target_node.attributes.get("max_health", 10) or 10)),
                effect("memory_add", target=f"node:{target_id}", text=f"{node.name} 在夜袭后救了我。", source=self.name, importance=0.82),
                effect("action_bullet_add", target=f"node:{node.id}", text="救治伤员", source=self.name, salience=0.78),
            ]
        effects.append(
            effect(
                "node_attribute_merge",
                target=f"node:{node.id}",
                field="_survival_actions",
                value={action: {"tick": world.tick}},
            )
        )
        return ActionTransition(
            status="succeeded",
            summary=summary,
            channel=instance.channel,
            target_ids=instance.target_ids,
            parameters=instance.parameters,
            progress=1.0,
            locks=instance.locks,
            behavior_label=instance.behavior_label,
            salience=instance.salience,
            status_reason="completed",
            effects=effects,
        )


def _add_organizations(world: World, rng: Random) -> None:
    for organization_id, name, loop, position, resources in HOME_ORGANIZATIONS:
        organization = world.add_node(
            organization_id,
            "organization",
            name,
            position,
            {
                "agent_layer": "relationship_network",
                "organization_kind": f"tribe_{loop}",
                "survival_loop": loop,
                "faction": "home_tribe",
                "sovereign_command_scope": "home_tribe_only",
                "synthetic": True,
                "resources": json_copy(resources),
                "defense_rating": 5 if organization_id == "ember-guard" else 3,
                "morale": round(0.62 + rng.random() * 0.16, 3),
            },
        )
        member_ids: list[str] = []
        roles = MEMBER_ROLES[organization_id]
        for index in range(RELATIONSHIP_MEMBERS_PER_NETWORK):
            role = roles[index % len(roles)]
            member_id = f"{organization_id}-member-{index + 1:02d}"
            member_ids.append(member_id)
            member_resources = {next(iter(resources)): 1 + index % 2}
            if index == 0:
                if organization_id == "stone-builders":
                    member_resources["wood"] = 6
                elif organization_id == "ash-shamans":
                    member_resources["medicine"] = 3
            member = world.add_node(
                member_id,
                "organization_member",
                f"{name}{role}{index + 1}",
                _network_member_position(position, index),
                {
                    "agent_layer": "relationship_network_member",
                    "parent_network": organization_id,
                    "role": role,
                    "display_role": role,
                    "faction": "home_tribe",
                    "sovereign_command_scope": "home_tribe_only",
                    "synthetic": True,
                    "simulation_tier": "active_individual",
                    "viewer_behavior_actor": True,
                    "viewer_overview_actor": True,
                    "viewer_background": False,
                    "resources": member_resources,
                },
            )
            world.add_relationship(member.id, organization.id, "member_of", 0.82, {"source": "tribe_survival"})
        organization.attributes["members"] = member_ids
        _add_internal_network_relationships(world, member_ids)

    for faction_id, name, faction, position, resources in EXTERNAL_FACTIONS:
        organization = world.add_node(
            faction_id,
            "organization",
            name,
            position,
            {
                "agent_layer": "relationship_network",
                "organization_kind": "external_faction",
                "faction": faction,
                "sovereign_command_scope": "not_commandable",
                "synthetic": True,
                "resources": json_copy(resources),
                "health": 12,
                "max_health": 12,
                "morale": 0.72,
                "threat_level": 0.8 if faction == "autonomous_enemy" else 0.3,
            },
        )
        member_ids = []
        for index in range(RELATIONSHIP_MEMBERS_PER_NETWORK):
            role = EXTERNAL_MEMBER_ROLES[index % len(EXTERNAL_MEMBER_ROLES)]
            member_id = f"{faction_id}-agent-{index + 1:02d}"
            member_ids.append(member_id)
            member = world.add_node(
                member_id,
                "organization_member",
                f"{name}{role}{index + 1}",
                _network_member_position(position, index),
                {
                    "agent_layer": "relationship_network_member",
                    "parent_network": faction_id,
                    "role": role,
                    "faction": faction,
                    "sovereign_command_scope": "not_commandable",
                    "synthetic": True,
                    "simulation_tier": "active_individual",
                    "viewer_behavior_actor": True,
                    "viewer_overview_actor": True,
                    "viewer_background": False,
                    "resources": {"hunger": 2 + index},
                },
            )
            world.add_relationship(member.id, organization.id, "member_of", 0.78, {"source": "tribe_survival"})
        organization.attributes["members"] = member_ids
        _add_internal_network_relationships(world, member_ids)


def _network_member_position(
    center: tuple[int, int], index: int
) -> tuple[float, float]:
    column = index % 8
    row = index // 8
    return (
        center[0] + (column - 3.5) * 0.7,
        center[1] + (row - 3.0) * 0.7,
    )


def _add_internal_network_relationships(world: World, member_ids: list[str]) -> None:
    for index, source_id in enumerate(member_ids):
        target_id = member_ids[(index + 1) % len(member_ids)]
        world.add_relationship(
            source_id,
            target_id,
            "coordination",
            0.52,
            {"source": "tribe_survival"},
        )
    hub_ids = member_ids[:4]
    for index, member_id in enumerate(member_ids[4:], start=4):
        world.add_relationship(
            hub_ids[index % len(hub_ids)],
            member_id,
            "influence",
            0.34,
            {"source": "tribe_survival"},
        )


def _add_key_characters(world: World) -> None:
    network_by_character = {
        "chieftain-aya": "elder-council",
        "captain-tor": "ember-guard",
        "scout-nara": "river-scouts",
        "shaman-ru": "ash-shamans",
        "builder-kun": "stone-builders",
        "young-chief-ren": "ember-guard",
    }
    for character_id, name, identity, position, goal in KEY_CHARACTERS:
        attributes: JsonDict = {
            "agent_layer": "key_character",
            "identity": identity,
            "parent_network": network_by_character[character_id],
            "faction": "home_tribe",
            "sovereign_command_scope": "home_tribe_only",
            "synthetic": True,
            "simulation_tier": "active_individual",
            "viewer_behavior_actor": True,
            "viewer_overview_actor": True,
            "health": 7,
            "max_health": 10,
            "morale": 0.72,
            "resources": (
                {"food": 2}
                if character_id == "chieftain-aya"
                else {"medicine": 2}
                if character_id == "shaman-ru"
                else {}
            ),
        }
        if character_id == "young-chief-ren":
            attributes["fatigue"] = 5
        node = world.add_node(character_id, "key_character", name, position, attributes)
        node.key_character = {
            "agent_layer": "key_character",
            "identity": identity,
            "status": "active",
            "goal": goal,
            "current_step": goal,
            "thought_seed": f"{name} 正在把世界压力拆成部落内部任务。",
            "salience_score": 0.88,
        }
        node.memories.append(
            {
                "tick": 0,
                "kind": "survival_memory",
                "text": f"{name} 记得上一场夜袭带来的收益和代价。",
                "source": "tribe_survival",
                "importance": 0.78,
            }
        )
        world.add_relationship(node.id, network_by_character[character_id], "command_influence", 0.86, {"source": "tribe_survival"})


def _add_special_members(world: World) -> None:
    world.add_node(
        "injured-scout",
        "person",
        "受伤斥候伊洛",
        (44, 42),
        {
            "synthetic": True,
            "governance_class": "synthetic_persona",
            "faction": "home_tribe",
            "parent_network": "river-scouts",
            "simulation_tier": "active_individual",
            "viewer_behavior_actor": True,
            "viewer_overview_actor": True,
            "health": 3,
            "max_health": 10,
            "morale": 0.42,
            "resources": {},
        },
    )
    world.add_relationship("injured-scout", "river-scouts", "member_of", 0.76, {"source": "tribe_survival"})


def _add_relationships(world: World) -> None:
    world.add_relationship("black-hill-tribe", "river-scouts", "scouting_tension", 0.82, {"status": "autonomous_enemy_pressure"})
    world.add_relationship("wolf-tooth-raiders", "ember-guard", "raid_pressure", 0.88, {"status": "enemy_not_commandable"})
    world.add_relationship("salt-road-caravan", "fire-diplomats", "trade_contact", 0.62, {"status": "neutral_leverage"})
    world.add_relationship("granary-keepers", "dawn-hunters", "food_dependency", 0.76, {"source": "tribe_survival"})
    world.add_relationship("stone-builders", "ember-guard", "defense_dependency", 0.8, {"source": "tribe_survival"})
    world.add_relationship("elder-council", "fire-diplomats", "collaboration", 0.66, {"source": "tribe_survival"})


def _seed_survival_pressures(world: World) -> None:
    # Coarse survival actions remain executable for imported/legacy pressures,
    # but the normal Tribe world is driven by staged person-bound activities.
    world.node("captain-tor").rule_pressures.append(
        {"rule": "combat", "to": "node:wolf-tooth-raiders", "damage": 2, "weight": 0.82, "ttl": 1, "reason": "驱退北门试探"}
    )
    world.set_movement_target("scout-nara", (44, 39), 4.0)


def _seed_display_payloads(world: World) -> None:
    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="tribe_survival",
            actor_type="system",
            actor_id="tribe_survival_seed",
            action="seed_survival_context",
            summary="蛮荒世界进入权威世界",
            targets=[target("world", world.id)],
            effects=[
                effect("action_bullet_add", target="node:ember-guard", text="北门进入夜间警戒", source="tribe_survival", salience=0.7),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )


def _survival_precondition_failure(
    world: World,
    node: WorldNode,
    action: str,
    pressure: JsonDict,
) -> str:
    if node.attributes.get("alive", True) is False:
        return "actor_unavailable"
    if action == "survival_eat":
        resource = str(pressure.get("resource", "food"))
        amount = float(pressure.get("amount", 1.0) or 1.0)
        if _resource_amount(node, resource) < amount:
            return f"insufficient_{resource}"
    if action == "survival_build":
        target_id = _node_id(pressure.get("target", pressure.get("to", "")))
        wood_cost = float(pressure.get("wood_cost", 1.0) or 1.0)
        if not target_id or not world.has_node(target_id):
            return "invalid_build_target"
        if _resource_amount(node, "wood") < wood_cost:
            return "insufficient_wood"
    if action == "survival_rescue":
        target_id = _node_id(pressure.get("target", pressure.get("to", "")))
        medicine_cost = float(pressure.get("medicine_cost", 1.0) or 1.0)
        if not target_id or not world.has_node(target_id):
            return "invalid_rescue_target"
        if _resource_amount(node, "medicine") < medicine_cost:
            return "insufficient_medicine"
        if world.node(target_id).attributes.get("alive", True) is False:
            return "rescue_target_unavailable"
    return ""


def _survival_channel_and_locks(action: str) -> tuple[str, list[str]]:
    locks = {
        "survival_forage": ["locomotion", "hands"],
        "survival_eat": ["hands"],
        "survival_rest": ["body"],
        "survival_build": ["hands", "attention"],
        "survival_rescue": ["hands", "attention"],
    }
    return "physical", list(locks.get(action, ["hands"]))


def _survival_behavior_label(action: str) -> str:
    return {
        "survival_forage": "采集食物",
        "survival_eat": "进食恢复",
        "survival_rest": "短暂休整",
        "survival_build": "修补北门",
        "survival_rescue": "救治伤员",
    }.get(action, "执行生存任务")


def _resource_amount(node: WorldNode, resource: str) -> float:
    resources = node.attributes.get("resources", {})
    if not isinstance(resources, dict):
        return 0.0
    return float(resources.get(resource, 0.0) or 0.0)


def _has_pending_or_active_action(
    world: World, node_id: str, definition_id: str
) -> bool:
    node = world.node(node_id)
    if any(
        str(pressure.get("rule", "")) == definition_id
        for pressure in node.rule_pressures
    ):
        return True
    return any(
        action.actor_id == node_id and action.definition_id == definition_id
        for action in world.active_actions.values()
    )


def _node_id(value: Any) -> str:
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text
