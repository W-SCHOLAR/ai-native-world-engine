"""Deterministic scheduler job factories."""

from __future__ import annotations

import json

from .commercial_lenses import commercial_lens_ids, DeterministicCommercialLensProvider
from .key_character_continuity import KeyCharacterContinuityApplier
from .pressure_grounding import rule_pressure_is_groundable
from .providers import (
    AgentProvider,
    DeterministicHighPressureResponseProvider,
    DeterministicKeyCharacterContinuityProvider,
    DeterministicRelationshipRoundProvider,
)
from .relationship_lenses import DeterministicRelationshipLensProvider, relationship_lens_ids
from .relationship_graph_instances import relationship_graph_instances
from .scheduler import AgentJob
from .world import World


LENS_TRIGGER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "organization_collaboration": ("coordination", "coordinate", "collaboration", "planning", "协作", "协调"),
    "risk_public_opinion": ("risk", "incident", "media", "trust", "public", "hospital", "风险", "舆情", "信任"),
    "resource_supply": ("resource", "supply", "capacity", "logistics", "hospital", "transfer", "资源", "供给", "物流"),
    "market_competition": ("market", "competition", "finance", "innovation", "standards", "市场", "竞争", "标准"),
    "governance_compliance": ("policy", "governance", "compliance", "ethics", "audit", "治理", "合规", "审计"),
}


def scenario_agent_jobs(
    world: World,
    rule: str = "move",
    include_static_lenses: bool = True,
    include_ai_isekai_lenses: bool = True,
    provider_override: AgentProvider | None = None,
) -> list[AgentJob]:
    scenario = str(world.attributes.get("scenario", "") or "world")
    job_prefix = "enterprise" if scenario == "enterprise_earth" else scenario.replace("_", "-")
    jobs: list[AgentJob] = []
    for index, graph in enumerate(relationship_graph_instances(world)):
        jobs.append(
            AgentJob(
                id=f"{job_prefix}-tribe-round-{index + 1}-{graph.root_node_id}",
                kind="relationship_round",
                provider=provider_override or DeterministicRelationshipRoundProvider(rule=rule),
                graph_key=graph.key,
                priority=100 - index,
                slot="tribe",
                metadata={
                    "scenario": scenario,
                    "ai_isekai_queue": "tribe",
                    **graph.to_metadata(),
                },
            )
        )
    key_applier = KeyCharacterContinuityApplier()
    key_nodes = [
        node
        for node in world.nodes.values()
        if node.type == "key_character" or node.key_character.get("agent_layer") == "key_character"
    ]
    key_nodes.sort(key=lambda node: (-float(key_applier.salience_report(world, node)["score"]), node.id))
    for index, node in enumerate(key_nodes[:5]):
        jobs.append(
            AgentJob(
                id=f"{job_prefix}-protagonist-continuity-{index + 1}-{node.id}",
                kind="key_character_continuity",
                provider=provider_override or DeterministicKeyCharacterContinuityProvider(grounded_rule=rule),
                graph_key=f"protagonist:{node.id}",
                priority=80 - index,
                slot="protagonist",
                metadata={
                    "scenario": scenario,
                    "ai_isekai_queue": "protagonist",
                    "graph_instance": True,
                    "graph_kind": "protagonist",
                    "graph_key": f"protagonist:{node.id}",
                    "target_node_id": node.id,
                    "trigger_node_ids": [node.id],
                    "coverage_node_ids": [node.id],
                    "candidate_node_ids": [node.id],
                },
            )
        )
    if include_static_lenses and scenario == "enterprise_earth":
        if include_ai_isekai_lenses:
            jobs.extend(_relationship_lens_jobs(relationship_lens_ids()))
        jobs.extend(_commercial_lens_jobs(commercial_lens_ids()))
    return jobs


def enterprise_agent_jobs(
    world: World,
    rule: str = "move",
    include_static_lenses: bool = True,
    include_ai_isekai_lenses: bool = True,
    provider_override: AgentProvider | None = None,
) -> list[AgentJob]:
    """Compatibility wrapper retaining the Enterprise-only public contract."""

    if world.attributes.get("scenario") != "enterprise_earth":
        return []
    return scenario_agent_jobs(
        world,
        rule=rule,
        include_static_lenses=include_static_lenses,
        include_ai_isekai_lenses=include_ai_isekai_lenses,
        provider_override=provider_override,
    )


def enterprise_event_triggered_lens_jobs(world: World, tick: int, limit: int = 2, feedback_limit: int = 32) -> list[AgentJob]:
    if world.attributes.get("scenario") != "enterprise_earth":
        return []
    scores = _lens_trigger_scores(world, feedback_limit)
    ranked = [
        (lens_id, data)
        for lens_id, data in scores.items()
        if int(data.get("score", 0)) > 0
    ]
    ranked.sort(key=lambda item: (-int(item[1]["score"]), item[0]))
    return _commercial_lens_jobs(
        [lens_id for lens_id, _ in ranked[: max(limit, 0)]],
        triggered=True,
        tick=tick,
        scores=scores,
    )


def enterprise_pressure_triggered_jobs(
    world: World,
    tick: int,
    limit: int = 2,
    threshold: float = 1.0,
    rule: str = "move",
    provider_override: AgentProvider | None = None,
) -> list[AgentJob]:
    if world.attributes.get("scenario") != "enterprise_earth":
        return []
    ranked = [
        item
        for item in _pressure_trigger_scores(world)
        if float(item["pressure_score"]) >= float(threshold)
    ]
    jobs: list[AgentJob] = []
    for index, item in enumerate(ranked[: max(int(limit), 0)]):
        node_id = str(item["node_id"])
        jobs.append(
            AgentJob(
                id=f"enterprise-high-pressure-{node_id}",
                kind="high_pressure_response",
                provider=provider_override or DeterministicHighPressureResponseProvider(fallback_rule=rule),
                graph_key=f"enterprise_earth.high_pressure.{node_id}",
                priority=30 - index,
                slot="any",
                metadata={
                    "scenario": "enterprise_earth",
                    "triggered": True,
                    "trigger_type": "pressure_threshold",
                    "trigger_node_ids": [node_id],
                    "trigger_score": item["pressure_score"],
                    "trigger_reasons": item["reasons"],
                },
            )
        )
    return jobs


def _commercial_lens_jobs(
    lens_ids: list[str],
    triggered: bool = False,
    tick: int = 0,
    scores: dict[str, dict[str, object]] | None = None,
) -> list[AgentJob]:
    jobs: list[AgentJob] = []
    for index, lens_id in enumerate(lens_ids):
        trigger_data = (scores or {}).get(lens_id, {})
        job_id = f"enterprise-commercial-lens-{lens_id}"
        if triggered:
            job_id = f"{job_id}-trigger-{tick}"
        jobs.append(
            AgentJob(
                id=job_id,
                kind="commercial_lens",
                provider=DeterministicCommercialLensProvider(lens_id),
                graph_key=f"enterprise_earth.commercial_lens.{lens_id}",
                priority=5 - index,
                slot="event_lens",
                metadata={
                    "scenario": "enterprise_earth",
                    "lens_id": lens_id,
                    "triggered": triggered,
                    "trigger_score": trigger_data.get("score", 0),
                    "trigger_reasons": trigger_data.get("reasons", []),
                },
            )
        )
    return jobs


def _relationship_lens_jobs(lens_ids: list[str], triggered: bool = False, tick: int = 0) -> list[AgentJob]:
    jobs: list[AgentJob] = []
    for index, lens_id in enumerate(lens_ids):
        job_id = f"enterprise-relationship-lens-{lens_id}"
        if triggered:
            job_id = f"{job_id}-trigger-{tick}"
        jobs.append(
            AgentJob(
                id=job_id,
                kind="relationship_lens",
                provider=DeterministicRelationshipLensProvider(lens_id),
                graph_key=f"enterprise_earth.relationship_lens.{lens_id}",
                priority=-index,
                slot="event_lens",
                metadata={
                    "scenario": "enterprise_earth",
                    "lens_id": lens_id,
                    "ai_isekai_relationship_lens": True,
                    "triggered": triggered,
                },
            )
        )
    return jobs


def _lens_trigger_scores(world: World, feedback_limit: int) -> dict[str, dict[str, object]]:
    scores = {lens_id: {"score": 0, "reasons": []} for lens_id in commercial_lens_ids()}
    text = _recent_event_text(world, feedback_limit)
    for lens_id, keywords in LENS_TRIGGER_KEYWORDS.items():
        lowered = text.lower()
        matched = [keyword for keyword in keywords if keyword.lower() in lowered]
        if matched:
            scores[lens_id] = {
                "score": len(matched),
                "reasons": matched[:5],
            }
    return scores


def _recent_event_text(world: World, feedback_limit: int) -> str:
    parts: list[str] = []
    for event in world.events.recent(feedback_limit):
        payload = event.get("payload", {})
        parts.append(str(event.get("source", "")))
        parts.append(str(payload.get("source", "")))
        parts.append(str(payload.get("action", "")))
        parts.append(str(payload.get("summary", "")))
        effects = payload.get("effects", [])
        if isinstance(effects, list):
            parts.append(json.dumps(effects, ensure_ascii=False))
    return " ".join(parts)


def _pressure_trigger_scores(world: World) -> list[dict[str, object]]:
    scored: list[dict[str, object]] = []
    for node in world.nodes.values():
        groundable_pressures = [
            pressure
            for pressure in node.rule_pressures
            if rule_pressure_is_groundable(world, node.id, str(pressure.get("rule", "")))
        ]
        pressure_score = sum(
            float(pressure.get("weight", 0.0) or 0.0) * max(int(pressure.get("ttl", 1) or 1), 1)
            for pressure in groundable_pressures
        )
        if pressure_score <= 0:
            continue
        scored.append(
            {
                "node_id": node.id,
                "pressure_score": round(pressure_score, 4),
                "reasons": [
                    str(pressure.get("reason") or pressure.get("rule") or "pressure")
                    for pressure in groundable_pressures[:5]
                ],
            }
        )
    scored.sort(key=lambda item: (-float(item["pressure_score"]), str(item["node_id"])))
    return scored
