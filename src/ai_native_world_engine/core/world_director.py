"""Deterministic world-fact pressure director."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .feedback import WorldEffect, effect
from .providers import ProviderContext, ProviderOutput
from .world import World, WorldNode


JsonDict = dict[str, Any]

WORLD_DIRECTOR_SOURCE = "deterministic-world-director"


@dataclass(slots=True)
class WorldDirectorConfig:
    max_effects: int = 12
    pressure_weight: float = 0.56
    ttl: int = 2

    @classmethod
    def from_dict(cls, value: JsonDict) -> "WorldDirectorConfig":
        return cls(
            max_effects=max(int(value.get("max_effects", 12) or 12), 0),
            pressure_weight=float(value.get("pressure_weight", 0.56) or 0.56),
            ttl=max(int(value.get("ttl", 2) or 2), 1),
        )

    def to_dict(self) -> JsonDict:
        return {
            "max_effects": self.max_effects,
            "pressure_weight": self.pressure_weight,
            "ttl": self.ttl,
        }


class DeterministicWorldDirectorProvider:
    """Reads world facts and emits structured pressure for grounded rules."""

    name = WORLD_DIRECTOR_SOURCE

    def __init__(self, config: WorldDirectorConfig | None = None) -> None:
        self.config = config or WorldDirectorConfig()

    def observe(self, context: ProviderContext) -> ProviderOutput:
        effects: list[WorldEffect] = []
        effects.extend(_logistics_pressures(context.world, self.config))
        effects.extend(_combat_pressures(context.world, self.config))
        effects.extend(_social_pressures(context.world, self.config))
        effects.extend(_science_pressures(context.world, self.config))
        effects.extend(_collaboration_pressures(context.world, self.config))
        effects.extend(_production_pressures(context.world, self.config))
        effects.extend(_economic_exchange_pressures(context.world, self.config))
        effects = effects[: self.config.max_effects]
        return ProviderOutput(
            source=self.name,
            summary=f"world director emitted {len(effects)} causal pressures",
            effects=effects,
            metadata={
                "provider_tick": context.tick,
                "provider_runtime": {
                    "provider": self.name,
                    "attempts": 1,
                    "estimated_cost": 0.0,
                    "cost_unit": "credits",
                    "latency_ms": 0.0,
                },
                "world_director": {
                    "enabled": True,
                    "effect_count": len(effects),
                    "config": self.config.to_dict(),
                },
            },
        )


def _logistics_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    for receiver in sorted(world.nodes.values(), key=lambda node: node.id):
        need = _logistics_need(receiver)
        if not need:
            continue
        route = _best_supply_route(world, receiver.id, need["resource"])
        if route is None:
            continue
        supplier = world.node(str(route["supplier_id"]))
        if _has_any_pressure(supplier) or _has_pressure(supplier, "logistics", receiver.id):
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{supplier.id}",
                rule="logistics",
                weight=config.pressure_weight,
                ttl=config.ttl,
                source=WORLD_DIRECTOR_SOURCE,
                reason=str(need["reason"]),
                to=f"node:{receiver.id}",
                resource=str(need["resource"]),
                amount=float(need["amount"]),
                heal_amount=float(need.get("heal_amount", 0.0) or 0.0),
                require_route=True,
            )
        )
    return effects


def _combat_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    threat_types = {"threat", "hostility", "enemy", "attack_risk"}
    for edge in sorted(world.relationships.values(), key=lambda item: item.key):
        if edge.type not in threat_types and edge.weight >= 0:
            continue
        if not world.has_node(edge.source) or not world.has_node(edge.target):
            continue
        attacker = world.node(edge.source)
        target = world.node(edge.target)
        if not _viable_actor(attacker) or not _viable_actor(target):
            continue
        if _has_any_pressure(attacker) or _has_pressure(attacker, "combat", target.id):
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{attacker.id}",
                rule="combat",
                weight=config.pressure_weight + min(abs(float(edge.weight)), 1.0) * 0.2,
                ttl=config.ttl,
                source=WORLD_DIRECTOR_SOURCE,
                reason=f"relationship threat {edge.type}",
                to=f"node:{target.id}",
                damage=1.0,
                max_range=max(attacker.position.distance_to(target.position) + 0.1, 1.0),
            )
        )
    return effects


def _social_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    relation_types = {"trust", "influence", "follow", "follows"}
    for edge in sorted(world.relationships.values(), key=lambda item: (-item.weight, item.key)):
        if edge.type not in relation_types or edge.weight <= 0:
            continue
        if not world.has_node(edge.source) or not world.has_node(edge.target):
            continue
        source = world.node(edge.source)
        target = world.node(edge.target)
        signal = _social_signal(target)
        if not signal or _has_any_pressure(source) or _has_pressure(source, "social_spread", target.id):
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{source.id}",
                rule="social_spread",
                weight=config.pressure_weight + min(float(edge.weight), 1.0) * 0.1,
                ttl=config.ttl,
                source=WORLD_DIRECTOR_SOURCE,
                reason=f"relationship {edge.type} can carry {signal}",
                to=f"node:{target.id}",
                signal=signal,
                require_relationship=True,
            )
        )
    return effects


def _science_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    if not any(_active_infection(node) for node in world.nodes.values()):
        return []
    effects: list[WorldEffect] = []
    for node in sorted(world.nodes.values(), key=lambda item: item.id):
        identity = f"{node.type} {node.attributes.get('identity', '')} {node.name}".lower()
        if "scientist" not in identity and "science" not in identity:
            continue
        if _has_any_pressure(node) or _has_pressure(node, "science_publish"):
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{node.id}",
                rule="science_publish",
                weight=config.pressure_weight,
                ttl=config.ttl,
                source=WORLD_DIRECTOR_SOURCE,
                reason="active infection risk needs published findings",
                title="Deterministic Field Update",
                topic="active infection and response evidence",
            )
        )
    return effects


def _collaboration_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    relation_types = {"coordination", "collaboration", "dependency"}
    for edge in sorted(world.relationships.values(), key=lambda item: (-item.weight, item.key)):
        if edge.type not in relation_types or edge.weight <= 0:
            continue
        if not world.has_node(edge.source) or not world.has_node(edge.target):
            continue
        source = world.node(edge.source)
        if _has_any_pressure(source) or _has_pressure(source, "collaboration", edge.target):
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{source.id}",
                rule="collaboration",
                weight=config.pressure_weight,
                ttl=config.ttl,
                source=WORLD_DIRECTOR_SOURCE,
                reason=f"relationship {edge.type} indicates coordination opportunity",
                **{"with": f"node:{edge.target}"},
                project=f"{edge.type} response alignment",
            )
        )
    return effects


def _production_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    for node in sorted(world.nodes.values(), key=lambda item: item.id):
        if _has_any_pressure(node):
            continue
        plan = _production_plan(node)
        if not plan:
            continue
        if any(_resource_amount(node, resource) < cost for resource, cost in plan["input_costs"].items()):
            continue
        effects.append(
            effect(
                "rule_pressure_add",
                target=f"node:{node.id}",
                rule="production",
                weight=config.pressure_weight,
                ttl=config.ttl,
                source=WORLD_DIRECTOR_SOURCE,
                reason=str(plan["reason"]),
                output_resource=str(plan["output_resource"]),
                amount=float(plan["amount"]),
                input_costs=plan["input_costs"],
                capacity=plan.get("capacity"),
                project=str(plan["project"]),
            )
        )
    return effects


def _economic_exchange_pressures(world: World, config: WorldDirectorConfig) -> list[WorldEffect]:
    effects: list[WorldEffect] = []
    offers = _market_offers(world)
    for buyer in sorted(world.nodes.values(), key=lambda item: item.id):
        if _has_any_pressure(buyer):
            continue
        needs = _market_needs(buyer)
        if not needs:
            continue
        budget = _optional_float(buyer.attributes.get("budget")) or 0.0
        for need in needs:
            offer = _best_market_offer(offers, buyer.id, need, budget)
            if offer is None:
                continue
            amount = min(float(need["amount"]), float(offer["amount"]))
            total_price = amount * float(offer["unit_price"])
            effects.append(
                effect(
                    "rule_pressure_add",
                    target=f"node:{buyer.id}",
                    rule="economic_exchange",
                    weight=config.pressure_weight,
                    ttl=config.ttl,
                    source=WORLD_DIRECTOR_SOURCE,
                    reason=f"market need for {need['resource']} matches offer from {offer['seller_id']}",
                    **{"from": f"node:{offer['seller_id']}"},
                    resource=str(need["resource"]),
                    amount=amount,
                    unit_price=float(offer["unit_price"]),
                    total_price=total_price,
                    currency=str(offer.get("currency", buyer.attributes.get("currency", "credits"))),
                )
            )
            break
    return effects


def _logistics_need(node: WorldNode) -> JsonDict:
    health = _optional_float(node.attributes.get("health"))
    max_health = _optional_float(node.attributes.get("max_health")) or 10.0
    if health is not None and health <= max_health * 0.5:
        return {
            "resource": "medical_supplies",
            "amount": 1.0,
            "heal_amount": max(1.0, min(max_health - health, 3.0)),
            "reason": "critical health needs medical logistics",
        }
    resources = node.attributes.get("resources")
    if isinstance(resources, dict):
        for resource in ("food", "water", "supplies"):
            if float(resources.get(resource, 0.0) or 0.0) <= 0:
                return {
                    "resource": resource if resource != "supplies" else "supplies",
                    "amount": 1.0,
                    "reason": f"resource scarcity needs {resource}",
                }
    return {}


def _production_plan(node: WorldNode) -> JsonDict:
    production = node.attributes.get("production")
    if not isinstance(production, dict):
        return {}
    output_resource = str(
        production.get("output_resource", production.get("resource", production.get("planned_output_resource", "")))
    )
    amount = _optional_float(production.get("amount", production.get("planned_amount", production.get("output_amount"))))
    if not output_resource or amount is None or amount <= 0:
        return {}
    capacity = _optional_float(production.get("capacity", production.get("max_amount")))
    if capacity is not None and amount > capacity:
        return {}
    return {
        "output_resource": output_resource,
        "amount": amount,
        "capacity": capacity,
        "input_costs": _resource_costs(production.get("input_costs", production.get("inputs", {}))),
        "project": str(production.get("project", production.get("product", output_resource))),
        "reason": str(production.get("reason", f"production plan for {output_resource}")),
    }


def _market_offers(world: World) -> list[JsonDict]:
    offers: list[JsonDict] = []
    for seller in sorted(world.nodes.values(), key=lambda item: item.id):
        raw_offers = seller.attributes.get("market_offers", seller.attributes.get("market_offer", []))
        if isinstance(raw_offers, dict):
            raw_offers = [raw_offers]
        if not isinstance(raw_offers, list):
            continue
        for raw_offer in raw_offers:
            if not isinstance(raw_offer, dict):
                continue
            resource = str(raw_offer.get("resource", ""))
            amount = _optional_float(raw_offer.get("amount"))
            unit_price = _optional_float(raw_offer.get("unit_price", raw_offer.get("price")))
            if not resource or amount is None or amount <= 0 or unit_price is None or unit_price < 0:
                continue
            available = _resource_amount(seller, resource)
            if available <= 0:
                continue
            offers.append(
                {
                    "seller_id": seller.id,
                    "resource": resource,
                    "amount": min(amount, available),
                    "unit_price": unit_price,
                    "currency": raw_offer.get("currency", seller.attributes.get("currency", "credits")),
                }
            )
    return offers


def _market_needs(node: WorldNode) -> list[JsonDict]:
    raw_needs = node.attributes.get("market_needs", node.attributes.get("market_need", []))
    if isinstance(raw_needs, dict):
        raw_needs = [raw_needs]
    if not isinstance(raw_needs, list):
        return []
    needs: list[JsonDict] = []
    for raw_need in raw_needs:
        if not isinstance(raw_need, dict):
            continue
        resource = str(raw_need.get("resource", ""))
        amount = _optional_float(raw_need.get("amount"))
        max_unit_price = _optional_float(raw_need.get("max_unit_price", raw_need.get("unit_price", raw_need.get("price"))))
        if not resource or amount is None or amount <= 0:
            continue
        needs.append(
            {
                "resource": resource,
                "amount": amount,
                "max_unit_price": max_unit_price,
            }
        )
    return needs


def _best_market_offer(offers: list[JsonDict], buyer_id: str, need: JsonDict, budget: float) -> JsonDict | None:
    matching: list[JsonDict] = []
    for offer in offers:
        if str(offer.get("seller_id", "")) == buyer_id:
            continue
        if str(offer.get("resource", "")) != str(need.get("resource", "")):
            continue
        unit_price = float(offer.get("unit_price", 0.0) or 0.0)
        max_unit_price = need.get("max_unit_price")
        if isinstance(max_unit_price, (int, float)) and unit_price > float(max_unit_price):
            continue
        amount = min(float(need.get("amount", 0.0) or 0.0), float(offer.get("amount", 0.0) or 0.0))
        if amount <= 0 or amount * unit_price > budget:
            continue
        matching.append(offer)
    matching.sort(key=lambda item: (float(item.get("unit_price", 0.0) or 0.0), str(item.get("seller_id", ""))))
    return matching[0] if matching else None


def _best_supply_route(world: World, receiver_id: str, resource: str) -> JsonDict | None:
    route_types = {"route", "supply_route", "logistics_route", "transport_link"}
    candidates: list[JsonDict] = []
    for edge in world.relationships.values():
        if edge.type not in route_types:
            continue
        if edge.target == receiver_id:
            supplier_id = edge.source
        elif edge.source == receiver_id:
            supplier_id = edge.target
        else:
            continue
        if not world.has_node(supplier_id):
            continue
        status = str(edge.metadata.get("status", "open")).lower()
        if status in {"closed", "blocked", "disabled"} or edge.weight <= 0:
            continue
        supplier = world.node(supplier_id)
        if _resource_amount(supplier, resource) <= 0:
            continue
        candidates.append({"supplier_id": supplier_id, "weight": edge.weight, "key": edge.key})
    candidates.sort(key=lambda item: (-float(item["weight"]), str(item["key"])))
    return candidates[0] if candidates else None


def _social_signal(node: WorldNode) -> str:
    for key, value in sorted(node.attributes.items()):
        if key.startswith("signal:") and isinstance(value, (int, float)):
            signal = key.split(":", 1)[1]
            if signal:
                return signal
    for key, value in sorted(node.attributes.items()):
        if key.startswith("belief:") and isinstance(value, (int, float)):
            signal = key.split(":", 1)[1]
            if signal:
                return signal
    return ""


def _has_pressure(node: WorldNode, rule: str, target_id: str = "") -> bool:
    for pressure in node.rule_pressures:
        if str(pressure.get("rule", "")) != rule:
            continue
        if not target_id:
            return True
        raw_target = pressure.get("to", pressure.get("target_node", pressure.get("target", pressure.get("with", ""))))
        if _node_id(raw_target) == target_id:
            return True
    return False


def _has_any_pressure(node: WorldNode) -> bool:
    return bool(node.rule_pressures)


def _active_infection(node: WorldNode) -> bool:
    infection = node.attributes.get("infection")
    if not isinstance(infection, dict):
        return False
    return str(infection.get("status", "")) in {"exposed", "infectious"}


def _viable_actor(node: WorldNode) -> bool:
    if node.attributes.get("alive", True) is False:
        return False
    health = _optional_float(node.attributes.get("health"))
    return health is None or health > 0


def _resource_amount(node: WorldNode, resource: str) -> float:
    resources = node.attributes.get("resources")
    if not isinstance(resources, dict):
        return 0.0
    return float(resources.get(resource, 0.0) or 0.0)


def _resource_costs(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    costs: dict[str, float] = {}
    for resource, amount in value.items():
        numeric = _optional_float(amount)
        if numeric is None or numeric <= 0:
            continue
        costs[str(resource)] = numeric
    return costs


def _node_id(value: Any) -> str:
    text = str(value)
    return text.split(":", 1)[1] if ":" in text else text


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
