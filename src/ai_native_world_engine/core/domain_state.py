"""Typed domain-state projections and validation for flexible node attributes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import json_copy
from .world import World, WorldNode


JsonDict = dict[str, Any]


@dataclass(slots=True)
class DomainStateIssue:
    node_id: str
    field: str
    severity: str
    message: str
    value: Any = None

    def to_dict(self) -> JsonDict:
        return {
            "node_id": self.node_id,
            "field": self.field,
            "severity": self.severity,
            "message": self.message,
            "value": json_copy(self.value),
        }


@dataclass(slots=True)
class DomainStateProfile:
    node_id: str
    node_type: str
    health: JsonDict = field(default_factory=dict)
    resources: JsonDict = field(default_factory=dict)
    infection: JsonDict = field(default_factory=dict)
    policies: JsonDict = field(default_factory=dict)
    publications: list[JsonDict] = field(default_factory=list)
    migration: JsonDict = field(default_factory=dict)
    collaborations: list[JsonDict] = field(default_factory=list)
    signals: JsonDict = field(default_factory=dict)
    organization: JsonDict = field(default_factory=dict)
    economy: JsonDict = field(default_factory=dict)
    beliefs: JsonDict = field(default_factory=dict)
    military: JsonDict = field(default_factory=dict)
    production: JsonDict = field(default_factory=dict)
    terrain: JsonDict = field(default_factory=dict)
    supply_chain: JsonDict = field(default_factory=dict)
    organization_structure: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "health": json_copy(self.health),
            "resources": json_copy(self.resources),
            "infection": json_copy(self.infection),
            "policies": json_copy(self.policies),
            "publications": json_copy(self.publications),
            "migration": json_copy(self.migration),
            "collaborations": json_copy(self.collaborations),
            "signals": json_copy(self.signals),
            "organization": json_copy(self.organization),
            "economy": json_copy(self.economy),
            "beliefs": json_copy(self.beliefs),
            "military": json_copy(self.military),
            "production": json_copy(self.production),
            "terrain": json_copy(self.terrain),
            "supply_chain": json_copy(self.supply_chain),
            "organization_structure": json_copy(self.organization_structure),
        }


@dataclass(slots=True)
class DomainStateValidationReport:
    issue_count: int
    issues: list[JsonDict] = field(default_factory=list)
    profiles: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "issue_count": self.issue_count,
            "issues": json_copy(self.issues),
            "profiles": json_copy(self.profiles),
        }


@dataclass(slots=True)
class WorldDomainStateSummary:
    node_count: int
    health: JsonDict = field(default_factory=dict)
    infection: JsonDict = field(default_factory=dict)
    resources: JsonDict = field(default_factory=dict)
    policies: JsonDict = field(default_factory=dict)
    migration: JsonDict = field(default_factory=dict)
    publications: JsonDict = field(default_factory=dict)
    collaborations: JsonDict = field(default_factory=dict)
    signals: JsonDict = field(default_factory=dict)
    risk: JsonDict = field(default_factory=dict)
    economy: JsonDict = field(default_factory=dict)
    beliefs: JsonDict = field(default_factory=dict)
    military: JsonDict = field(default_factory=dict)
    production: JsonDict = field(default_factory=dict)
    terrain: JsonDict = field(default_factory=dict)
    supply_chain: JsonDict = field(default_factory=dict)
    organization_structure: JsonDict = field(default_factory=dict)
    domain_model_coverage: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "node_count": self.node_count,
            "health": json_copy(self.health),
            "infection": json_copy(self.infection),
            "resources": json_copy(self.resources),
            "policies": json_copy(self.policies),
            "migration": json_copy(self.migration),
            "publications": json_copy(self.publications),
            "collaborations": json_copy(self.collaborations),
            "signals": json_copy(self.signals),
            "risk": json_copy(self.risk),
            "economy": json_copy(self.economy),
            "beliefs": json_copy(self.beliefs),
            "military": json_copy(self.military),
            "production": json_copy(self.production),
            "terrain": json_copy(self.terrain),
            "supply_chain": json_copy(self.supply_chain),
            "organization_structure": json_copy(self.organization_structure),
            "domain_model_coverage": json_copy(self.domain_model_coverage),
        }


class WorldDomainStateInspector:
    def inspect_node(self, world: World, node_id: str) -> DomainStateProfile:
        return self.profile(world.node(node_id))

    def validate_snapshot(self, snapshot: JsonDict, include_profiles: bool = False) -> DomainStateValidationReport:
        return self.validate_world(_world_from_snapshot(snapshot), include_profiles=include_profiles)

    def summarize_snapshot(self, snapshot: JsonDict) -> WorldDomainStateSummary:
        return self.summarize_world(_world_from_snapshot(snapshot))

    def profile(self, node: WorldNode) -> DomainStateProfile:
        attributes = node.attributes
        return DomainStateProfile(
            node_id=node.id,
            node_type=node.type,
            health=_health(attributes),
            resources=_object(attributes.get("resources")),
            infection=_object(attributes.get("infection")),
            policies=_object(attributes.get("policies")),
            publications=_list_of_dicts(attributes.get("publications")),
            migration=_object(attributes.get("migration")),
            collaborations=_list_of_dicts(attributes.get("collaborations")),
            signals=_signals(attributes),
            organization=_organization(attributes),
            economy=_economy(attributes),
            beliefs=_beliefs(attributes),
            military=_military(attributes),
            production=_production(attributes),
            terrain=_terrain(attributes),
            supply_chain=_supply_chain(attributes),
            organization_structure=_organization_structure(attributes),
        )

    def validate_world(self, world: World, include_profiles: bool = False) -> DomainStateValidationReport:
        issues: list[DomainStateIssue] = []
        profiles: list[JsonDict] = []
        for node in world.nodes.values():
            profile = self.profile(node)
            if include_profiles:
                profiles.append(profile.to_dict())
            issues.extend(_validate_node(node))
        issue_dicts = [issue.to_dict() for issue in sorted(issues, key=lambda item: (item.node_id, item.field, item.message))]
        return DomainStateValidationReport(len(issue_dicts), issue_dicts, profiles)

    def summarize_world(self, world: World) -> WorldDomainStateSummary:
        profiles = [self.profile(node).to_dict() for node in world.nodes.values()]
        health = _health_summary(profiles)
        infection = _infection_summary(profiles)
        resources = _resource_summary(profiles)
        policies = _policy_summary(profiles)
        migration = _migration_summary(profiles)
        publications = {"count": sum(len(_list(profile.get("publications"))) for profile in profiles)}
        collaborations = {"count": sum(len(_list(profile.get("collaborations"))) for profile in profiles)}
        signals = _signal_summary(profiles)
        economy = _presence_summary(profiles, "economy")
        beliefs = _belief_summary(profiles)
        military = _presence_summary(profiles, "military")
        production = _presence_summary(profiles, "production")
        terrain = _presence_summary(profiles, "terrain")
        supply_chain = _presence_summary(profiles, "supply_chain")
        organization_structure = _presence_summary(profiles, "organization_structure")
        domain_model_coverage = _domain_model_coverage(
            profiles,
            [
                "health",
                "resources",
                "infection",
                "policies",
                "migration",
                "publications",
                "collaborations",
                "signals",
                "economy",
                "beliefs",
                "military",
                "production",
                "terrain",
                "supply_chain",
                "organization_structure",
            ],
        )
        risk = _risk_summary(health, infection, resources, policies, migration)
        return WorldDomainStateSummary(
            node_count=len(profiles),
            health=health,
            infection=infection,
            resources=resources,
            policies=policies,
            migration=migration,
            publications=publications,
            collaborations=collaborations,
            signals=signals,
            risk=risk,
            economy=economy,
            beliefs=beliefs,
            military=military,
            production=production,
            terrain=terrain,
            supply_chain=supply_chain,
            organization_structure=organization_structure,
            domain_model_coverage=domain_model_coverage,
        )


def _validate_node(node: WorldNode) -> list[DomainStateIssue]:
    attributes = node.attributes
    issues: list[DomainStateIssue] = []
    if "health" in attributes and not isinstance(attributes["health"], (int, float)):
        issues.append(_issue(node, "health", "error", "health must be numeric", attributes["health"]))
    if isinstance(attributes.get("health"), (int, float)) and float(attributes["health"]) < 0:
        issues.append(_issue(node, "health", "error", "health cannot be negative", attributes["health"]))
    if "resources" in attributes:
        resources = attributes["resources"]
        if not isinstance(resources, dict):
            issues.append(_issue(node, "resources", "error", "resources must be an object", resources))
        else:
            for name, amount in resources.items():
                if not isinstance(amount, (int, float)):
                    issues.append(_issue(node, f"resources.{name}", "error", "resource amount must be numeric", amount))
                elif float(amount) < 0:
                    issues.append(_issue(node, f"resources.{name}", "error", "resource amount cannot be negative", amount))
    for field_name in ("infection", "policies", "migration"):
        if field_name in attributes and not isinstance(attributes[field_name], dict):
            issues.append(_issue(node, field_name, "error", f"{field_name} must be an object", attributes[field_name]))
    for field_name in ("economy", "beliefs", "military", "production", "terrain", "supply_chain", "organization_structure"):
        if field_name in attributes and not isinstance(attributes[field_name], dict):
            issues.append(_issue(node, field_name, "error", f"{field_name} must be an object", attributes[field_name]))
    if isinstance(attributes.get("infection"), dict):
        severity = attributes["infection"].get("severity")
        if severity is not None and (not isinstance(severity, (int, float)) or float(severity) < 0):
            issues.append(_issue(node, "infection.severity", "error", "infection severity must be non-negative", severity))
    for field_name in ("publications", "collaborations"):
        if field_name in attributes and not isinstance(attributes[field_name], list):
            issues.append(_issue(node, field_name, "error", f"{field_name} must be a list", attributes[field_name]))
    for key, value in attributes.items():
        if key.startswith("signal:") and not isinstance(value, (int, float)):
            issues.append(_issue(node, key, "error", "signal counters must be numeric", value))
        if key.startswith("belief:") and not isinstance(value, (int, float)):
            issues.append(_issue(node, key, "error", "belief counters must be numeric", value))
    for field_name in (
        "budget",
        "price_index",
        "demand",
        "supply",
        "force_strength",
        "readiness",
        "capacity",
        "output",
        "backlog",
        "research_progress",
    ):
        if field_name in attributes and not isinstance(attributes[field_name], (int, float)):
            issues.append(_issue(node, field_name, "error", f"{field_name} must be numeric", attributes[field_name]))
    return issues


def _issue(node: WorldNode, field: str, severity: str, message: str, value: Any) -> DomainStateIssue:
    return DomainStateIssue(node.id, field, severity, message, value)


def _world_from_snapshot(snapshot: JsonDict) -> World:
    from .world import Position, RelationshipEdge

    world = World(str(snapshot.get("id", "domain-state-snapshot")))
    world.tick = int(snapshot.get("tick", 0) or 0)
    world.attributes = json_copy(_object(snapshot.get("attributes")))
    for raw_node in _list(snapshot.get("nodes")):
        node_data = _object(raw_node)
        node_id = str(node_data.get("id", ""))
        if not node_id:
            continue
        world.nodes[node_id] = WorldNode(
            id=node_id,
            type=str(node_data.get("type", "")),
            name=str(node_data.get("name", node_id)),
            position=Position.from_value(_object(node_data.get("position"))),
            attributes=json_copy(_object(node_data.get("attributes"))),
            memories=json_copy(_list(node_data.get("memories"))),
            rule_pressures=json_copy(_list(node_data.get("rule_pressures"))),
            key_character=json_copy(_object(node_data.get("key_character"))),
        )
    for raw_edge in _list(snapshot.get("relationships")):
        edge_data = _object(raw_edge)
        edge = RelationshipEdge(
            source=str(edge_data.get("source", "")),
            target=str(edge_data.get("target", "")),
            type=str(edge_data.get("type", "")),
            weight=float(edge_data.get("weight", 0.0) or 0.0),
            metadata=json_copy(_object(edge_data.get("metadata"))),
        )
        world.relationships[edge.key] = edge
    return world


def _health(attributes: JsonDict) -> JsonDict:
    health: JsonDict = {}
    if "health" in attributes:
        health["value"] = attributes["health"]
    if "alive" in attributes:
        health["alive"] = attributes["alive"]
    return health


def _signals(attributes: JsonDict) -> JsonDict:
    return {
        key.split(":", 1)[1]: value
        for key, value in attributes.items()
        if key.startswith("signal:")
    }


def _organization(attributes: JsonDict) -> JsonDict:
    return {
        key: json_copy(attributes[key])
        for key in ("role", "identity", "organization_kind", "agent_layer")
        if key in attributes
    }


def _economy(attributes: JsonDict) -> JsonDict:
    return _slice(attributes, "economy", ("budget", "currency", "market", "price_index", "demand", "supply"))


def _beliefs(attributes: JsonDict) -> JsonDict:
    beliefs = _object(attributes.get("beliefs"))
    beliefs.update(
        {
            key.split(":", 1)[1]: value
            for key, value in attributes.items()
            if key.startswith("belief:")
        }
    )
    return beliefs


def _military(attributes: JsonDict) -> JsonDict:
    return _slice(attributes, "military", ("force_strength", "readiness", "unit_type", "doctrine", "stance"))


def _production(attributes: JsonDict) -> JsonDict:
    return _slice(attributes, "production", ("capacity", "output", "backlog", "research_progress"))


def _terrain(attributes: JsonDict) -> JsonDict:
    return _slice(attributes, "terrain", ("terrain_type", "hazard", "region", "location_label"))


def _supply_chain(attributes: JsonDict) -> JsonDict:
    return _slice(attributes, "supply_chain", ("routes", "dependencies", "bottlenecks", "inventory"))


def _organization_structure(attributes: JsonDict) -> JsonDict:
    return _slice(
        attributes,
        "organization_structure",
        ("authority", "hierarchy", "teams", "decision_state", "parent_network"),
    )


def _slice(attributes: JsonDict, object_key: str, scalar_keys: tuple[str, ...]) -> JsonDict:
    result = _object(attributes.get(object_key))
    for key in scalar_keys:
        if key in attributes:
            result[key] = json_copy(attributes[key])
    return result


def _health_summary(profiles: list[JsonDict]) -> JsonDict:
    values: list[float] = []
    dead_count = 0
    critical_count = 0
    for profile in profiles:
        health = _object(profile.get("health"))
        if health.get("alive") is False:
            dead_count += 1
        value = health.get("value")
        if isinstance(value, (int, float)):
            numeric = float(value)
            values.append(numeric)
            if numeric <= 2:
                critical_count += 1
    return {
        "tracked_count": len(values),
        "average": round(sum(values) / len(values), 4) if values else 0.0,
        "critical_count": critical_count,
        "dead_count": dead_count,
    }


def _infection_summary(profiles: list[JsonDict]) -> JsonDict:
    by_status: dict[str, int] = {}
    pathogens: dict[str, int] = {}
    active_count = 0
    for profile in profiles:
        infection = _object(profile.get("infection"))
        status = str(infection.get("status", "")).strip()
        if not status:
            continue
        by_status[status] = by_status.get(status, 0) + 1
        if status in {"exposed", "infectious"}:
            active_count += 1
        pathogen = str(infection.get("pathogen", "")).strip()
        if pathogen:
            pathogens[pathogen] = pathogens.get(pathogen, 0) + 1
    return {
        "active_count": active_count,
        "by_status": dict(sorted(by_status.items())),
        "pathogens": dict(sorted(pathogens.items())),
    }


def _resource_summary(profiles: list[JsonDict]) -> JsonDict:
    totals: dict[str, float] = {}
    scarcity_nodes = 0
    for profile in profiles:
        resources = _object(profile.get("resources"))
        scarce = False
        for name, amount in resources.items():
            if not isinstance(amount, (int, float)):
                continue
            numeric = float(amount)
            totals[str(name)] = totals.get(str(name), 0.0) + numeric
            if str(name) in {"food", "water", "medical_supplies", "medicine", "supplies"} and numeric <= 0:
                scarce = True
        if scarce:
            scarcity_nodes += 1
    return {
        "totals": {name: _clean_number(value) for name, value in sorted(totals.items())},
        "scarcity_nodes": scarcity_nodes,
    }


def _policy_summary(profiles: list[JsonDict]) -> JsonDict:
    by_policy: dict[str, int] = {}
    active_count = 0
    movement_blocking_count = 0
    contact_blocking_count = 0
    for profile in profiles:
        policies = _object(profile.get("policies"))
        for name, state in policies.items():
            if not isinstance(state, dict) or str(state.get("status", "")).lower() != "active":
                continue
            policy = str(name)
            by_policy[policy] = by_policy.get(policy, 0) + 1
            active_count += 1
            if bool(state.get("blocks_movement")) or policy.lower() in {"quarantine", "isolation", "district_lockdown"}:
                movement_blocking_count += 1
            if bool(state.get("blocks_contact")) or policy.lower() in {"quarantine", "isolation", "district_lockdown"}:
                contact_blocking_count += 1
    return {
        "active_count": active_count,
        "by_policy": dict(sorted(by_policy.items())),
        "movement_blocking_count": movement_blocking_count,
        "contact_blocking_count": contact_blocking_count,
    }


def _migration_summary(profiles: list[JsonDict]) -> JsonDict:
    by_status: dict[str, int] = {}
    blocked_count = 0
    for profile in profiles:
        migration = _object(profile.get("migration"))
        status = str(migration.get("status", "")).strip()
        if not status:
            continue
        by_status[status] = by_status.get(status, 0) + 1
        if migration.get("blocked_by_policy") or int(migration.get("blocked_ticks", 0) or 0) > 0:
            blocked_count += 1
    return {"by_status": dict(sorted(by_status.items())), "blocked_count": blocked_count}


def _signal_summary(profiles: list[JsonDict]) -> JsonDict:
    totals: dict[str, float] = {}
    for profile in profiles:
        signals = _object(profile.get("signals"))
        for name, amount in signals.items():
            if isinstance(amount, (int, float)):
                totals[str(name)] = totals.get(str(name), 0.0) + float(amount)
    return {"totals": {name: _clean_number(value) for name, value in sorted(totals.items())}}


def _belief_summary(profiles: list[JsonDict]) -> JsonDict:
    summary = _presence_summary(profiles, "beliefs")
    totals: dict[str, float] = {}
    for profile in profiles:
        beliefs = _object(profile.get("beliefs"))
        for name, amount in beliefs.items():
            if isinstance(amount, (int, float)):
                totals[str(name)] = totals.get(str(name), 0.0) + float(amount)
    summary["totals"] = {name: _clean_number(value) for name, value in sorted(totals.items())}
    return summary


def _presence_summary(profiles: list[JsonDict], field_name: str) -> JsonDict:
    fields: dict[str, int] = {}
    tracked_count = 0
    for profile in profiles:
        value = _object(profile.get(field_name))
        if not value:
            continue
        tracked_count += 1
        for key in value:
            fields[str(key)] = fields.get(str(key), 0) + 1
    return {"tracked_count": tracked_count, "fields": dict(sorted(fields.items()))}


def _domain_model_coverage(profiles: list[JsonDict], field_names: list[str]) -> JsonDict:
    by_domain = {
        field_name: _coverage_count(profiles, field_name)
        for field_name in field_names
    }
    return {
        "by_domain": by_domain,
        "covered_domains": sum(1 for count in by_domain.values() if count > 0),
    }


def _coverage_count(profiles: list[JsonDict], field_name: str) -> int:
    count = 0
    for profile in profiles:
        value = profile.get(field_name)
        if isinstance(value, dict) and value:
            count += 1
        elif isinstance(value, list) and value:
            count += 1
    return count


def _risk_summary(
    health: JsonDict,
    infection: JsonDict,
    resources: JsonDict,
    policies: JsonDict,
    migration: JsonDict,
) -> JsonDict:
    by_status = _object(infection.get("by_status"))
    score = (
        int(by_status.get("infectious", 0) or 0) * 3
        + int(by_status.get("exposed", 0) or 0) * 2
        + int(health.get("critical_count", 0) or 0) * 2
        + int(health.get("dead_count", 0) or 0) * 4
        + int(resources.get("scarcity_nodes", 0) or 0)
        + int(policies.get("active_count", 0) or 0)
        + int(migration.get("blocked_count", 0) or 0)
    )
    if score == 0:
        level = "low"
    elif score <= 5:
        level = "elevated"
    elif score <= 10:
        level = "high"
    else:
        level = "critical"
    return {"score": score, "level": level}


def _object(value: Any) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_dicts(value: Any) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [json_copy(item) for item in value if isinstance(item, dict)]


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)
