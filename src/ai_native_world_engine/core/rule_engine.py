"""Rule-engine orchestration and authoritative decision feedback."""

from .action_runtime import ActionRuntime, LegacyRulePackageAdapter, is_v2_action_package
from .events import TraceRecord, json_copy
from .feedback import APPLY_AUTHORITATIVE, ActionFeedback, FeedbackIngestor, effect, target
from .rule_contracts import RuleCandidate, RulePackage, RulePressureDeriver
from .rule_causality import attach_pressure_causality
from .rule_lifecycle import _domain_lifecycle_feedback, _feedback
from .rule_packages import (
    CollaborationRulePackage,
    CombatRulePackage,
    EconomicExchangeRulePackage,
    InfectionRulePackage,
    LogisticsRulePackage,
    MigrationRulePackage,
    MovementRulePackage,
    OrganizationDecisionRulePackage,
    ProductionRulePackage,
    QuarantineRulePackage,
    ResourceTransferRulePackage,
    SciencePublishRulePackage,
    SocialSpreadRulePackage,
)
from .rule_registry import expand_rule_names
from .rule_names import canonical_rule_name
from .speech import SpeakRulePackage
from .world import World, WorldNode

class RuleEngineSet:
    def __init__(self, packages: list[RulePackage] | None = None) -> None:
        self.packages = packages or []
        self.ingestor = FeedbackIngestor()
        self.action_runtime = ActionRuntime(self.ingestor)
        self.legacy_adapter = LegacyRulePackageAdapter()
        self.v2_packages = {
            str(package.name): package
            for package in self.packages
            if is_v2_action_package(package)
        }

    @classmethod
    def from_scenario(cls, rule_names: list[str], extra_packages: list[RulePackage] | None = None) -> "RuleEngineSet":
        registry = {
            "combat": CombatRulePackage,
            "collaboration": CollaborationRulePackage,
            "economic_exchange": EconomicExchangeRulePackage,
            "infection": InfectionRulePackage,
            "logistics": LogisticsRulePackage,
            "movement": MovementRulePackage,
            "migration": MigrationRulePackage,
            "organization_decision": OrganizationDecisionRulePackage,
            "quarantine": QuarantineRulePackage,
            "resource_transfer": ResourceTransferRulePackage,
            "science_publish": SciencePublishRulePackage,
            "speak": SpeakRulePackage,
            "social_spread": SocialSpreadRulePackage,
            "production": ProductionRulePackage,
        }
        packages: list[RulePackage] = []
        for name in expand_rule_names(rule_names):
            if name not in registry:
                raise ValueError(f"未知规则包：{name}")
            packages.append(registry[name]())
        packages.extend(extra_packages or [])
        return cls(packages)

    def step(
        self,
        world: World,
        *,
        eligible_pressure_ids: set[str] | None = None,
    ) -> None:
        causal_bootstrap = eligible_pressure_ids is not None
        if not causal_bootstrap:
            self._bind_pressures_to_active_actions(world)
            self.action_runtime.advance(world, self.v2_packages)  # type: ignore[arg-type]
            self._apply_domain_lifecycle(world)
            self._derive_rule_pressures(world)
        for node in list(world.nodes.values()):
            selected_channels: set[str] = set()
            for attempt in range(2):
                decision = self.decide(
                    world,
                    node,
                    v2_only=attempt > 0,
                    excluded_channels=selected_channels,
                    eligible_pressure_ids=eligible_pressure_ids,
                )
                if decision is None:
                    break
                package = self.v2_packages.get(decision.rule)
                if package is not None:
                    recorded = self.action_runtime.start(
                        world,
                        package,  # type: ignore[arg-type]
                        decision,
                        self.v2_packages,  # type: ignore[arg-type]
                    )
                    if recorded is None or recorded.get("errors"):
                        break
                    _consume_correlated_pressure(world, decision)
                    selected_channels.add(
                        str(decision.metadata.get("channel", "physical"))
                    )
                    continue
                feedback = self.feedback_for_decision(world, decision)
                if feedback is not None:
                    feedback = self.legacy_adapter.decorate(world, decision, feedback)
                    attach_pressure_causality(feedback, decision)
                    applied = self.ingestor.ingest(world, feedback)
                    if not applied.get("errors"):
                        _consume_correlated_pressure(world, decision)
                break

    def _bind_pressures_to_active_actions(self, world: World) -> None:
        for action_id in sorted(world.active_actions):
            action = world.active_actions.get(action_id)
            if action is None or not world.has_node(action.actor_id):
                continue
            node = world.node(action.actor_id)
            for pressure in list(node.rule_pressures):
                if not _pressure_matches_active_action(pressure, action):
                    continue
                recorded = self.action_runtime.bind_pressure(world, action, pressure)
                if recorded is None or recorded.get("errors"):
                    continue
                _consume_pressure(world, action.actor_id, pressure)
                action = world.active_actions.get(action_id, action)

    def _apply_domain_lifecycle(self, world: World) -> None:
        for node in list(world.nodes.values()):
            feedbacks = _domain_lifecycle_feedback(world, node)
            for feedback in feedbacks:
                self.ingestor.ingest(world, feedback)

    def _derive_rule_pressures(self, world: World) -> None:
        for package in self.packages:
            if not isinstance(package, RulePressureDeriver):
                continue
            for feedback in package.derive_pressures(world):
                self.ingestor.ingest(world, feedback)

    def decide(
        self,
        world: World,
        node: WorldNode,
        *,
        v2_only: bool = False,
        excluded_channels: set[str] | None = None,
        eligible_pressure_ids: set[str] | None = None,
    ) -> RuleCandidate | None:
        if node.attributes.get("alive", True) is False:
            return None
        candidates: list[RuleCandidate] = []
        for package in self.packages:
            if v2_only and not is_v2_action_package(package):
                continue
            package_candidates = package.candidates(world, node)
            for candidate in package_candidates:
                if eligible_pressure_ids is not None:
                    pressure = candidate.metadata.get("pressure")
                    pressure_data = pressure if isinstance(pressure, dict) else {}
                    if (
                        str(pressure_data.get("pressure_id", "")).strip()
                        not in eligible_pressure_ids
                    ):
                        continue
                candidate.metadata.setdefault(
                    "runtime_version", 2 if is_v2_action_package(package) else 1
                )
                candidate.metadata.setdefault("package_id", str(package.name))
                channel = str(candidate.metadata.get("channel", "physical"))
                if channel in (excluded_channels or set()):
                    continue
                locks_value = candidate.metadata.get("locks", [])
                locks = locks_value if isinstance(locks_value, list) else []
                if not self.action_runtime.can_start(
                    world,
                    candidate.node_id,
                    channel,
                    locks,
                    interrupt_priority=float(
                        candidate.metadata.get("interrupt_priority", 0.0) or 0.0
                    ),
                ):
                    continue
                candidates.append(candidate)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.score, reverse=True)
        selected = candidates[0]
        world.traces.record(
            TraceRecord(
                tick=world.tick,
                kind="rule_decision",
                source="rule_engine_set",
                observed={
                    "node_id": node.id,
                    "position": node.position.to_dict(),
                    "rule_pressures": json_copy(node.rule_pressures),
                    "attributes": json_copy(node.attributes),
                },
                candidates=[candidate.to_dict() for candidate in candidates],
                selected=selected.to_dict(),
            )
        )
        return selected

    def feedback_for_decision(self, world: World, decision: RuleCandidate) -> ActionFeedback | None:
        if decision.feedback is not None:
            return decision.feedback
        if decision.action == "move":
            node = world.node(decision.node_id)
            if node.movement_target is None:
                return None
            old_position = node.position
            effective_speed = float(decision.metadata.get("effective_speed", node.movement_speed) or node.movement_speed)
            new_position, arrived = old_position.step_toward(node.movement_target, effective_speed)
            effects = [
                effect(
                    "node_position",
                    target=f"node:{node.id}",
                    position=new_position.to_dict(),
                    arrived=arrived,
                ),
                effect(
                    "action_bullet_add",
                    target=f"node:{node.id}",
                    text="移动",
                    source="movement_rule",
                    salience=0.4,
                ),
            ]
            if arrived:
                effects.append(effect("node_state", target=f"node:{node.id}", field="movement_arrived", value=True))
            feedback = ActionFeedback(
                source="rule_engine_set",
                actor_type="node",
                actor_id=node.id,
                action="move",
                summary=f"{node.name} 向目标移动",
                targets=[target("node", node.id)],
                effects=effects,
                apply_mode=APPLY_AUTHORITATIVE,
                metadata={
                    "decision_trace": decision.to_dict(),
                    "delta": {
                        "from": old_position.to_dict(),
                        "to": new_position.to_dict(),
                        "arrived": arrived,
                        "effective_speed": effective_speed,
                    },
                },
            )
            world.traces.record(
                TraceRecord(
                    tick=world.tick,
                    kind="movement",
                    source="movement_rule",
                    observed={"node_id": node.id, "target": new_position.to_dict()},
                    selected=decision.to_dict(),
                    delta={
                        "from": old_position.to_dict(),
                        "to": new_position.to_dict(),
                        "arrived": arrived,
                        "effective_speed": effective_speed,
                    },
                )
            )
            return feedback
        if decision.action == "resource_transfer":
            node = world.node(decision.node_id)
            receiver_id = str(decision.metadata.get("to", ""))
            resource = str(decision.metadata.get("resource", ""))
            amount = float(decision.metadata.get("amount", 0.0) or 0.0)
            if not receiver_id or not resource or amount <= 0:
                return None
            receiver = world.node(receiver_id)
            feedback = ActionFeedback(
                source="rule_engine_set",
                actor_type="node",
                actor_id=node.id,
                action="resource_transfer",
                summary=f"{node.name} 向 {receiver.name} 转移 {resource}",
                targets=[target("node", receiver.id)],
                effects=[
                    effect(
                        "resource_transfer",
                        **{
                            "from": f"node:{node.id}",
                            "to": f"node:{receiver.id}",
                            "resource": resource,
                            "amount": amount,
                        },
                    ),
                    effect(
                        "action_bullet_add",
                        target=f"node:{node.id}",
                        text=f"转移 {resource}",
                        source="resource_transfer_rule",
                        salience=0.45,
                    ),
                ],
                apply_mode=APPLY_AUTHORITATIVE,
                metadata={"decision_trace": decision.to_dict()},
            )
            world.traces.record(
                TraceRecord(
                    tick=world.tick,
                    kind="resource_transfer",
                    source="resource_transfer_rule",
                    observed={
                        "node_id": node.id,
                        "receiver_id": receiver.id,
                        "resource": resource,
                        "amount": amount,
                    },
                    selected=decision.to_dict(),
                    delta={
                        "from": node.id,
                        "to": receiver.id,
                        "resource": resource,
                        "amount": amount,
                    },
                )
            )
            return feedback
        if decision.action == "logistics_transfer":
            node = world.node(decision.node_id)
            receiver_id = str(decision.metadata.get("to", ""))
            receiver = world.node(receiver_id)
            resource = str(decision.metadata.get("resource", "supplies"))
            amount = float(decision.metadata.get("amount", 0.0) or 0.0)
            pressure = decision.metadata.get("pressure", {})
            pressure_data = pressure if isinstance(pressure, dict) else {}
            effects = [
                effect("resource_transfer", **{"from": f"node:{node.id}", "to": f"node:{receiver.id}", "resource": resource, "amount": amount}),
                effect("action_bullet_add", target=f"node:{node.id}", text=f"调拨 {resource}", source="logistics_rule", salience=0.48),
                effect("memory_add", target=f"node:{receiver.id}", text=f"received {amount:g} {resource} from {node.name}", source="logistics_rule", importance=0.45),
            ]
            if resource in {"medical_supplies", "medicine", "medkit"}:
                effects.append(
                    effect(
                        "health_delta",
                        target=f"node:{receiver.id}",
                        delta=float(pressure_data.get("heal_amount", amount) or amount),
                        ceiling=float(pressure_data.get("max_health", receiver.attributes.get("max_health", 10)) or 10),
                    )
                )
            return _feedback(
                decision,
                node,
                "logistics_transfer",
                f"{node.name} 向 {receiver.name} 调拨 {resource}",
                effects,
                target_id=receiver.id,
            )
        if decision.action == "combat_attack":
            node = world.node(decision.node_id)
            target_id = str(decision.metadata.get("target_id", ""))
            target_node = world.node(target_id)
            damage = float(decision.metadata.get("damage", 1.0) or 1.0)
            resource = str(decision.metadata.get("resource", ""))
            resource_cost = float(decision.metadata.get("resource_cost", 0.0) or 0.0)
            effects = [
                effect("health_delta", target=f"node:{target_node.id}", delta=-damage, floor=0),
                effect("action_bullet_add", target=f"node:{node.id}", text="攻击", source="combat_rule", salience=0.62),
                effect("memory_add", target=f"node:{target_node.id}", text=f"took {damage:g} scenario combat damage from {node.name}", source="combat_rule", importance=0.65),
            ]
            if resource and resource_cost > 0:
                effects.append(
                    effect("resource_delta", target=f"node:{node.id}", resource=resource, delta=-resource_cost, floor=0)
                )
            return _feedback(
                decision,
                node,
                "combat_attack",
                f"{node.name} 攻击 {target_node.name}",
                effects,
                target_id=target_node.id,
            )
        if decision.action == "infection_spread":
            node = world.node(decision.node_id)
            target_id = str(decision.metadata.get("target_id", ""))
            target_node = world.node(target_id)
            pathogen = str(decision.metadata.get("pathogen", "scenario_pathogen"))
            pressure = decision.metadata.get("pressure", {})
            pressure_data = pressure if isinstance(pressure, dict) else {}
            return _feedback(
                decision,
                node,
                "infection_spread",
                f"{node.name} 触发 {target_node.name} 的感染风险",
                [
                    effect(
                        "infection_state",
                        target=f"node:{target_node.id}",
                        pathogen=pathogen,
                        status="exposed",
                        severity=decision.metadata.get("severity", 1.0),
                        age=0,
                        incubation_ticks=int(pressure_data.get("incubation_ticks", 1) or 1),
                        infectious_ticks=int(pressure_data.get("infectious_ticks", 2) or 2),
                        damage_per_tick=float(pressure_data.get("damage_per_tick", 0.0) or 0.0),
                    ),
                    effect("action_bullet_add", target=f"node:{target_node.id}", text="感染暴露", source="infection_rule", salience=0.55),
                ],
                target_id=target_node.id,
            )
        if decision.action == "quarantine_policy":
            node = world.node(decision.node_id)
            policy = str(decision.metadata.get("policy", "quarantine"))
            return _feedback(
                decision,
                node,
                "quarantine_policy",
                f"{node.name} 启用隔离政策",
                [
                    effect(
                        "policy_state",
                        target=f"node:{node.id}",
                        policy=policy,
                        status=decision.metadata.get("level", "active"),
                        remaining_ticks=decision.metadata.get("duration_ticks", decision.metadata.get("remaining_ticks", 0)),
                    ),
                    effect("action_bullet_add", target=f"node:{node.id}", text="隔离", source="quarantine_rule", salience=0.5),
                ],
            )
        if decision.action == "organization_decision":
            node = world.node(decision.node_id)
            decision_text = str(decision.metadata.get("decision", "coordinate"))
            return _feedback(
                decision,
                node,
                "organization_decision",
                f"{node.name} 采纳组织决策",
                [
                    effect("policy_state", target=f"node:{node.id}", policy="organization_decision", status=decision_text),
                    effect("memory_add", target=f"node:{node.id}", text=f"organization decision adopted: {decision_text}", source="organization_decision_rule", importance=0.6),
                    effect("action_bullet_add", target=f"node:{node.id}", text="组织决策", source="organization_decision_rule", salience=0.5),
                ],
            )
        if decision.action == "social_spread":
            node = world.node(decision.node_id)
            target_id = str(decision.metadata.get("target_id", node.id))
            signal = str(decision.metadata.get("signal", "scenario_signal"))
            return _feedback(
                decision,
                node,
                "social_spread",
                f"{node.name} 传播 {signal}",
                [
                    effect("node_attribute_delta", target=f"node:{target_id}", field=f"signal:{signal}", delta=1),
                    effect("relationship_delta", source=f"node:{node.id}", target=f"node:{target_id}", relation="influence", delta=0.05, reason=f"social spread: {signal}"),
                    effect("action_bullet_add", target=f"node:{target_id}", text="影响传播", source="social_spread_rule", salience=0.46),
                ],
                target_id=target_id,
            )
        if decision.action == "science_publish":
            node = world.node(decision.node_id)
            title = str(decision.metadata.get("title", "Scenario note"))
            topic = str(decision.metadata.get("topic", "scenario research"))
            return _feedback(
                decision,
                node,
                "science_publish",
                f"{node.name} 发表 {title}",
                [
                    effect("publication_add", target=f"node:{node.id}", title=title, topic=topic),
                    effect("action_bullet_add", target=f"node:{node.id}", text="发表", source="science_publish_rule", salience=0.58),
                ],
            )
        if decision.action == "migration":
            node = world.node(decision.node_id)
            destination = str(decision.metadata.get("destination", "scenario_destination"))
            pressure = decision.metadata.get("pressure", {})
            pressure_data = pressure if isinstance(pressure, dict) else {}
            effects = [
                effect(
                    "migration_state",
                    target=f"node:{node.id}",
                    destination=destination,
                    status="migrating",
                    destination_position=pressure_data.get("destination_position", pressure_data.get("position")),
                    speed=float(pressure_data.get("speed", 0.0) or 0.0),
                    base_speed=float(pressure_data.get("speed", 0.0) or 0.0),
                    progress=0.0,
                ),
                effect("action_bullet_add", target=f"node:{node.id}", text="迁徙", source="migration_rule", salience=0.5),
            ]
            if isinstance(pressure, dict) and "position" in pressure and not pressure.get("speed"):
                effects.append(effect("node_position", target=f"node:{node.id}", position=pressure["position"], arrived=True))
            return _feedback(decision, node, "migration", f"{node.name} 迁徙至 {destination}", effects)
        if decision.action == "collaboration":
            node = world.node(decision.node_id)
            partner_id = str(decision.metadata.get("partner_id", ""))
            project = str(decision.metadata.get("project", "scenario collaboration"))
            effects = [
                effect("collaboration_add", target=f"node:{node.id}", partner=f"node:{partner_id}" if partner_id else "", project=project),
                effect("action_bullet_add", target=f"node:{node.id}", text="协作", source="collaboration_rule", salience=0.52),
            ]
            if partner_id:
                effects.append(effect("relationship_delta", source=f"node:{node.id}", target=f"node:{partner_id}", relation="collaboration", delta=0.12, reason=project))
            return _feedback(decision, node, "collaboration", f"{node.name} 推进协作：{project}", effects, target_id=partner_id or node.id)
        if decision.action == "production":
            node = world.node(decision.node_id)
            output_resource = str(decision.metadata.get("output_resource", ""))
            amount = float(decision.metadata.get("amount", 0.0) or 0.0)
            input_costs = decision.metadata.get("input_costs", {})
            costs = input_costs if isinstance(input_costs, dict) else {}
            effects = [
                *[
                    effect("resource_delta", target=f"node:{node.id}", resource=str(resource), delta=-float(cost), floor=0)
                    for resource, cost in sorted(costs.items())
                ],
                effect("resource_delta", target=f"node:{node.id}", resource=output_resource, delta=amount, floor=0),
                effect(
                    "node_attribute_merge",
                    target=f"node:{node.id}",
                    field="production",
                    value={
                        "last_output_resource": output_resource,
                        "last_output_amount": amount,
                        "last_project": decision.metadata.get("project", output_resource),
                        "last_tick": world.tick,
                    },
                ),
                effect("action_bullet_add", target=f"node:{node.id}", text="生产", source="production_rule", salience=0.5),
            ]
            return _feedback(
                decision,
                node,
                "production",
                f"{node.name} 生产 {amount:g} {output_resource}",
                effects,
            )
        if decision.action == "economic_exchange":
            buyer = world.node(decision.node_id)
            seller_id = str(decision.metadata.get("seller_id", ""))
            seller = world.node(seller_id)
            resource = str(decision.metadata.get("resource", ""))
            amount = float(decision.metadata.get("amount", 0.0) or 0.0)
            total_price = float(decision.metadata.get("total_price", 0.0) or 0.0)
            budget_field = str(decision.metadata.get("budget_field", "budget"))
            effects = [
                effect(
                    "resource_transfer",
                    **{
                        "from": f"node:{seller.id}",
                        "to": f"node:{buyer.id}",
                        "resource": resource,
                        "amount": amount,
                    },
                ),
                effect("node_attribute_delta", target=f"node:{buyer.id}", field=budget_field, delta=-total_price, floor=0),
                effect("node_attribute_delta", target=f"node:{seller.id}", field=budget_field, delta=total_price, floor=0),
                effect("action_bullet_add", target=f"node:{buyer.id}", text="交易", source="economic_exchange_rule", salience=0.5),
                effect(
                    "memory_add",
                    target=f"node:{buyer.id}",
                    text=f"bought {amount:g} {resource} from {seller.name} for {total_price:g}",
                    source="economic_exchange_rule",
                    importance=0.45,
                ),
            ]
            return _feedback(
                decision,
                buyer,
                "economic_exchange",
                f"{buyer.name} 从 {seller.name} 购买 {resource}",
                effects,
                target_id=seller.id,
            )
        return None


def _consume_correlated_pressure(world: World, decision: RuleCandidate) -> None:
    """Consume an option pressure after its first successful authoritative action."""

    pressure = decision.metadata.get("pressure")
    if not isinstance(pressure, dict):
        return
    _consume_pressure(world, decision.node_id, pressure)


def _consume_pressure(
    world: World, node_id: str, pressure: dict[str, object]
) -> None:
    pressure_id = str(pressure.get("pressure_id", "")).strip()
    if not pressure_id or not world.has_node(node_id):
        return
    node = world.node(node_id)
    remaining = [
        item
        for item in node.rule_pressures
        if str(item.get("pressure_id", "")).strip() != pressure_id
    ]
    if len(remaining) == len(node.rule_pressures):
        return
    node.rule_pressures = remaining
    world.events.record_delta(
        world.tick,
        "rule_engine_set",
        {
            "kind": "correlated_pressure_consumed",
            "node_id": node.id,
            "pressure_id": pressure_id,
            "provider_job_id": str(pressure.get("provider_job_id", "")),
            "option_id": str(pressure.get("option_id", "")),
        },
    )


def _pressure_matches_active_action(
    pressure: dict[str, object], action: object
) -> bool:
    pressure_id = str(pressure.get("pressure_id", "")).strip()
    if not pressure_id:
        return False
    definition_id = str(getattr(action, "definition_id", ""))
    package_id = str(getattr(action, "package_id", ""))
    expected = str(
        pressure.get("expected_action", pressure.get("action", ""))
    ).strip()
    if expected:
        return canonical_rule_name(expected) in {
            canonical_rule_name(definition_id),
            canonical_rule_name(package_id),
        }
    rule = canonical_rule_name(str(pressure.get("rule", "")))
    if rule in {
        canonical_rule_name(definition_id),
        canonical_rule_name(package_id),
    }:
        return True
    return (rule, definition_id) in {
        ("movement", "move"),
        ("speak", "speak"),
        ("speech", "speak"),
        ("social_speech", "speak"),
    }
