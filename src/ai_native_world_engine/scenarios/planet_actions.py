"""Scenario-owned V2 activity loop for the Enterprise Earth worldline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_native_world_engine.core.action_contracts import (
    ActionInstance,
    ActionTransition,
)
from ai_native_world_engine.core.events import json_copy
from ai_native_world_engine.core.feedback import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    effect,
    target,
)
from ai_native_world_engine.core.rule_contracts import RuleCandidate
from ai_native_world_engine.core.world import World, WorldNode


JsonDict = dict[str, Any]


@dataclass(slots=True)
class PlanetStageRulePackage:
    name: str
    action_id: str
    stage: int
    next_stage: int
    actor_id: str
    behavior_label: str
    channel: str = "physical"
    locks: tuple[str, ...] = ("attention",)
    duration_ticks: int = 1
    target_id: str = ""
    version: str = "2"
    action_runtime_version: int = 2

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        if node.id != self.actor_id or node.attributes.get("alive", True) is False:
            return []
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if str(pressure.get("rule", "")) != self.name:
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action=self.action_id,
                    score=1.6 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", self.behavior_label)),
                    metadata={
                        "channel": self.channel,
                        "locks": list(self.locks),
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates

    def derive_pressures(self, world: World) -> list[ActionFeedback]:
        if world.attributes.get("scenario") != "enterprise_earth":
            return []
        if int(world.attributes.get("planet_activity_stage", 0) or 0) != self.stage:
            return []
        actor = world.node(self.actor_id)
        if any(
            str(item.get("rule", "")) == self.name
            for item in actor.rule_pressures
        ) or any(
            item.actor_id == self.actor_id and item.definition_id == self.action_id
            for item in world.active_actions.values()
        ):
            return []
        cycle = int(world.attributes.get("planet_activity_cycle", 0) or 0)
        pressure_id = f"planet-cycle:{cycle}:{self.name}"
        return [
            ActionFeedback(
                source=self.name,
                actor_type="system",
                actor_id="planet_activity_loop",
                action="derive_planet_pressure",
                summary=f"生成星球场景压力：{self.behavior_label}",
                targets=[target("node", self.actor_id)],
                effects=[
                    effect(
                        "rule_pressure_add",
                        target=f"node:{self.actor_id}",
                        rule=self.name,
                        weight=0.72,
                        ttl=4,
                        source=self.name,
                        reason=f"星球活动循环进入{self.behavior_label}",
                        pressure_id=pressure_id,
                        expected_action=self.action_id,
                        root_causality_id=f"planet-cycle:{cycle}",
                        caused_by=[f"planet-stage:{self.stage}:{cycle}"],
                    )
                ],
                apply_mode=APPLY_AUTHORITATIVE,
            )
        ]

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        actor = world.node(candidate.node_id)
        if actor.attributes.get("alive", True) is False:
            return ActionTransition(
                status="failed",
                summary=f"{actor.name} 当前无法行动",
                channel=self.channel,
                locks=list(self.locks),
                behavior_label=self.behavior_label,
                status_reason="actor_unavailable",
            )
        cycle = int(world.attributes.get("planet_activity_cycle", 0) or 0)
        return ActionTransition(
            status="running",
            summary=f"{actor.name} 开始{self.behavior_label}",
            channel=self.channel,
            target_ids=[self.target_id] if self.target_id else [],
            parameters={"cycle": cycle, "stage": self.stage},
            progress=0.0,
            locks=list(self.locks),
            deadline_tick=world.tick + max(self.duration_ticks, 1),
            behavior_label=self.behavior_label,
            salience=0.66,
        )

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        deadline = action.deadline_tick or action.started_tick + 1
        duration = max(deadline - action.started_tick, 1)
        progress = max(
            action.progress,
            min(1.0, (world.tick - action.started_tick) / duration),
        )
        if world.tick < deadline:
            return ActionTransition(
                status="running",
                summary=f"{world.node(action.actor_id).name} 正在{self.behavior_label}",
                channel=action.channel,
                target_ids=action.target_ids,
                parameters=action.parameters,
                progress=progress,
                locks=action.locks,
                deadline_tick=deadline,
                behavior_label=action.behavior_label,
                salience=action.salience,
            )
        return ActionTransition(
            status="succeeded",
            summary=f"{world.node(action.actor_id).name} 完成{self.behavior_label}",
            channel=action.channel,
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=1.0,
            locks=action.locks,
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason="completed",
            effects=self._completion_effects(world, action),
        )

    def interrupt(
        self, world: World, action: ActionInstance, reason: str
    ) -> ActionTransition:
        return ActionTransition(
            status="interrupted",
            summary=f"{world.node(action.actor_id).name} 中断{self.behavior_label}",
            channel=action.channel,
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=action.progress,
            locks=action.locks,
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason=reason,
        )

    def _completion_effects(
        self, world: World, action: ActionInstance
    ) -> list[Any]:
        actor = world.node(action.actor_id)
        cycle = int(action.parameters.get("cycle", 0) or 0)
        effects: list[Any] = [
            effect(
                "world_state",
                field="planet_activity_stage",
                value=self.next_stage,
            ),
            effect(
                "memory_add",
                target=f"node:{actor.id}",
                text=f"第 {cycle + 1} 轮中完成：{self.behavior_label}",
                source=self.name,
                importance=0.58,
            ),
            effect(
                "action_bullet_add",
                target=f"node:{actor.id}",
                text=f"完成{self.behavior_label}",
                source=self.name,
                salience=0.64,
            ),
        ]
        if self.action_id == "planet_observe":
            effects.append(
                effect(
                    "node_state",
                    target=f"node:{actor.id}",
                    field="latest_observation",
                    value="跨区域气候与公共健康信号出现关联异常",
                )
            )
        elif self.action_id == "planet_organization":
            effects.append(
                effect(
                    "node_state",
                    target=f"node:{actor.id}",
                    field="latest_decision",
                    value="启动跨组织验证任务",
                )
            )
        elif self.action_id == "planet_work":
            effects.append(
                effect(
                    "node_state",
                    target=f"node:{actor.id}",
                    field="work_output",
                    value="cross_domain_evidence_packet",
                )
            )
        elif self.action_id == "planet_relationship":
            effects.append(
                effect(
                    "collaboration_add",
                    target=f"node:{actor.id}",
                    partner=self.target_id,
                    project="跨域证据验证",
                )
            )
        elif self.action_id == "planet_economy":
            effects.append(
                effect(
                    "node_attribute_merge",
                    target=f"node:{actor.id}",
                    field="economy",
                    value={
                        "latest_allocation": "验证任务算力与物流时隙",
                        "cycle": cycle,
                    },
                )
            )
        elif self.action_id == "planet_knowledge":
            effects.extend(
                [
                    effect(
                        "publication_add",
                        target=f"node:{actor.id}",
                        title=f"Cross-domain evidence note {cycle + 1}",
                        topic="climate-health signal validation",
                    ),
                    effect(
                        "world_state",
                        field="planet_activity_cycle",
                        value=cycle + 1,
                    ),
                ]
            )
        return effects


@dataclass(slots=True)
class PlanetCommunicationPackage:
    """Bridges the Planet stage loop into the shared SpeakRulePackage."""

    name: str = "planet_communication"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        return []

    def derive_pressures(self, world: World) -> list[ActionFeedback]:
        if world.attributes.get("scenario") != "enterprise_earth":
            return []
        if int(world.attributes.get("planet_activity_stage", 0) or 0) != 1:
            return []
        cycle = int(world.attributes.get("planet_activity_cycle", 0) or 0)
        root_id = f"planet-cycle:{cycle}"
        speech_event = next(
            (
                item
                for item in reversed(world.speech_events)
                if item.get("root_causality_id") == root_id
                and item.get("speaker_id") == "key-wangari-maathai"
            ),
            None,
        )
        if speech_event is not None:
            return [
                ActionFeedback(
                    source=self.name,
                    actor_type="system",
                    actor_id="planet_activity_loop",
                    action="advance_planet_communication_stage",
                    summary="星球沟通事件已经投递，进入组织决策阶段",
                    targets=[target("world", world.id)],
                    effects=[
                        effect(
                            "world_state",
                            field="planet_activity_stage",
                            value=2,
                        )
                    ],
                    apply_mode=APPLY_AUTHORITATIVE,
                )
            ]
        speaker = world.node("key-wangari-maathai")
        if any(
            str(item.get("rule", "")) == "speak"
            for item in speaker.rule_pressures
        ) or any(
            item.actor_id == speaker.id and item.definition_id == "speak"
            for item in world.active_actions.values()
        ):
            return []
        return [
            ActionFeedback(
                source=self.name,
                actor_type="system",
                actor_id="planet_activity_loop",
                action="derive_planet_communication_pressure",
                summary="将观察结果转为结构化语言意图",
                targets=[target("node", speaker.id)],
                effects=[
                    effect(
                        "rule_pressure_add",
                        target=f"node:{speaker.id}",
                        rule="speak",
                        weight=0.88,
                        ttl=4,
                        source=self.name,
                        reason="需要把跨域异常告知科学委员会",
                        pressure_id=f"planet-cycle:{cycle}:communication",
                        intent="inform",
                        to="key-marie-curie",
                        content="气候与公共健康信号出现关联异常，需要共同验证。",
                        max_range=40,
                        duration_ticks=1,
                        root_causality_id=root_id,
                        caused_by=[f"planet-stage:observation:{cycle}"],
                    )
                ],
                apply_mode=APPLY_AUTHORITATIVE,
            )
        ]


def planet_rule_packages() -> list[object]:
    return [
        PlanetStageRulePackage(
            name="planet_observation",
            action_id="planet_observe",
            stage=0,
            next_stage=1,
            actor_id="org-climate-resilience-forum:field-observation",
            behavior_label="观察跨域异常",
            locks=("attention",),
        ),
        PlanetCommunicationPackage(),
        PlanetStageRulePackage(
            name="planet_organization",
            action_id="planet_organization",
            stage=2,
            next_stage=3,
            actor_id="org-science-council",
            behavior_label="组织验证决策",
            locks=("attention",),
        ),
        PlanetStageRulePackage(
            name="planet_work",
            action_id="planet_work",
            stage=3,
            next_stage=4,
            actor_id="org-science-council:laboratory-network",
            behavior_label="执行证据验证",
            locks=("hands", "attention"),
            duration_ticks=2,
        ),
        PlanetStageRulePackage(
            name="planet_relationship",
            action_id="planet_relationship",
            stage=4,
            next_stage=5,
            actor_id="org-science-council",
            behavior_label="建立跨组织协作",
            channel="social",
            locks=("attention",),
            target_id="org-climate-resilience-forum",
        ),
        PlanetStageRulePackage(
            name="planet_economy",
            action_id="planet_economy",
            stage=5,
            next_stage=6,
            actor_id="org-logistics-grid",
            behavior_label="分配验证资源",
            locks=("attention",),
        ),
        PlanetStageRulePackage(
            name="planet_knowledge",
            action_id="planet_knowledge",
            stage=6,
            next_stage=0,
            actor_id="key-albert-einstein",
            behavior_label="发布验证结果",
            locks=("hands", "attention"),
        ),
    ]
