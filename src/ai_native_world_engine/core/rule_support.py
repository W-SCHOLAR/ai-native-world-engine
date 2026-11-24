"""Low-level helpers shared by rule packages and lifecycle processing."""

from .events import json_copy
from .rule_contracts import JsonDict, RuleCandidate
from .world import World, WorldNode
from .rule_registry import canonical_rule_name

def _single_node_pressure_candidates(
    node: WorldNode,
    package_name: str,
    names: set[str],
    action: str,
    defaults: JsonDict,
) -> list[RuleCandidate]:
    candidates: list[RuleCandidate] = []
    for pressure in node.rule_pressures:
        if not _rule_matches(pressure, names):
            continue
        metadata = json_copy(defaults)
        metadata.update({key: json_copy(value) for key, value in pressure.items() if key not in {"type", "target", "node_id"}})
        metadata["pressure"] = json_copy(pressure)
        candidates.append(
            RuleCandidate(
                node_id=node.id,
                action=action,
                score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                rule=package_name,
                reason=str(pressure.get("reason", f"{package_name} pressure")),
                metadata=metadata,
            )
        )
    return candidates


def _rule_matches(pressure: JsonDict, names: set[str]) -> bool:
    canonical_names = {canonical_rule_name(name) for name in names}
    return canonical_rule_name(str(pressure.get("rule", ""))) in canonical_names


def _is_alive(node: WorldNode) -> bool:
    if node.attributes.get("alive", True) is False:
        return False
    if "health" in node.attributes and float(node.attributes.get("health", 0.0) or 0.0) <= 0:
        return False
    return True


def _health_factor(node: WorldNode) -> float:
    if "health" not in node.attributes:
        return 1.0
    health = float(node.attributes.get("health", 0.0) or 0.0)
    max_health = float(node.attributes.get("max_health", max(health, 10.0)) or 10.0)
    if max_health <= 0:
        return 0.0
    return _clamp(health / max_health, 0.0, 1.5)


def _morale_factor(node: WorldNode) -> float:
    morale = float(node.attributes.get("morale", node.attributes.get("combat_morale", 1.0)) or 0.0)
    return _clamp(morale, 0.0, 2.0)


def _logistics_capacity(node: WorldNode, pressure: JsonDict) -> float | None:
    capacity = _optional_float(pressure.get("capacity", pressure.get("max_amount")))
    if capacity is not None:
        return capacity
    for key in ("logistics_capacity", "transport_capacity", "vehicle_capacity", "capacity"):
        capacity = _optional_float(node.attributes.get(key))
        if capacity is not None:
            return capacity
    return None


def _production_capacity(node: WorldNode, pressure: JsonDict) -> float | None:
    capacity = _optional_float(pressure.get("capacity", pressure.get("max_amount")))
    if capacity is not None:
        return capacity
    production = node.attributes.get("production")
    if isinstance(production, dict):
        for key in ("capacity", "max_amount", "output_capacity"):
            capacity = _optional_float(production.get(key))
            if capacity is not None:
                return capacity
    for key in ("production_capacity", "capacity"):
        capacity = _optional_float(node.attributes.get(key))
        if capacity is not None:
            return capacity
    return None


def _resource_costs(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    costs: dict[str, float] = {}
    for resource, amount in value.items():
        numeric = _optional_float(amount)
        if numeric is None or numeric <= 0:
            continue
        costs[str(resource)] = numeric
    return costs


def _route_between(world: World, source_id: str, target_id: str) -> JsonDict | None:
    route_types = {"route", "supply_route", "logistics_route", "transport_link"}
    best: JsonDict | None = None
    for edge in world.relationships.values():
        if edge.type not in route_types:
            continue
        if not ((edge.source == source_id and edge.target == target_id) or (edge.source == target_id and edge.target == source_id)):
            continue
        status = str(edge.metadata.get("status", "open")).lower()
        if status in {"closed", "blocked", "disabled"} or edge.weight <= 0:
            continue
        payload = {
            "source": edge.source,
            "target": edge.target,
            "type": edge.type,
            "weight": edge.weight,
            "metadata": json_copy(edge.metadata),
        }
        if best is None or float(payload["weight"]) > float(best.get("weight", 0.0) or 0.0):
            best = payload
    return best


def _relationship_strength(world: World, source_id: str, target_id: str, relation_types: set[str]) -> float:
    strength = 0.0
    for edge in world.relationships.values():
        if edge.type not in relation_types:
            continue
        if (edge.source == source_id and edge.target == target_id) or (edge.source == target_id and edge.target == source_id):
            strength = max(strength, edge.weight)
    return strength


def _pressure_bonus(node: WorldNode, rule: str) -> float:
    bonus = 0.0
    for pressure in node.rule_pressures:
        pressure_rule = canonical_rule_name(str(pressure.get("rule", "")))
        if pressure_rule == canonical_rule_name(rule) or str(pressure.get("rule", "")) == "移动":
            bonus += float(pressure.get("weight", 0.0))
    return bonus


def _node_id(value: object) -> str:
    text = str(value)
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _resource_amount(node: WorldNode, resource: str) -> float:
    resources = node.attributes.get("resources", {})
    if not isinstance(resources, dict):
        return 0.0
    return float(resources.get(resource, 0.0) or 0.0)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
