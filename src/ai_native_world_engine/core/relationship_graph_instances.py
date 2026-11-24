"""Godot-parity relationship graph-instance discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import json_copy
from .relationship_round import PRIMARY_GRAPH_MIN_COVERAGE
from .world import World, WorldNode


JsonDict = dict[str, Any]

RELATIONSHIP_COVERAGE_LIMIT = 64
RELATIONSHIP_DETAILED_CANDIDATE_LIMIT = 16


@dataclass(slots=True)
class RelationshipGraphInstance:
    key: str
    kind: str
    root_node_id: str
    coverage_node_ids: list[str]
    candidate_node_ids: list[str]
    pressure_score: float = 0.0
    trigger_reasons: list[str] = field(default_factory=list)

    def to_metadata(self) -> JsonDict:
        return {
            "graph_instance": True,
            "graph_kind": self.kind,
            "graph_key": self.key,
            "root_node_id": self.root_node_id,
            "coverage_node_ids": list(self.coverage_node_ids),
            "candidate_node_ids": list(self.candidate_node_ids),
            "pressure_score": self.pressure_score,
            "trigger_reasons": list(self.trigger_reasons),
        }


def relationship_graph_instances(
    world: World,
    coverage_limit: int = RELATIONSHIP_COVERAGE_LIMIT,
    candidate_limit: int = RELATIONSHIP_DETAILED_CANDIDATE_LIMIT,
) -> list[RelationshipGraphInstance]:
    """Build one primary graph for every scenario-declared relationship network."""

    organizations = sorted(
        (
            node
            for node in world.nodes.values()
            if node.type == "organization"
            and node.attributes.get("agent_layer") == "relationship_network"
        ),
        key=lambda node: node.id,
    )
    recent_mentions = _recent_node_mentions(world)
    graphs: list[RelationshipGraphInstance] = []
    for organization in organizations:
        members = [
            node
            for node in world.nodes.values()
            if node.attributes.get("agent_layer") == "relationship_network_member"
            and node.attributes.get("parent_network") == organization.id
        ]
        ranked = _rank_members(world, members, recent_mentions)
        coverage = ranked[: max(int(coverage_limit), 0)]
        candidates = _diverse_candidates(coverage, max(int(candidate_limit), 0), world, recent_mentions)
        if len(coverage) < PRIMARY_GRAPH_MIN_COVERAGE or len(candidates) < 10:
            continue
        reasons = _graph_trigger_reasons(world, organization, candidates, recent_mentions)
        score = round(
            sum(_member_score(world, node, recent_mentions) for node in candidates)
            + recent_mentions.get(organization.id, 0) * 2.0,
            4,
        )
        graphs.append(
            RelationshipGraphInstance(
                key=f"tribe:{organization.id}",
                kind="tribe",
                root_node_id=organization.id,
                coverage_node_ids=[node.id for node in coverage],
                candidate_node_ids=[node.id for node in candidates],
                pressure_score=score,
                trigger_reasons=reasons,
            )
        )
    graphs.sort(key=lambda graph: (-graph.pressure_score, graph.key))
    return graphs


def enterprise_relationship_graph_instances(
    world: World,
    coverage_limit: int = RELATIONSHIP_COVERAGE_LIMIT,
    candidate_limit: int = RELATIONSHIP_DETAILED_CANDIDATE_LIMIT,
) -> list[RelationshipGraphInstance]:
    """Compatibility wrapper for the original Enterprise Earth public API."""

    return relationship_graph_instances(
        world,
        coverage_limit=coverage_limit,
        candidate_limit=candidate_limit,
    )


def _rank_members(
    world: World,
    members: list[WorldNode],
    recent_mentions: dict[str, int],
) -> list[WorldNode]:
    return sorted(
        members,
        key=lambda node: (
            -_member_score(world, node, recent_mentions),
            str(node.attributes.get("role", "")),
            node.id,
        ),
    )


def _diverse_candidates(
    coverage: list[WorldNode],
    limit: int,
    world: World,
    recent_mentions: dict[str, int],
) -> list[WorldNode]:
    """Interleave role groups while preserving pressure priority within each role."""

    by_role: dict[str, list[WorldNode]] = {}
    for node in coverage:
        role = str(node.attributes.get("role") or node.attributes.get("identity") or node.type)
        by_role.setdefault(role, []).append(node)
    for nodes in by_role.values():
        nodes.sort(key=lambda node: (-_member_score(world, node, recent_mentions), node.id))
    roles = sorted(
        by_role,
        key=lambda role: (
            -_member_score(world, by_role[role][0], recent_mentions),
            role,
        ),
    )
    selected: list[WorldNode] = []
    while roles and len(selected) < limit:
        next_roles: list[str] = []
        for role in roles:
            nodes = by_role[role]
            if nodes and len(selected) < limit:
                selected.append(nodes.pop(0))
            if nodes:
                next_roles.append(role)
        roles = next_roles
    return selected


def _member_score(world: World, node: WorldNode, recent_mentions: dict[str, int]) -> float:
    pressure = sum(abs(float(item.get("weight", 0.0) or 0.0)) for item in node.rule_pressures)
    degree = sum(
        1
        for edge in world.relationships.values()
        if edge.source == node.id or edge.target == node.id
    )
    return (
        pressure * 12.0
        + recent_mentions.get(node.id, 0) * 7.0
        + min(len(node.memories), 6) * 1.5
        + min(degree, 12) * 0.35
    )


def _recent_node_mentions(world: World, limit: int = 80) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in world.events.recent(limit):
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        actor_id = str(payload.get("actor_id", ""))
        if actor_id and world.has_node(actor_id):
            counts[actor_id] = counts.get(actor_id, 0) + 1
        for target in payload.get("targets", []):
            if not isinstance(target, dict):
                continue
            node_id = str(target.get("id", ""))
            if node_id and world.has_node(node_id):
                counts[node_id] = counts.get(node_id, 0) + 1
        for raw_effect in payload.get("effects", []):
            if not isinstance(raw_effect, dict):
                continue
            for field_name in ("target", "source", "from", "to"):
                node_id = _node_ref(raw_effect.get(field_name, ""))
                if node_id and world.has_node(node_id):
                    counts[node_id] = counts.get(node_id, 0) + 1
    return counts


def _graph_trigger_reasons(
    world: World,
    organization: WorldNode,
    candidates: list[WorldNode],
    recent_mentions: dict[str, int],
) -> list[str]:
    reasons: list[str] = []
    if recent_mentions.get(organization.id, 0):
        reasons.append("recent organization feedback")
    if any(recent_mentions.get(node.id, 0) for node in candidates):
        reasons.append("recent member feedback")
    if any(node.rule_pressures for node in candidates):
        reasons.append("active structured pressure")
    if any(node.memories for node in candidates):
        reasons.append("memory continuity")
    if not reasons:
        reasons.append("scheduled graph rotation")
    return reasons


def _node_ref(value: object) -> str:
    text = str(value)
    if text.startswith("node:"):
        return text.split(":", 1)[1]
    return text


def graph_instance_metadata(value: Any) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}
