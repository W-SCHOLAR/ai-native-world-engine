"""Read-only context packets for scheduled agent jobs."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Protocol

from .domain_state import WorldDomainStateInspector
from .events import json_copy
from .memory import AiCausalityTraceLedger, MemoryQuery, PressureActionTraceLedger, WorldMemoryRetriever
from .pressure import StructuredPressureView
from .relationship_round import ACTIVE_NODE_LIMIT
from .relationship_graph import RelationshipSubgraphBuilder
from .relationship_graph_instances import (
    RELATIONSHIP_COVERAGE_LIMIT,
    RELATIONSHIP_DETAILED_CANDIDATE_LIMIT,
)
from .world import World, WorldNode


JsonDict = dict[str, Any]

CONTEXT_PACKET_SCHEMA = "agent_context_packet_v1"
RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT = RELATIONSHIP_DETAILED_CANDIDATE_LIMIT
DEFAULT_COVERAGE_LIMIT = RELATIONSHIP_COVERAGE_LIMIT
GRAPH_MEMORY_LIMIT = 8
GRAPH_FEEDBACK_LIMIT = 6
RELATIONSHIP_MODEL_EDGE_LIMIT = 24
RELATIONSHIP_MODEL_EVIDENCE_LIMIT = RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
KEY_CHARACTER_MODEL_EVIDENCE_LIMIT = 10
KEY_CHARACTER_MODEL_EDGE_LIMIT = 12
DOMAIN_CARD_COLLECTION_LIMIT = 1
DOMAIN_CARD_MAPPING_LIMIT = 2
MODEL_CONTEXT_SCHEMA = "agent_model_context_v2"


class ContextPacketJob(Protocol):
    id: str
    kind: str
    metadata: JsonDict

    def to_dict(self) -> JsonDict:
        ...


class AgentContextPacketBuilder:
    def build(
        self,
        world: World,
        job: ContextPacketJob,
        feedback_limit: int = 24,
        ai_trace_limit: int = 12,
    ) -> JsonDict:
        coverage_nodes = _coverage_nodes(world, job)
        active_candidates = _active_candidates(job, coverage_nodes)
        ai_report = AiCausalityTraceLedger().build_report(world, recent_limit=ai_trace_limit)
        pressure_action_report = PressureActionTraceLedger().build_report(world)
        graph_context = RelationshipSubgraphBuilder().build(
            world,
            [node.id for node in active_candidates],
            depth=1,
            max_nodes=32,
            max_edges=96,
        ).to_dict()
        memory_context = _memory_context(world, job, active_candidates, pressure_action_report, ai_report)
        relevant_node_ids = {node.id for node in coverage_nodes}
        recent_feedback = _graph_recent_feedback(world, relevant_node_ids, GRAPH_FEEDBACK_LIMIT)
        ai_traces = [
            item
            for item in _list(ai_report.get("recent"))
            if str(_dict(item).get("node_id", "")) in relevant_node_ids
        ][-12:]
        packet = {
            "schema": CONTEXT_PACKET_SCHEMA,
            "job": job.to_dict(),
            "world": {
                "id": world.id,
                "tick": world.tick,
                "scenario": world.attributes.get("scenario", ""),
                "node_count": len(world.nodes),
                "relationship_count": len(world.relationships),
            },
            "coverage_nodes": [_node_summary(node) for node in coverage_nodes],
            "active_candidates": [_detailed_node_summary(world, node) for node in active_candidates],
            "graph_context": graph_context,
            "domain_summary": WorldDomainStateInspector().summarize_world(world).to_dict(),
            "memory_context": memory_context,
            "recent_feedback": recent_feedback or world.events.recent(min(feedback_limit, GRAPH_FEEDBACK_LIMIT)),
            "ai_traces": ai_traces,
            "pressure_action_reflections": _pressure_action_reflections(
                pressure_action_report,
                allowed_node_ids=relevant_node_ids,
            ),
            "observation_reflections": _observation_reflections(active_candidates, pressure_action_report, ai_report),
            "key_character_peers": _key_character_peer_context(world, job, active_candidates),
            "influence_context": _key_character_influence_context(world, job, active_candidates),
            "pressure_summary": StructuredPressureView().build(world)["totals"],
            "constraints": _constraints(job),
        }
        return packet

    def summary(self, packet: JsonDict) -> JsonDict:
        return {
            "schema": packet.get("schema", CONTEXT_PACKET_SCHEMA),
            "coverage_count": len(_list(packet.get("coverage_nodes"))),
            "active_candidate_count": len(_list(packet.get("active_candidates"))),
            "recent_feedback_count": len(_list(packet.get("recent_feedback"))),
            "ai_trace_count": len(_list(packet.get("ai_traces"))),
            "pressure_action_reflection_count": len(_list(packet.get("pressure_action_reflections"))),
            "observation_reflection_count": len(_list(packet.get("observation_reflections"))),
            "graph_node_count": _dict(packet.get("graph_context")).get("stats", {}).get("node_count", 0),
            "graph_edge_count": _dict(packet.get("graph_context")).get("stats", {}).get("edge_count", 0),
            "domain_covered_domains": _dict(_dict(packet.get("domain_summary")).get("domain_model_coverage")).get(
                "covered_domains",
                0,
            ),
            "memory_context_count": len(_list(packet.get("memory_context"))),
            "graph_key": str(_dict(packet.get("job")).get("graph_key", "")),
            "graph_kind": str(_dict(_dict(packet.get("job")).get("metadata")).get("graph_kind", "")),
        }


def compact_relationship_model_context(packet: JsonDict) -> JsonDict:
    """Compatibility wrapper for the relationship model-facing projection."""

    if str(_dict(packet.get("job")).get("kind", "")) != "relationship_round":
        return json_copy(packet)
    compiled, _ = compile_agent_model_context(packet)
    return compiled


def compile_agent_model_context(packet: JsonDict) -> tuple[JsonDict, JsonDict]:
    """Compile one audit packet into deterministic L0/L1/L2 model context."""

    job = _dict(packet.get("job"))
    kind = str(job.get("kind", ""))
    if kind == "relationship_round":
        return _compile_relationship_model_context(packet)
    if kind == "key_character_continuity":
        return _compile_key_character_model_context(packet)
    copied = json_copy(packet)
    return copied, _model_context_metrics(copied, candidate_count=0, duplicate_count=0)


def _compile_relationship_model_context(packet: JsonDict) -> tuple[JsonDict, JsonDict]:
    job = _dict(packet.get("job"))

    metadata = _dict(job.get("metadata"))
    active_candidates = [
        _compact_active_candidate(item)
        for item in _list(packet.get("active_candidates"))
        if isinstance(item, dict)
    ]
    active_ids = {str(item.get("id", "")) for item in active_candidates}
    root_node_id = str(metadata.get("root_node_id", ""))
    graph = _dict(packet.get("graph_context"))
    graph_edges = sorted(
        (_compact_graph_edge(item) for item in _list(graph.get("edges")) if isinstance(item, dict)),
        key=lambda item: (
            0 if str(item.get("source", "")) in active_ids or str(item.get("target", "")) in active_ids else 1,
            -abs(float(item.get("weight", 0.0) or 0.0)),
            str(item.get("source", "")),
            str(item.get("target", "")),
        ),
    )[:RELATIONSHIP_MODEL_EDGE_LIMIT]
    domain_cards = [
        card
        for item in _list(graph.get("domain_profiles"))
        if isinstance(item, dict)
        and str(item.get("node_id", "")) in active_ids | {root_node_id}
        and (card := _compact_domain_card(item))
    ]
    evidence, evidence_metrics = _canonical_model_evidence(
        packet,
        relevant_node_ids=active_ids | {root_node_id},
        limit=RELATIONSHIP_MODEL_EVIDENCE_LIMIT,
    )
    compiled = {
        "schema": MODEL_CONTEXT_SCHEMA,
        "audit_schema": packet.get("schema", CONTEXT_PACKET_SCHEMA),
        "projection": "relationship_model_context_v2",
        "job": {
            "kind": "relationship_round",
            "graph_key": str(job.get("graph_key", metadata.get("graph_key", ""))),
            "graph_kind": str(metadata.get("graph_kind", "")),
            "root_node_id": root_node_id,
        },
        "decision_context": {
            "world": _compact_world(packet.get("world")),
            "coverage_nodes": [
                {"id": str(item.get("id", ""))}
                for item in _list(packet.get("coverage_nodes"))
                if isinstance(item, dict) and str(item.get("id", ""))
            ],
            "active_candidates": active_candidates,
            "graph": {
                "edges": graph_edges,
                "stats": {
                    "available_node_count": int(_dict(graph.get("stats")).get("node_count", 0) or 0),
                    "available_edge_count": int(_dict(graph.get("stats")).get("edge_count", 0) or 0),
                    "included_edge_count": len(graph_edges),
                },
            },
            "action_options_by_node": _compact_action_options_by_node(
                _list(packet.get("groundable_action_options")),
                active_ids,
            ),
            "current_pressures_by_node": _compact_current_pressures_by_node(
                _list(packet.get("active_candidates"))
            ),
            "trigger": _compact_nonempty(
                {
                    "pressure_score": float(metadata.get("pressure_score", 0.0) or 0.0),
                    "reasons": [str(value)[:96] for value in _list(metadata.get("trigger_reasons"))[:3]],
                }
            ),
            "pressure_summary": json_copy(_dict(packet.get("pressure_summary"))),
            "constraints": json_copy(_dict(packet.get("constraints"))),
        },
        "episodic_evidence": evidence,
        "continuity_context": {
            "graph_key": str(job.get("graph_key", metadata.get("graph_key", ""))),
            "graph_kind": str(metadata.get("graph_kind", "")),
            "root_node_id": root_node_id,
            "organizations": [
                _compact_organization(item)
                for item in _list(graph.get("organizations"))[:4]
                if isinstance(item, dict)
            ],
            "domain_cards": domain_cards,
            "domain_summary": _compact_domain_summary(packet.get("domain_summary")),
        },
    }
    return compiled, _model_context_metrics(
        compiled,
        candidate_count=int(evidence_metrics["candidate_count"]),
        duplicate_count=int(evidence_metrics["duplicate_suppressed_count"]),
    )


def _compile_key_character_model_context(packet: JsonDict) -> tuple[JsonDict, JsonDict]:
    job = _dict(packet.get("job"))
    metadata = _dict(job.get("metadata"))
    target_id = str(metadata.get("target_node_id", _dict(packet.get("constraints")).get("target_node_id", "")))
    active = next(
        (
            item
            for item in _list(packet.get("active_candidates"))
            if isinstance(item, dict) and (not target_id or str(item.get("id", "")) == target_id)
        ),
        {},
    )
    if not target_id:
        target_id = str(_dict(active).get("id", ""))
    graph = _dict(packet.get("graph_context"))
    relevant_ids = {target_id} | {
        str(item.get("id", ""))
        for item in _list(packet.get("key_character_peers"))
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    evidence, evidence_metrics = _canonical_model_evidence(
        packet,
        relevant_node_ids=relevant_ids,
        limit=KEY_CHARACTER_MODEL_EVIDENCE_LIMIT,
    )
    compiled = {
        "schema": MODEL_CONTEXT_SCHEMA,
        "audit_schema": packet.get("schema", CONTEXT_PACKET_SCHEMA),
        "projection": "key_character_model_context_v2",
        "job": {
            "kind": "key_character_continuity",
            "graph_key": str(job.get("graph_key", metadata.get("graph_key", ""))),
            "target_node_id": target_id,
        },
        "decision_context": {
            "world": _compact_world(packet.get("world")),
            "target": _compact_key_character_decision_card(_dict(active)),
            "influence_nodes": [
                _compact_influence_node(item)
                for item in _list(packet.get("influence_context"))
                if isinstance(item, dict)
            ],
            "relevant_edges": [
                _compact_graph_edge(item)
                for item in _list(graph.get("edges"))[:KEY_CHARACTER_MODEL_EDGE_LIMIT]
                if isinstance(item, dict)
            ],
            "action_options_by_node": _compact_action_options_by_node(
                _list(packet.get("groundable_action_options")),
                {target_id},
            ),
            "pressure_summary": json_copy(_dict(packet.get("pressure_summary"))),
            "constraints": json_copy(_dict(packet.get("constraints"))),
        },
        "episodic_evidence": evidence,
        "continuity_context": {
            "target": _compact_target_continuity(_dict(active)),
            "peers": [
                _compact_peer_card(item, target_id)
                for item in _list(packet.get("key_character_peers"))
                if isinstance(item, dict)
            ],
            "domain_summary": _compact_domain_summary(packet.get("domain_summary")),
        },
    }
    return compiled, _model_context_metrics(
        compiled,
        candidate_count=int(evidence_metrics["candidate_count"]),
        duplicate_count=int(evidence_metrics["duplicate_suppressed_count"]),
    )


def _compact_active_candidate(item: JsonDict) -> JsonDict:
    attributes = _dict(item.get("attributes"))
    return _compact_nonempty({
        "id": str(item.get("id", "")),
        "name": str(item.get("name", "")),
        "role": str(attributes.get("role", attributes.get("identity", ""))),
        "parent_network": str(attributes.get("parent_network", "")),
        "type": str(item.get("type", "")),
        "identity": str(attributes.get("identity", "")),
        "organization_kind": str(attributes.get("organization_kind", "")),
    })


def _compact_current_pressures_by_node(items: list[Any]) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pressures = [
            {
                "rule": str(_dict(pressure).get("rule", "")),
                "weight": float(_dict(pressure).get("weight", 0.0) or 0.0),
                "ttl": int(_dict(pressure).get("ttl", 0) or 0),
                "reason": str(_dict(pressure).get("reason", ""))[:48],
                "origin": str(_dict(pressure).get("origin", "")),
                "influenced_by": str(_dict(pressure).get("influenced_by", "")),
                "initiative_id": str(_dict(pressure).get("initiative_id", "")),
                "propagation_depth": int(
                    _dict(pressure).get("propagation_depth", 0) or 0
                ),
                "propagation_goal": str(
                    _dict(pressure).get("propagation_goal", "")
                )[:120],
            }
            for pressure in _list(item.get("rule_pressures"))[-2:]
            if isinstance(pressure, dict)
        ]
        if pressures:
            rows.append({"node_id": str(item.get("id", "")), "pressures": pressures})
    return rows


def _compact_graph_edge(item: JsonDict) -> JsonDict:
    return {
        "source": str(item.get("source", "")),
        "target": str(item.get("target", "")),
        "type": str(item.get("type", "")),
        "weight": round(float(item.get("weight", 0.0) or 0.0), 4),
    }


def _compact_domain_card(item: JsonDict) -> JsonDict:
    organization = _dict(item.get("organization"))
    card: JsonDict = {
        "node_id": str(item.get("node_id", "")),
        "organization": _compact_nonempty(
            {
                "agent_layer": str(organization.get("agent_layer", "")),
                "organization_kind": str(organization.get("organization_kind", "")),
            }
        ),
    }
    for key in sorted(item):
        if key in {"node_id", "organization", "node_type", "organization_structure"}:
            continue
        value = item[key]
        if isinstance(value, list):
            recent = [
                _compact_nonempty(entry)
                for entry in value[-DOMAIN_CARD_COLLECTION_LIMIT:]
                if _compact_nonempty(entry) not in ({}, [], "", None)
            ]
            if recent:
                card[key] = recent
        elif isinstance(value, dict):
            ranked = sorted(
                value.items(),
                key=lambda pair: (
                    -abs(float(pair[1])) if isinstance(pair[1], (int, float)) else 0.0,
                    str(pair[0]),
                ),
            )[:DOMAIN_CARD_MAPPING_LIMIT]
            compact_mapping = {
                str(mapping_key): _compact_nonempty(mapping_value)
                for mapping_key, mapping_value in ranked
                if _compact_nonempty(mapping_value) not in ({}, [], "", None, 0, 0.0, False)
            }
            if compact_mapping:
                card[key] = compact_mapping
        elif value not in ({}, [], "", None, 0, 0.0, False):
            card[key] = _compact_nonempty(value)
    compact = _compact_nonempty(card)
    return compact if len(compact) > 2 else {}


def _compact_organization(item: JsonDict) -> JsonDict:
    attributes = _dict(item.get("attributes"))
    return _compact_nonempty(
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "kind": str(attributes.get("organization_kind", item.get("type", ""))),
        }
    )


def _compact_world(value: Any) -> JsonDict:
    world = _dict(value)
    return _compact_nonempty(
        {
            "id": str(world.get("id", "")),
            "scenario": str(world.get("scenario", "")),
        }
    )


def _compact_domain_summary(value: Any) -> JsonDict:
    summary = _dict(value)
    coverage = _dict(summary.get("domain_model_coverage"))
    return _compact_nonempty(
        {
            "covered_domains": int(coverage.get("covered_domains", 0) or 0),
            "by_domain": _compact_nonempty(_dict(coverage.get("by_domain"))),
            "totals": _compact_nonempty(_dict(summary.get("totals"))),
        }
    )


def _compact_key_character_decision_card(item: JsonDict) -> JsonDict:
    attributes = _dict(item.get("attributes"))
    return _compact_nonempty(
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "type": str(item.get("type", "")),
            "identity": str(attributes.get("identity", _dict(item.get("key_character")).get("identity", ""))),
            "position": _compact_nonempty(_dict(item.get("position"))),
            "current_pressures": [
                {
                    "rule": str(_dict(pressure).get("rule", "")),
                    "weight": float(_dict(pressure).get("weight", 0.0) or 0.0),
                    "ttl": int(_dict(pressure).get("ttl", 0) or 0),
                    "reason": str(_dict(pressure).get("reason", ""))[:80],
                }
                for pressure in _list(item.get("rule_pressures"))[-2:]
                if isinstance(pressure, dict)
            ],
        }
    )


def _compact_target_continuity(item: JsonDict) -> JsonDict:
    key_character = _dict(item.get("key_character"))
    attributes = _dict(item.get("attributes"))
    return _compact_nonempty(
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "identity": str(key_character.get("identity", attributes.get("identity", ""))),
            "status": str(key_character.get("status", "")),
            "self_narrative": str(key_character.get("self_narrative", ""))[:360],
            "personality_profile": _compact_nonempty(_dict(key_character.get("personality_profile"))),
            "goal_status": str(key_character.get("goal_status", "")),
            "goal": str(key_character.get("goal", ""))[:320],
            "plan_reason": str(key_character.get("plan_reason", ""))[:240],
            "plan_steps": [str(value)[:200] for value in _list(key_character.get("plan_steps"))[-4:]],
            "current_step": str(key_character.get("current_step", ""))[:240],
            "last_progress_delta": str(
                key_character.get("last_progress_delta", "")
            )[:240],
            "last_action_assessment": _compact_nonempty(
                _dict(key_character.get("last_action_assessment"))
            ),
            "previous_initiative": _compact_initiative(
                key_character.get("previous_initiative")
            ),
            "current_initiative": _compact_initiative(
                key_character.get("current_initiative")
            ),
            "initiative_generation": int(
                key_character.get("initiative_generation", 0) or 0
            ),
            "commitments": [
                _compact_lifecycle_item(value)
                for value in _list(key_character.get("commitments"))
                if isinstance(value, dict) and str(value.get("status", "pending")) != "resolved"
            ][-4:],
            "peer_interactions": [
                _compact_lifecycle_item(value)
                for value in _list(key_character.get("peer_interactions"))
                if isinstance(value, dict)
            ][-4:],
        }
    )


def _compact_peer_card(item: JsonDict, target_id: str) -> JsonDict:
    key_character = _dict(item.get("key_character"))
    attributes = _dict(item.get("attributes"))
    direct_interactions = [
        _compact_lifecycle_item(value)
        for value in _list(key_character.get("peer_interactions"))
        if isinstance(value, dict) and str(value.get("target", "")) == target_id
    ]
    direct_commitments = [
        _compact_lifecycle_item(value)
        for value in _list(key_character.get("commitments"))
        if isinstance(value, dict)
        and str(value.get("target", "")) == target_id
        and str(value.get("status", "pending")) != "resolved"
    ]
    recent_change = ""
    memories = _list(item.get("recent_memories"))
    thoughts = _list(item.get("recent_thoughts"))
    if memories:
        recent_change = str(_dict(memories[-1]).get("text", ""))[:180]
    elif thoughts:
        recent_change = str(thoughts[-1])[:180]
    return _compact_nonempty(
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "identity": str(key_character.get("identity", attributes.get("identity", ""))),
            "status": str(key_character.get("status", "")),
            "goal": str(key_character.get("goal", ""))[:160],
            "current_step": str(key_character.get("current_step", ""))[:160],
            "direct_interaction": direct_interactions[-1] if direct_interactions else {},
            "open_commitment": direct_commitments[-1] if direct_commitments else {},
            "recent_meaningful_change": recent_change,
        }
    )


def _compact_lifecycle_item(value: Any) -> JsonDict:
    item = _dict(value)
    return _compact_nonempty(
        {
            "target": str(item.get("target", "")),
            "status": str(item.get("status", "")),
            "stance": str(item.get("stance", "")),
            "summary": str(item.get("summary", ""))[:200],
            "reason": str(item.get("reason", ""))[:120],
            "created_tick": int(item.get("created_tick", 0) or 0),
        }
    )


def _compact_initiative(value: Any) -> JsonDict:
    item = _dict(value)
    return _compact_nonempty(
        {
            "initiative_id": str(item.get("initiative_id", "")),
            "generation": int(item.get("generation", 0) or 0),
            "source_tick": int(item.get("source_tick", 0) or 0),
            "action": str(item.get("action", ""))[:240],
            "target_node_ids": [
                str(node_id)
                for node_id in _list(item.get("target_node_ids"))[:5]
                if str(node_id)
            ],
            "expected_change": str(item.get("expected_change", ""))[:240],
            "propagation_goal": str(item.get("propagation_goal", ""))[:240],
            "impact_scale": round(float(item.get("impact_scale", 0.0) or 0.0), 4),
            "selected_action_option_id": str(
                item.get("selected_action_option_id", "")
            ),
        }
    )


def _compact_influence_node(item: JsonDict) -> JsonDict:
    attributes = _dict(item.get("attributes"))
    return _compact_nonempty(
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "role": str(attributes.get("role", "")),
            "parent_network": str(attributes.get("parent_network", "")),
        }
    )


def _canonical_model_evidence(
    packet: JsonDict,
    *,
    relevant_node_ids: set[str],
    limit: int,
) -> tuple[list[JsonDict], JsonDict]:
    candidates: list[JsonDict] = []
    for item in _list(packet.get("memory_context")):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id", ""))
        ranked_records = _list(item.get("ranked_records"))
        if ranked_records:
            for record in ranked_records:
                if isinstance(record, dict):
                    candidates.append(
                        _evidence_candidate(
                            node_id=node_id,
                            kind=str(record.get("kind", "memory")),
                            summary=str(record.get("text", record.get("summary", ""))),
                            tick=int(record.get("tick", 0) or 0),
                            sequence=int(record.get("sequence", 0) or 0),
                            status=str(record.get("status", "observed")),
                            source=str(record.get("source", "memory_retrieval")),
                            priority=70.0 + float(record.get("score", 0.0) or 0.0),
                        )
                    )
        else:
            candidates.append(
                _evidence_candidate(
                    node_id=node_id,
                    kind=str(item.get("kind", "memory")),
                    summary=str(item.get("text", item.get("summary", ""))),
                    tick=int(item.get("tick", 0) or 0),
                    sequence=int(item.get("sequence", 0) or 0),
                    status=str(item.get("status", "observed")),
                    source=str(item.get("source", "memory_retrieval")),
                    priority=70.0 + float(item.get("score", 0.0) or 0.0),
                )
            )
    for item in _list(packet.get("recent_feedback")):
        if not isinstance(item, dict):
            continue
        payload = _dict(item.get("payload"))
        node_id = str(payload.get("actor_id", ""))
        summary = str(payload.get("summary", payload.get("action", "")))
        candidates.append(
            _evidence_candidate(
                node_id=node_id,
                kind=str(item.get("kind", "feedback")),
                summary=summary,
                tick=int(item.get("tick", 0) or 0),
                sequence=int(item.get("sequence", 0) or 0),
                status="grounded_feedback",
                source=str(payload.get("source", "rule_engine_feedback")),
                priority=90.0,
            )
        )
    for item in _list(packet.get("pressure_action_reflections")):
        if isinstance(item, dict):
            candidates.append(_pressure_evidence_candidate(item, source="pressure_action_reflection"))
    for item in _list(packet.get("ai_traces")):
        if isinstance(item, dict):
            candidates.append(_ai_evidence_candidate(item, source="ai_causality_trace"))
    for observation in _list(packet.get("observation_reflections")):
        if not isinstance(observation, dict):
            continue
        for item in _list(observation.get("pressure_action")):
            if isinstance(item, dict):
                candidates.append(_pressure_evidence_candidate(item, source="observation_reflection"))
        for item in _list(observation.get("ai_causality")):
            if isinstance(item, dict):
                candidates.append(_ai_evidence_candidate(item, source="observation_reflection"))
    candidates = [
        item
        for item in candidates
        if item.get("summary")
        and (
            not relevant_node_ids
            or not str(item.get("node_id", ""))
            or str(item.get("node_id", "")) in relevant_node_ids
        )
    ]
    deduplicated: dict[str, JsonDict] = {}
    for candidate in candidates:
        identity = str(candidate.pop("_identity", ""))
        existing = deduplicated.get(identity)
        if existing is None:
            candidate["sources"] = [str(candidate.pop("_source", ""))]
            deduplicated[identity] = candidate
            continue
        source = str(candidate.pop("_source", ""))
        sources = _list(existing.get("sources"))
        if source and source not in sources:
            existing["sources"] = [*sources, source]
        if _evidence_sort_key(candidate) < _evidence_sort_key(existing):
            candidate["sources"] = json_copy(existing.get("sources", []))
            deduplicated[identity] = candidate
    ranked = sorted(deduplicated.values(), key=_evidence_sort_key)
    selected: list[JsonDict] = []
    selected_ids: set[str] = set()
    for node_id in sorted(relevant_node_ids):
        candidate = next((item for item in ranked if str(item.get("node_id", "")) == node_id), None)
        if candidate is not None and str(candidate.get("id", "")) not in selected_ids:
            selected.append(candidate)
            selected_ids.add(str(candidate.get("id", "")))
            if len(selected) >= limit:
                break
    for candidate in ranked:
        if len(selected) >= limit:
            break
        evidence_id = str(candidate.get("id", ""))
        if evidence_id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(evidence_id)
    visible = [
        {key: json_copy(value) for key, value in item.items() if not key.startswith("_")}
        for item in selected
    ]
    return visible, {
        "candidate_count": len(candidates),
        "selected_count": len(visible),
        "duplicate_suppressed_count": len(candidates) - len(deduplicated),
    }


def _evidence_candidate(
    *,
    node_id: str,
    kind: str,
    summary: str,
    tick: int,
    sequence: int,
    status: str,
    source: str,
    priority: float,
    causal_identity: str = "",
) -> JsonDict:
    compact_summary = " ".join(summary.split())[:220]
    semantic = _normalized_evidence_text(compact_summary)
    identity = causal_identity or f"semantic:{node_id}:{semantic}"
    evidence_id = f"ev-{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    return _compact_nonempty(
        {
            "id": evidence_id,
            "node_id": node_id,
            "kind": kind,
            "tick": max(int(tick), 0),
            "sequence": max(int(sequence), 0),
            "status": status,
            "summary": compact_summary,
            "_identity": identity,
            "_source": source,
            "_priority": round(float(priority), 4),
        }
    )


def _pressure_evidence_candidate(item: JsonDict, *, source: str) -> JsonDict:
    node_id = str(item.get("node_id", ""))
    sequence = int(item.get("sequence", 0) or 0)
    status = str(item.get("status", "")) or ("matched" if item.get("matched") else "unresolved")
    rule = str(item.get("rule", ""))
    expected = str(item.get("expected_action", ""))
    grounded = str(item.get("grounded_action", ""))
    grounded_summary = str(item.get("grounded_summary", ""))
    summary = (
        f"rule={rule}; expected={expected or 'unspecified'}; "
        f"grounded={grounded or 'none'}; outcome={grounded_summary or status}"
    )
    return _evidence_candidate(
        node_id=node_id,
        kind="pressure_outcome",
        summary=summary,
        tick=int(item.get("tick", 0) or 0),
        sequence=sequence,
        status=status,
        source=source,
        priority=130.0 if status in {"unresolved", "pending_observation", "unmatched_terminal"} else 105.0,
        causal_identity=f"pressure:{node_id}:{sequence}" if sequence else "",
    )


def _ai_evidence_candidate(item: JsonDict, *, source: str) -> JsonDict:
    pressure = _dict(item.get("pressure"))
    thought = _dict(item.get("thought"))
    action = _dict(item.get("action"))
    node_id = str(item.get("node_id", ""))
    sequence = int(pressure.get("sequence", item.get("sequence", 0)) or 0)
    status = str(item.get("status", "")) or ("matched" if item.get("matched") else "unresolved")
    rule = str(pressure.get("rule", item.get("rule", "")))
    thought_text = str(thought.get("text", item.get("thought", "")))
    grounded = str(action.get("action", item.get("grounded_action", "")))
    reason = str(pressure.get("reason", item.get("reason", "")))
    summary = (
        f"thought={thought_text or 'none'}; rule={rule or 'none'}; "
        f"reason={reason or 'none'}; grounded={grounded or 'none'}"
    )
    return _evidence_candidate(
        node_id=node_id,
        kind="ai_causality",
        summary=summary,
        tick=int(pressure.get("tick", item.get("tick", 0)) or 0),
        sequence=sequence,
        status=status,
        source=source,
        priority=125.0 if status in {"unresolved", "pending_observation", "unmatched_terminal"} else 100.0,
        causal_identity=f"ai:{node_id}:{sequence}" if sequence else "",
    )


def _normalized_evidence_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()[:240]


def _evidence_sort_key(item: JsonDict) -> tuple[float, int, int, str, str]:
    return (
        -float(item.get("_priority", 0.0) or 0.0),
        -int(item.get("tick", 0) or 0),
        -int(item.get("sequence", 0) or 0),
        str(item.get("node_id", "")),
        str(item.get("id", "")),
    )


def _model_context_metrics(
    compiled: JsonDict,
    *,
    candidate_count: int,
    duplicate_count: int,
) -> JsonDict:
    section_bytes = {
        "l0_decision": _json_size(compiled.get("decision_context")),
        "l1_evidence": _json_size(compiled.get("episodic_evidence")),
        "l2_continuity": _json_size(compiled.get("continuity_context")),
    }
    section_versions = {
        name: sha256(
            json.dumps(compiled.get(field), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        for name, field in (
            ("l0_decision", "decision_context"),
            ("l1_evidence", "episodic_evidence"),
            ("l2_continuity", "continuity_context"),
        )
    }
    selected_count = len(_list(compiled.get("episodic_evidence")))
    return {
        "schema": MODEL_CONTEXT_SCHEMA,
        "projection": str(compiled.get("projection", "")),
        "model_context_bytes": _json_size(compiled),
        "section_bytes": section_bytes,
        "section_versions": section_versions,
        "evidence_candidate_count": max(int(candidate_count), 0),
        "evidence_selected_count": selected_count,
        "evidence_duplicate_suppressed_count": max(int(duplicate_count), 0),
    }


def _json_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _compact_action_options_by_node(
    raw_options: list[Any],
    active_node_ids: set[str],
) -> list[JsonDict]:
    """Expose only the identifiers the model needs to make a choice.

    The full action payload remains in the engine/audit context and is used by
    the Provider boundary when the selected option is materialized. Sending
    resolved parameters to the model duplicates authoritative state and makes
    relationship requests needlessly large.
    """

    grouped: dict[str, list[JsonDict]] = {}
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            continue
        node_id = str(raw_option.get("node_id", ""))
        option_id = str(raw_option.get("option_id", ""))
        if not node_id or node_id not in active_node_ids or not option_id:
            continue
        option = {
            "option_id": option_id,
            "rule": str(raw_option.get("rule", "")),
        }
        target_id = str(raw_option.get("target_id", ""))
        if target_id:
            option["target"] = target_id
        grouped.setdefault(node_id, []).append(option)
    return [
        {"node_id": node_id, "options": grouped[node_id]}
        for node_id in sorted(grouped)
    ]


def _compact_nonempty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): compact
            for key, item in value.items()
            if (compact := _compact_nonempty(item)) not in ({}, [], "", None, 0, 0.0, False)
        }
    if isinstance(value, list):
        return [compact for item in value if (compact := _compact_nonempty(item)) not in ({}, [], "", None)]
    if isinstance(value, str):
        return value[:240]
    return json_copy(value)


def _coverage_nodes(world: World, job: ContextPacketJob) -> list[WorldNode]:
    coverage_node_ids = [
        str(node_id)
        for node_id in _list(job.metadata.get("coverage_node_ids"))
        if world.has_node(str(node_id))
    ]
    if coverage_node_ids:
        return [world.node(node_id) for node_id in coverage_node_ids[:DEFAULT_COVERAGE_LIMIT]]
    trigger_node_ids = [
        str(node_id)
        for node_id in _list(job.metadata.get("trigger_node_ids"))
        if world.has_node(str(node_id))
    ]
    if trigger_node_ids:
        return [world.node(node_id) for node_id in trigger_node_ids]
    if job.kind == "relationship_round":
        return _sorted_nodes(
            node
            for node in world.nodes.values()
            if node.attributes.get("agent_layer") == "relationship_network_member"
        )[:DEFAULT_COVERAGE_LIMIT]
    if job.kind == "key_character_continuity":
        return _sorted_nodes(
            node
            for node in world.nodes.values()
            if node.type == "key_character" or node.key_character.get("agent_layer") == "key_character"
        )
    if job.kind in {"commercial_lens", "relationship_lens"}:
        lens_id = str(job.metadata.get("lens_id", ""))
        return _commercial_lens_nodes(world, lens_id)[:DEFAULT_COVERAGE_LIMIT]
    return _sorted_nodes(world.nodes.values())[:DEFAULT_COVERAGE_LIMIT]


def _active_candidates(job: ContextPacketJob, coverage_nodes: list[WorldNode]) -> list[WorldNode]:
    candidate_node_ids = [str(node_id) for node_id in _list(job.metadata.get("candidate_node_ids"))]
    if candidate_node_ids:
        by_id = {node.id: node for node in coverage_nodes}
        return [by_id[node_id] for node_id in candidate_node_ids if node_id in by_id]
    if job.kind == "relationship_round":
        return coverage_nodes[:RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT]
    if job.kind == "key_character_continuity":
        return coverage_nodes[:5]
    if job.kind in {"commercial_lens", "relationship_lens"}:
        return coverage_nodes[:12]
    return coverage_nodes[:12]


def _commercial_lens_nodes(world: World, lens_id: str) -> list[WorldNode]:
    keywords = {
        "organization_collaboration": ("coordination", "operations", "planning"),
        "risk_public_opinion": ("communications", "security", "analysis"),
        "resource_supply": ("logistics", "supply", "field", "operations"),
        "market_competition": ("research", "data", "finance", "standards"),
        "governance_compliance": ("policy", "ethics", "standards", "security"),
    }.get(lens_id, ())
    nodes = [
        node
        for node in world.nodes.values()
        if node.attributes.get("agent_layer") == "relationship_network_member"
        and any(keyword in str(node.attributes.get("role", "")).lower() for keyword in keywords)
    ]
    if nodes:
        return _sorted_nodes(nodes)
    return _sorted_nodes(
        node
        for node in world.nodes.values()
        if node.attributes.get("agent_layer") == "relationship_network_member"
    )


def _node_summary(node: WorldNode) -> JsonDict:
    return {
        "id": node.id,
        "type": node.type,
        "name": node.name,
        "attributes": json_copy(
            {
                key: value
                for key, value in node.attributes.items()
                if key in {"agent_layer", "parent_network", "role", "identity", "organization_kind"}
            }
        ),
        "memory_count": len(node.memories),
        "rule_pressure_count": len(node.rule_pressures),
        "key_character": json_copy(
            {
                key: value
                for key, value in node.key_character.items()
                if key
                in {
                    "status",
                    "identity",
                    "agent_layer",
                    "self_narrative",
                    "personality_profile",
                    "goal_status",
                    "goal",
                    "plan_reason",
                    "plan_steps",
                    "current_step",
                    "last_progress_delta",
                    "last_action_assessment",
                    "previous_initiative",
                    "current_initiative",
                    "initiative_generation",
                    "initiative_changed",
                    "progress_changed",
                    "peer_interactions",
                    "commitments",
                    "salience_score",
                }
            }
        ),
    }


def _detailed_node_summary(world: World, node: WorldNode) -> JsonDict:
    summary = _node_summary(node)
    summary.update(
        {
            "position": node.position.to_dict(),
            "recent_memories": [
                {
                    "text": str(item.get("text", item.get("summary", "")))[:240],
                    "source": str(item.get("source", "")),
                    "importance": float(item.get("importance", 0.0) or 0.0),
                }
                for item in node.memories[-2:]
                if isinstance(item, dict)
            ],
            "rule_pressures": json_copy(node.rule_pressures[-3:]),
            "relationship_degree": sum(
                1
                for edge in world.relationships.values()
                if edge.source == node.id or edge.target == node.id
            ),
        }
    )
    return summary


def _constraints(job: ContextPacketJob) -> JsonDict:
    base = {
        "provider_must_not_directly_mutate_world": True,
        "output_must_be_structured_pressure": True,
    }
    if job.kind == "relationship_round":
        base.update(
            {
                "active_candidate_limit": RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT,
                "coverage_node_limit": DEFAULT_COVERAGE_LIMIT,
                "active_node_limit": ACTIVE_NODE_LIMIT,
                "required_active_node_count": ACTIVE_NODE_LIMIT,
                "thought_slice_count": 6,
                "ripple_targets_per_active": 3,
                "graph_key": str(job.metadata.get("graph_key", "")),
                "graph_kind": str(job.metadata.get("graph_kind", "")),
                "root_node_id": str(job.metadata.get("root_node_id", "")),
            }
        )
    if job.kind == "key_character_continuity":
        base.update(
            {
                "target_node_id": str(job.metadata.get("target_node_id", "")),
                "one_character_per_call": True,
            }
        )
    if job.kind == "commercial_lens":
        base.update({"lens_id": job.metadata.get("lens_id", ""), "origin": "commercial_relationship_lens"})
    if job.kind == "relationship_lens":
        base.update({"lens_id": job.metadata.get("lens_id", ""), "origin": "ai_isekai_relationship_lens"})
    return base


def _memory_context(
    world: World,
    job: ContextPacketJob,
    active_candidates: list[WorldNode],
    pressure_action_report: JsonDict,
    ai_report: JsonDict,
) -> list[JsonDict]:
    if job.kind == "relationship_round":
        return _graph_memory_context(
            world,
            job,
            active_candidates,
            pressure_action_report,
            ai_report,
            GRAPH_MEMORY_LIMIT,
        )
    return _node_memory_context(world, job, active_candidates, pressure_action_report, ai_report)


def _node_memory_context(
    world: World,
    job: ContextPacketJob,
    active_candidates: list[WorldNode],
    pressure_action_report: JsonDict,
    ai_report: JsonDict,
) -> list[JsonDict]:
    retriever = WorldMemoryRetriever()
    query_text = _memory_query_text(job)
    contexts: list[JsonDict] = []
    for node in active_candidates[:12]:
        result = retriever.retrieve(world, MemoryQuery(node.id, limit=4, text=query_text)).to_dict()
        contexts.append(
            {
                "node_id": node.id,
                "query": query_text,
                "ranked_records": result["ranked_records"][:4],
                "relationship_count": len(_list(result["relationships"])),
                "pressure_count": len(_list(result["pressures"])),
                "recent_feedback_count": len(_list(result["recent_feedback"])),
                "trace_count": len(_list(result["traces"])),
                "pressure_action_reflections": _node_pressure_action_reflections(node.id, pressure_action_report, limit=3),
                "ai_causality_reflections": _node_ai_causality_reflections(node.id, ai_report, limit=3),
            }
        )
    return contexts


def _graph_memory_context(
    world: World,
    job: ContextPacketJob,
    active_candidates: list[WorldNode],
    pressure_action_report: JsonDict,
    ai_report: JsonDict,
    limit: int,
) -> list[JsonDict]:
    retriever = WorldMemoryRetriever()
    query_text = _memory_query_text(job)
    records: list[JsonDict] = []
    for node in active_candidates:
        result = retriever.retrieve(world, MemoryQuery(node.id, limit=4, text=query_text)).to_dict()
        for item in _list(result.get("ranked_records")):
            record = _dict(item)
            records.append(
                {
                    "node_id": node.id,
                    "kind": str(record.get("kind", "memory")),
                    "text": str(record.get("text", ""))[:320],
                    "score": 100.0 + float(record.get("score", 0.0) or 0.0),
                }
            )
        for item in node.memories[-2:]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", item.get("summary", ""))).strip()
            if text:
                records.append(
                    {
                        "node_id": node.id,
                        "kind": "memory",
                        "text": text[:320],
                        "score": 90.0 + float(item.get("importance", 0.0) or 0.0),
                    }
                )
        for item in node.rule_pressures[-2:]:
            records.append(
                {
                    "node_id": node.id,
                    "kind": "pressure",
                    "text": f"{item.get('rule', '')}: {item.get('reason', '')}"[:320],
                    "score": 92.0 + abs(float(item.get("weight", 0.0) or 0.0)),
                }
            )
        for item in _node_ai_causality_reflections(node.id, ai_report, limit=2):
            records.append(
                {
                    "node_id": node.id,
                    "kind": "causality_reflection",
                    "text": (
                        f"thought={item.get('thought', '')}; rule={item.get('rule', '')}; "
                        f"grounded={item.get('grounded_action', '') or 'none'}"
                    )[:320],
                    "score": 88.0 + (4.0 if not item.get("matched") else 0.0),
                }
            )
        for item in _node_pressure_action_reflections(node.id, pressure_action_report, limit=2):
            records.append(
                {
                    "node_id": node.id,
                    "kind": "pressure_action_reflection",
                    "text": (
                        f"rule={item.get('rule', '')}; grounded={item.get('grounded_action', '') or 'none'}; "
                        f"summary={item.get('grounded_summary', '')}"
                    )[:320],
                    "score": 86.0 + (4.0 if not item.get("matched") else 0.0),
                }
            )
    deduplicated: dict[tuple[str, str, str], JsonDict] = {}
    for record in records:
        key = (str(record.get("node_id", "")), str(record.get("kind", "")), str(record.get("text", "")))
        existing = deduplicated.get(key)
        if existing is None or float(record.get("score", 0.0)) > float(existing.get("score", 0.0)):
            deduplicated[key] = record
    ranked = sorted(
        deduplicated.values(),
        key=lambda item: (-float(item.get("score", 0.0)), str(item.get("node_id", "")), str(item.get("kind", ""))),
    )
    return json_copy(ranked[: max(int(limit), 0)])


def _pressure_action_reflections(
    report: JsonDict,
    limit: int = 12,
    allowed_node_ids: set[str] | None = None,
) -> list[JsonDict]:
    reflections: list[JsonDict] = []
    for item in _list(_dict(report).get("recent"))[-max(int(limit), 0) :]:
        row = _pressure_action_row(item)
        if row and (allowed_node_ids is None or str(row.get("node_id", "")) in allowed_node_ids):
            reflections.append(row)
    return reflections


def _observation_reflections(
    active_candidates: list[WorldNode],
    pressure_action_report: JsonDict,
    ai_report: JsonDict,
    limit_per_node: int = 3,
) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for node in active_candidates[:12]:
        rows.append(
            {
                "node_id": node.id,
                "pressure_action": _node_pressure_action_reflections(node.id, pressure_action_report, limit_per_node),
                "ai_causality": _node_ai_causality_reflections(node.id, ai_report, limit_per_node),
            }
        )
    return rows


def _node_pressure_action_reflections(node_id: str, report: JsonDict, limit: int = 3) -> list[JsonDict]:
    rows = [
        row
        for row in (_pressure_action_row(item) for item in _list(_dict(report).get("recent")))
        if row and row.get("node_id") == node_id
    ]
    return rows[-max(int(limit), 0) :]


def _node_ai_causality_reflections(node_id: str, report: JsonDict, limit: int = 3) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for item in _list(_dict(report).get("recent")):
        trace = _dict(item)
        if str(trace.get("node_id", "")) != node_id:
            continue
        pressure = _dict(trace.get("pressure"))
        thought = _dict(trace.get("thought"))
        action = _dict(trace.get("action"))
        rows.append(
            {
                "node_id": node_id,
                "matched": bool(trace.get("matched", False)),
                "latency_ticks": int(trace.get("latency_ticks", 0) or 0),
                "thought": str(thought.get("text", ""))[:160],
                "rule": str(pressure.get("rule", "")),
                "reason": str(pressure.get("reason", ""))[:160],
                "grounded_action": str(action.get("action", "")),
                "grounded_summary": str(action.get("summary", ""))[:160],
            }
        )
    return rows[-max(int(limit), 0) :]


def _pressure_action_row(item: Any) -> JsonDict:
    pressure = _dict(item)
    if not pressure:
        return {}
    action = _dict(pressure.get("action"))
    return {
        "node_id": str(pressure.get("node_id", "")),
        "tick": int(pressure.get("tick", 0) or 0),
        "sequence": int(pressure.get("sequence", 0) or 0),
        "rule": str(pressure.get("rule", "")),
        "source": str(pressure.get("source", "")),
        "matched": bool(pressure.get("matched", False)),
        "expected_action": str(pressure.get("expected_action", "")),
        "grounded_action": str(action.get("action", "")),
        "grounded_summary": str(action.get("summary", ""))[:160],
    }


def _memory_query_text(job: ContextPacketJob) -> str:
    parts = [
        job.kind,
        str(job.metadata.get("graph_key", "")),
        str(job.metadata.get("graph_kind", "")),
        str(job.metadata.get("root_node_id", "")),
        str(job.metadata.get("lens_id", "")),
        str(job.metadata.get("trigger_reasons", "")),
    ]
    return " ".join(part for part in parts if part).strip()


def _key_character_peer_context(
    world: World,
    job: ContextPacketJob,
    active_candidates: list[WorldNode],
) -> list[JsonDict]:
    if job.kind != "key_character_continuity":
        return []
    target_ids = {node.id for node in active_candidates}
    peers = [
        node
        for node in world.nodes.values()
        if node.id not in target_ids
        and (node.type == "key_character" or node.key_character.get("agent_layer") == "key_character")
    ]
    peers.sort(key=lambda node: node.id)
    return [_detailed_node_summary(world, node) for node in peers[:4]]


def _key_character_influence_context(
    world: World,
    job: ContextPacketJob,
    active_candidates: list[WorldNode],
) -> list[JsonDict]:
    if job.kind != "key_character_continuity" or not active_candidates:
        return []
    target = active_candidates[0]
    members = [
        node
        for node in world.nodes.values()
        if node.attributes.get("agent_layer") == "relationship_network_member"
    ]
    members.sort(
        key=lambda node: (
            (node.position.x - target.position.x) ** 2 + (node.position.y - target.position.y) ** 2,
            node.id,
        )
    )
    return [_node_summary(node) for node in members[:8]]


def _graph_recent_feedback(world: World, node_ids: set[str], limit: int) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for event in world.events.recent(80):
        payload = _dict(event.get("payload"))
        if str(payload.get("source", "")) == "ai_inference":
            continue
        if str(payload.get("actor_id", "")) in node_ids or _event_mentions_any_node(payload, node_ids):
            rows.append(json_copy(event))
    return rows[-max(int(limit), 0) :]


def _event_mentions_any_node(payload: JsonDict, node_ids: set[str]) -> bool:
    for target in _list(payload.get("targets")):
        if isinstance(target, dict) and str(target.get("id", "")) in node_ids:
            return True
    for raw_effect in _list(payload.get("effects")):
        if not isinstance(raw_effect, dict):
            continue
        for field_name in ("target", "source", "from", "to"):
            if _node_ref(raw_effect.get(field_name, "")) in node_ids:
                return True
    return False


def _node_ref(value: Any) -> str:
    text = str(value)
    if text.startswith("node:"):
        return text.split(":", 1)[1]
    return text


def _sorted_nodes(nodes: Any) -> list[WorldNode]:
    return sorted(list(nodes), key=lambda node: node.id)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}
