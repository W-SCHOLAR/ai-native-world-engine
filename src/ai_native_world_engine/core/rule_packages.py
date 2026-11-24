"""Built-in candidate-producing rule packages."""

from .action_contracts import ActionInstance, ActionTransition
from .events import json_copy
from .feedback import effect
from .rule_contracts import RuleCandidate
from .rule_lifecycle import _contact_factor, _movement_factor
from .rule_support import (
    _health_factor,
    _is_alive,
    _logistics_capacity,
    _morale_factor,
    _node_id,
    _optional_float,
    _pressure_bonus,
    _production_capacity,
    _relationship_strength,
    _resource_amount,
    _resource_costs,
    _route_between,
    _rule_matches,
    _single_node_pressure_candidates,
)
from .world import Position, World, WorldNode

class MovementRulePackage:
    name = "movement"
    version = "2"
    action_runtime_version = 2

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        if node.movement_target is None or node.movement_speed <= 0:
            return []
        movement_factor = _movement_factor(node)
        if movement_factor <= 0:
            return []
        pressure_bonus = _pressure_bonus(node, "movement")
        movement_pressures = [
            pressure
            for pressure in node.rule_pressures
            if _rule_matches(pressure, {"movement"})
        ]
        strongest_pressure = max(
            movement_pressures,
            key=lambda pressure: float(pressure.get("weight", 0.0) or 0.0),
            default=None,
        )
        metadata = {
            "effective_speed": node.movement_speed * movement_factor,
            "target_position": node.movement_target.to_dict(),
            "channel": "physical",
            "locks": ["locomotion"],
            "behavior_label": "移动",
        }
        if strongest_pressure is not None:
            metadata["pressure"] = json_copy(strongest_pressure)
        return [
            RuleCandidate(
                node_id=node.id,
                action="move",
                score=(1.0 + pressure_bonus) * movement_factor,
                rule=self.name,
                reason="节点存在移动目标",
                metadata=metadata,
            )
        ]

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        node = world.node(candidate.node_id)
        target_value = candidate.metadata.get("target_position")
        if not isinstance(target_value, dict):
            return ActionTransition(
                status="failed",
                summary=f"{node.name} 没有有效移动目标",
                behavior_label="移动",
                locks=["locomotion"],
                status_reason="missing_target",
            )
        target_position = Position.from_value(target_value)
        speed = float(candidate.metadata.get("effective_speed", 0.0) or 0.0)
        total_distance = node.position.distance_to(target_position)
        return self._move_transition(
            node,
            target_position,
            speed,
            origin=node.position,
            total_distance=total_distance,
        )

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        node = world.node(action.actor_id)
        if node.attributes.get("alive", True) is False:
            return ActionTransition(
                status="failed",
                summary=f"{node.name} 无法继续移动",
                channel="physical",
                target_ids=action.target_ids,
                parameters=action.parameters,
                progress=action.progress,
                locks=["locomotion"],
                behavior_label="移动",
                status_reason="actor_unavailable",
            )
        target_value = action.parameters.get("target_position")
        if not isinstance(target_value, dict):
            return ActionTransition(
                status="failed",
                summary=f"{node.name} 的移动目标失效",
                channel="physical",
                progress=action.progress,
                locks=["locomotion"],
                behavior_label="移动",
                status_reason="missing_target_after_restore",
            )
        origin_value = action.parameters.get("origin", node.position.to_dict())
        origin = Position.from_value(origin_value) if isinstance(origin_value, dict) else node.position
        return self._move_transition(
            node,
            Position.from_value(target_value),
            float(action.parameters.get("speed", 0.0) or 0.0),
            origin=origin,
            total_distance=float(action.parameters.get("total_distance", 0.0) or 0.0),
        )

    def interrupt(
        self, world: World, action: ActionInstance, reason: str
    ) -> ActionTransition:
        node = world.node(action.actor_id)
        return ActionTransition(
            status="interrupted",
            summary=f"{node.name} 中断移动：{reason}",
            channel="physical",
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=action.progress,
            locks=["locomotion"],
            behavior_label="移动",
            status_reason=reason,
        )

    def _move_transition(
        self,
        node: WorldNode,
        target_position: Position,
        speed: float,
        *,
        origin: Position,
        total_distance: float,
    ) -> ActionTransition:
        parameters = {
            "target_position": target_position.to_dict(),
            "origin": origin.to_dict(),
            "speed": speed,
            "total_distance": total_distance,
        }
        if speed <= 0:
            return ActionTransition(
                status="failed",
                summary=f"{node.name} 无法移动",
                channel="physical",
                parameters=parameters,
                locks=["locomotion"],
                behavior_label="移动",
                status_reason="non_positive_speed",
            )
        next_position, arrived = node.position.step_toward(target_position, speed)
        remaining = next_position.distance_to(target_position)
        progress = (
            1.0
            if arrived or total_distance <= 0
            else max(0.0, min(1.0, 1.0 - remaining / total_distance))
        )
        effects = [
            effect(
                "node_position",
                target=f"node:{node.id}",
                position=next_position.to_dict(),
                arrived=arrived,
            )
        ]
        if arrived:
            effects.append(
                effect(
                    "node_state",
                    target=f"node:{node.id}",
                    field="movement_arrived",
                    value=True,
                )
            )
            effects.append(
                effect(
                    "action_bullet_add",
                    target=f"node:{node.id}",
                    text="抵达",
                    source="movement_action_v2",
                    salience=0.52,
                )
            )
        elif node.position == origin:
            effects.append(
                effect(
                    "action_bullet_add",
                    target=f"node:{node.id}",
                    text="移动",
                    source="movement_action_v2",
                    salience=0.4,
                )
            )
        return ActionTransition(
            status="succeeded" if arrived else "running",
            summary=(
                f"{node.name} 抵达移动目标"
                if arrived
                else f"{node.name} 正在向目标移动"
            ),
            channel="physical",
            target_ids=[node.id],
            parameters=parameters,
            progress=progress,
            locks=["locomotion"],
            behavior_label="移动",
            salience=0.4,
            status_reason="arrived" if arrived else "",
            effects=effects,
        )


class ResourceTransferRulePackage:
    name = "resource_transfer"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            pressure_rule = str(pressure.get("rule", ""))
            if pressure_rule not in {"resource_transfer", "transfer", "资源转移"}:
                continue
            resource = str(pressure.get("resource", ""))
            amount = float(pressure.get("amount", 0.0) or 0.0)
            receiver_id = _node_id(pressure.get("to", pressure.get("target_node", "")))
            if not resource or amount <= 0 or not receiver_id or not world.has_node(receiver_id):
                continue
            available = _resource_amount(node, resource)
            if available < amount:
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="resource_transfer",
                    score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", "资源转移压力")),
                    metadata={
                        "to": receiver_id,
                        "resource": resource,
                        "amount": amount,
                        "available": available,
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class ProductionRulePackage:
    name = "production"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"production", "produce", "manufacture", "产能", "生产"}):
                continue
            output_resource = str(pressure.get("output_resource", pressure.get("resource", "")))
            amount = float(pressure.get("amount", pressure.get("output_amount", 0.0)) or 0.0)
            if not output_resource or amount <= 0:
                continue
            capacity = _production_capacity(node, pressure)
            if capacity is not None and amount > capacity:
                continue
            input_costs = _resource_costs(pressure.get("input_costs", pressure.get("inputs", {})))
            if any(_resource_amount(node, resource) < cost for resource, cost in input_costs.items()):
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="production",
                    score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", "production pressure")),
                    metadata={
                        "output_resource": output_resource,
                        "amount": amount,
                        "capacity": capacity,
                        "input_costs": input_costs,
                        "project": str(pressure.get("project", pressure.get("product", output_resource))),
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class EconomicExchangeRulePackage:
    name = "economic_exchange"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"economic_exchange", "market_exchange", "trade", "交易", "经济交换"}):
                continue
            seller_id = _node_id(pressure.get("from", pressure.get("seller", pressure.get("to", ""))))
            resource = str(pressure.get("resource", ""))
            amount = float(pressure.get("amount", 0.0) or 0.0)
            unit_price = float(pressure.get("unit_price", pressure.get("price", 0.0)) or 0.0)
            total_price = float(pressure.get("total_price", unit_price * amount) or 0.0)
            if not seller_id or not world.has_node(seller_id) or seller_id == node.id:
                continue
            if not resource or amount <= 0 or total_price < 0:
                continue
            seller = world.node(seller_id)
            if _resource_amount(seller, resource) < amount:
                continue
            budget_field = str(pressure.get("budget_field", "budget"))
            buyer_budget = float(node.attributes.get(budget_field, 0.0) or 0.0)
            if buyer_budget < total_price:
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="economic_exchange",
                    score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", "economic exchange pressure")),
                    metadata={
                        "seller_id": seller_id,
                        "resource": resource,
                        "amount": amount,
                        "unit_price": unit_price,
                        "total_price": total_price,
                        "budget_field": budget_field,
                        "currency": str(pressure.get("currency", node.attributes.get("currency", "credits"))),
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class CombatRulePackage:
    name = "combat"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"combat", "attack", "battle", "战斗", "攻击"}):
                continue
            target_id = _node_id(pressure.get("to", pressure.get("target_node", pressure.get("target", ""))))
            if not target_id or not world.has_node(target_id) or target_id == node.id:
                continue
            target_node = world.node(target_id)
            if not _is_alive(node) or not _is_alive(target_node):
                continue
            distance = node.position.distance_to(target_node.position)
            max_range = _optional_float(pressure.get("max_range", pressure.get("range")))
            if max_range is not None and distance > max_range:
                continue
            resource = str(pressure.get("resource", pressure.get("required_resource", "")))
            resource_cost = max(float(pressure.get("resource_cost", pressure.get("ammo_cost", 0.0)) or 0.0), 0.0)
            if resource and resource_cost > 0 and _resource_amount(node, resource) < resource_cost:
                continue
            health_factor = _health_factor(node)
            morale_factor = _morale_factor(node)
            if health_factor <= 0 or morale_factor <= 0:
                continue
            base_damage = max(float(pressure.get("damage", 1.0) or 1.0), 0.0)
            damage = round(base_damage * health_factor * morale_factor, 4)
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="combat_attack",
                    score=(1.0 + float(pressure.get("weight", 0.0) or 0.0)) * health_factor * morale_factor,
                    rule=self.name,
                    reason=str(pressure.get("reason", "combat pressure")),
                    metadata={
                        "target_id": target_id,
                        "damage": damage,
                        "base_damage": base_damage,
                        "distance": distance,
                        "max_range": max_range,
                        "health_factor": health_factor,
                        "morale_factor": morale_factor,
                        "resource": resource,
                        "resource_cost": resource_cost,
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class InfectionRulePackage:
    name = "infection"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"infection", "contact_infection", "disease_spread", "感染"}):
                continue
            target_id = _node_id(pressure.get("to", pressure.get("target_node", pressure.get("target", node.id))))
            if not target_id or not world.has_node(target_id):
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="infection_spread",
                    score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", "infection pressure")),
                    metadata={
                        "target_id": target_id,
                        "pathogen": str(pressure.get("pathogen", "scenario_pathogen")),
                        "severity": float(pressure.get("severity", 1.0) or 1.0),
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class QuarantineRulePackage:
    name = "quarantine"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        return _single_node_pressure_candidates(
            node,
            self.name,
            {"quarantine", "quarantine_policy", "isolation", "隔离"},
            "quarantine_policy",
            {"policy": "quarantine", "level": "active"},
        )


class LogisticsRulePackage:
    name = "logistics"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"logistics", "transport", "supply", "物流", "补给"}):
                continue
            receiver_id = _node_id(pressure.get("to", pressure.get("target_node", "")))
            resource = str(pressure.get("resource", "supplies"))
            amount = float(pressure.get("amount", 1.0) or 1.0)
            if not receiver_id or not world.has_node(receiver_id) or amount <= 0:
                continue
            available = _resource_amount(node, resource)
            if available < amount:
                continue
            capacity = _logistics_capacity(node, pressure)
            if capacity is not None and amount > capacity:
                continue
            route = _route_between(world, node.id, receiver_id)
            if bool(pressure.get("require_route", pressure.get("route_required", False))) and route is None:
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="logistics_transfer",
                    score=1.0
                    + float(pressure.get("weight", 0.0) or 0.0)
                    + (max(float(route.get("weight", 0.0) or 0.0), 0.0) * 0.1 if route else 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", "logistics pressure")),
                    metadata={
                        "to": receiver_id,
                        "resource": resource,
                        "amount": amount,
                        "available": available,
                        "capacity": capacity,
                        "route": route,
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class OrganizationDecisionRulePackage:
    name = "organization_decision"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        return _single_node_pressure_candidates(
            node,
            self.name,
            {"organization_decision", "decision", "policy_decision", "组织决策"},
            "organization_decision",
            {"decision": "coordinate", "status": "adopted"},
        )


class SocialSpreadRulePackage:
    name = "social_spread"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"social_spread", "influence", "belief_spread", "传播", "舆论"}):
                continue
            target_id = _node_id(pressure.get("to", pressure.get("target_node", node.id)))
            if not target_id or not world.has_node(target_id):
                continue
            signal = str(pressure.get("signal", pressure.get("belief", "scenario_signal")))
            relationship_weight = _relationship_strength(
                world,
                node.id,
                target_id,
                {"trust", "influence", "follow", "follows", "collaboration", "member_of"},
            )
            min_relationship_weight = _optional_float(pressure.get("min_relationship_weight"))
            if bool(pressure.get("require_relationship", False)) and relationship_weight <= 0:
                continue
            if min_relationship_weight is not None and relationship_weight < min_relationship_weight:
                continue
            contact_factor = _contact_factor(node) * _contact_factor(world.node(target_id))
            if contact_factor <= 0:
                continue
            relationship_bonus = max(relationship_weight, 0.0)
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="social_spread",
                    score=(1.0 + float(pressure.get("weight", 0.0) or 0.0) + relationship_bonus) * contact_factor,
                    rule=self.name,
                    reason=str(pressure.get("reason", "social spread pressure")),
                    metadata={
                        "target_id": target_id,
                        "signal": signal,
                        "relationship_weight": relationship_weight,
                        "contact_factor": contact_factor,
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates


class SciencePublishRulePackage:
    name = "science_publish"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        return _single_node_pressure_candidates(
            node,
            self.name,
            {"science_publish", "publish", "publication", "发表"},
            "science_publish",
            {"topic": "scenario research", "title": "Scenario note"},
        )


class MigrationRulePackage:
    name = "migration"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        return _single_node_pressure_candidates(
            node,
            self.name,
            {"migration", "migrate", "relocate", "迁徙", "迁移"},
            "migration",
            {"destination": "scenario_destination"},
        )


class CollaborationRulePackage:
    name = "collaboration"

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if not _rule_matches(pressure, {"collaboration", "collaborate", "cooperate", "协作", "合作"}):
                continue
            partner_id = _node_id(pressure.get("with", pressure.get("to", pressure.get("target_node", ""))))
            if partner_id and not world.has_node(partner_id):
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="collaboration",
                    score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", "collaboration pressure")),
                    metadata={
                        "partner_id": partner_id,
                        "project": str(pressure.get("project", "scenario collaboration")),
                        "pressure": json_copy(pressure),
                    },
                )
            )
        return candidates

