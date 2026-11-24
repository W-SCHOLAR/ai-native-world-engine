"""Relationship subgraph extraction for agent context packets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .domain_state import WorldDomainStateInspector
from .events import json_copy
from .world import World, WorldNode


JsonDict = dict[str, Any]

THREAT_RELATIONS = {"threat", "hostility", "competition", "governance_pressure", "risk"}
RESOURCE_KEYS = {"resources", "inventory", "capacity"}
ROUTE_RELATIONS = {"route", "supply_route", "logistics_route", "transport_link"}


@dataclass(slots=True)
class RelationshipSubgraph:
    seed_node_ids: list[str]
    nodes: list[JsonDict] = field(default_factory=list)
    edges: list[JsonDict] = field(default_factory=list)
    resources: list[JsonDict] = field(default_factory=list)
    threats: list[JsonDict] = field(default_factory=list)
    organizations: list[JsonDict] = field(default_factory=list)
    terrain: list[JsonDict] = field(default_factory=list)
    supply_chains: list[JsonDict] = field(default_factory=list)
    domain_profiles: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "seed_node_ids": list(self.seed_node_ids),
            "nodes": json_copy(self.nodes),
            "edges": json_copy(self.edges),
            "resources": json_copy(self.resources),
            "threats": json_copy(self.threats),
            "organizations": json_copy(self.organizations),
            "terrain": json_copy(self.terrain),
            "supply_chains": json_copy(self.supply_chains),
            "domain_profiles": json_copy(self.domain_profiles),
            "stats": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "resource_count": len(self.resources),
                "threat_count": len(self.threats),
                "organization_count": len(self.organizations),
                "terrain_count": len(self.terrain),
                "supply_chain_count": len(self.supply_chains),
                "domain_profile_count": len(self.domain_profiles),
            },
        }


class RelationshipSubgraphBuilder:
    def build(
        self,
        world: World,
        seed_node_ids: list[str],
        depth: int = 1,
        max_nodes: int = 32,
        max_edges: int = 96,
    ) -> RelationshipSubgraph:
        seeds = [node_id for node_id in dict.fromkeys(seed_node_ids) if world.has_node(node_id)]
        included = self._expand(world, seeds, depth, max_nodes)
        nodes = [self._node_payload(world.node(node_id)) for node_id in sorted(included)]
        edges = [
            edge.to_dict()
            for edge in sorted(world.relationships.values(), key=lambda item: item.key)
            if edge.source in included and edge.target in included
        ][: max(max_edges, 0)]
        return RelationshipSubgraph(
            seed_node_ids=seeds,
            nodes=nodes,
            edges=edges,
            resources=_resource_payloads(world, included),
            threats=_threat_payloads(edges),
            organizations=_organization_payloads(world, included),
            terrain=_terrain_payloads(world, included),
            supply_chains=_supply_chain_payloads(world, included, edges),
            domain_profiles=_domain_profile_payloads(world, included),
        )

    def _expand(self, world: World, seeds: list[str], depth: int, max_nodes: int) -> set[str]:
        included: set[str] = set(seeds)
        frontier = set(seeds)
        for _ in range(max(int(depth), 0)):
            next_frontier: set[str] = set()
            for edge in sorted(world.relationships.values(), key=lambda item: (-abs(item.weight), item.key)):
                if edge.source in frontier and edge.target not in included:
                    next_frontier.add(edge.target)
                if edge.target in frontier and edge.source not in included:
                    next_frontier.add(edge.source)
                if len(included) + len(next_frontier) >= max_nodes:
                    break
            included.update(sorted(next_frontier)[: max(max_nodes - len(included), 0)])
            frontier = next_frontier
            if not frontier or len(included) >= max_nodes:
                break
        return set(sorted(included)[: max(max_nodes, 0)])

    def _node_payload(self, node: WorldNode) -> JsonDict:
        attributes = node.attributes
        return {
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "position": node.position.to_dict(),
            "role": attributes.get("role") or attributes.get("identity") or attributes.get("organization_kind") or node.type,
            "agent_layer": attributes.get("agent_layer", ""),
            "parent_network": attributes.get("parent_network", ""),
            "rule_pressure_count": len(node.rule_pressures),
            "memory_count": len(node.memories),
        }


def _resource_payloads(world: World, included: set[str]) -> list[JsonDict]:
    payloads: list[JsonDict] = []
    for node_id in sorted(included):
        node = world.node(node_id)
        resources: JsonDict = {}
        for key in RESOURCE_KEYS:
            value = node.attributes.get(key)
            if isinstance(value, dict):
                resources[key] = json_copy(value)
        if resources:
            payloads.append({"node_id": node_id, "resources": resources})
    return payloads


def _threat_payloads(edges: list[JsonDict]) -> list[JsonDict]:
    return [
        {
            "source": edge.get("source", ""),
            "target": edge.get("target", ""),
            "type": edge.get("type", ""),
            "weight": edge.get("weight", 0.0),
            "metadata": json_copy(edge.get("metadata", {})),
        }
        for edge in edges
        if str(edge.get("type", "")) in THREAT_RELATIONS or float(edge.get("weight", 0.0) or 0.0) < 0
    ]


def _organization_payloads(world: World, included: set[str]) -> list[JsonDict]:
    org_ids = {
        node_id
        for node_id in included
        if world.node(node_id).type == "organization"
    }
    for node_id in included:
        parent_id = str(world.node(node_id).attributes.get("parent_network", ""))
        if parent_id and world.has_node(parent_id):
            org_ids.add(parent_id)
    return [
        {
            "id": org.id,
            "name": org.name,
            "kind": org.attributes.get("organization_kind", ""),
            "scope": org.attributes.get("scope", ""),
            "member_count": len(org.attributes.get("members", [])) if isinstance(org.attributes.get("members"), list) else 0,
        }
        for org in (world.node(node_id) for node_id in sorted(org_ids))
    ]


def _terrain_payloads(world: World, included: set[str]) -> list[JsonDict]:
    payloads: list[JsonDict] = []
    for node_id in sorted(included):
        node = world.node(node_id)
        terrain: JsonDict = {}
        if isinstance(node.attributes.get("terrain"), dict):
            terrain.update(json_copy(node.attributes["terrain"]))
        for key in ("terrain_type", "hazard", "region", "location_label"):
            if key in node.attributes:
                terrain[key] = json_copy(node.attributes[key])
        if terrain:
            payloads.append({"node_id": node_id, "terrain": terrain})
    return payloads


def _supply_chain_payloads(world: World, included: set[str], edges: list[JsonDict]) -> list[JsonDict]:
    payloads: list[JsonDict] = []
    for node_id in sorted(included):
        node = world.node(node_id)
        state: JsonDict = {}
        if isinstance(node.attributes.get("supply_chain"), dict):
            state.update(json_copy(node.attributes["supply_chain"]))
        for key in ("routes", "dependencies", "bottlenecks", "inventory"):
            if key in node.attributes:
                state[key] = json_copy(node.attributes[key])
        if state:
            payloads.append({"kind": "node_supply_chain", "node_id": node_id, "state": state})
    for edge in edges:
        if str(edge.get("type", "")) not in ROUTE_RELATIONS:
            continue
        payloads.append(
            {
                "kind": "route",
                "source": edge.get("source", ""),
                "target": edge.get("target", ""),
                "type": edge.get("type", ""),
                "weight": edge.get("weight", 0.0),
                "metadata": json_copy(edge.get("metadata", {})),
            }
        )
    return payloads


def _domain_profile_payloads(world: World, included: set[str]) -> list[JsonDict]:
    inspector = WorldDomainStateInspector()
    return [
        inspector.inspect_node(world, node_id).to_dict()
        for node_id in sorted(included)
    ]
