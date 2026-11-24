"""Projection helpers for Web earth viewer data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .domain_state import WorldDomainStateInspector
from .events import json_copy
from .thought_presentation import split_thought_for_presentation


JsonDict = dict[str, Any]


@dataclass(slots=True)
class ViewerProjection:
    summary: JsonDict = field(default_factory=dict)
    organizations: list[JsonDict] = field(default_factory=list)
    characters: list[JsonDict] = field(default_factory=list)
    people: list[JsonDict] = field(default_factory=list)
    relationships: list[JsonDict] = field(default_factory=list)
    thoughts: list[JsonDict] = field(default_factory=list)
    actions: list[JsonDict] = field(default_factory=list)
    speech_bubbles: list[JsonDict] = field(default_factory=list)
    grounded_actions: list[JsonDict] = field(default_factory=list)
    action_visuals: list[JsonDict] = field(default_factory=list)
    current_actions: list[JsonDict] = field(default_factory=list)
    impact_ripples: list[JsonDict] = field(default_factory=list)
    key_character_trajectories: list[JsonDict] = field(default_factory=list)
    ai_traces: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "summary": json_copy(self.summary),
            "organizations": json_copy(self.organizations),
            "characters": json_copy(self.characters),
            "people": json_copy(self.people),
            "relationships": json_copy(self.relationships),
            "thoughts": json_copy(self.thoughts),
            "actions": json_copy(self.actions),
            "speech_bubbles": json_copy(self.speech_bubbles),
            "grounded_actions": json_copy(self.grounded_actions),
            "action_visuals": json_copy(self.action_visuals),
            "current_actions": json_copy(self.current_actions),
            "impact_ripples": json_copy(self.impact_ripples),
            "key_character_trajectories": json_copy(self.key_character_trajectories),
            "ai_traces": json_copy(self.ai_traces),
        }


def project_run_for_viewer(result: Any) -> ViewerProjection:
    data = result.to_dict() if hasattr(result, "to_dict") else json_copy(result)
    if not isinstance(data, dict):
        raise TypeError("project_run_for_viewer expects a RunResult or JSON-compatible dict")

    snapshot = _dict(data.get("snapshot"))
    world_attributes = _dict(snapshot.get("attributes"))
    nodes = [_dict(node) for node in _list(snapshot.get("nodes"))]
    relationships = [_dict(edge) for edge in _list(snapshot.get("relationships"))]
    bounds = _bounds(nodes)
    nodes_by_id = {str(node.get("id")): node for node in nodes}
    member_map = _organization_members(relationships, nodes_by_id)
    domain_summary = _domain_summary(snapshot)
    scorecard = _dict(data.get("scorecard"))
    scorecard_metrics = _dict(scorecard.get("metrics"))
    thoughts, actions, speech_bubbles = _display_payloads(
        _list(data.get("events")),
        nodes_by_id,
        bounds,
        current_tick=int(snapshot.get("tick", 0) or 0),
    )
    display_node_ids = {
        str(item.get("node_id", "")) for item in [*thoughts, *actions]
    }
    include_tribe_members = world_attributes.get("scenario") == "tribe_survival"
    visible_node_ids = {
        str(node.get("id", ""))
        for node in nodes
        if _is_viewer_visible_node(node, display_node_ids, include_tribe_members)
    }

    organizations: list[JsonDict] = []
    characters: list[JsonDict] = []
    people: list[JsonDict] = []
    for node in nodes:
        projected = _project_node(node, bounds)
        if _is_relationship_network(node):
            projected["members"] = [
                _project_node(nodes_by_id[member_id], bounds)
                for member_id in member_map.get(str(node.get("id")), [])
                if member_id in nodes_by_id
                and member_id in visible_node_ids
                and _dict(nodes_by_id[member_id].get("attributes")).get("parent_network") == node.get("id")
                and _dict(nodes_by_id[member_id].get("attributes")).get("agent_layer") == "relationship_network_member"
            ]
            organizations.append(projected)
        elif _is_key_character(node):
            characters.append(projected)
        elif _is_people_node(node) and str(node.get("id", "")) in visible_node_ids:
            people.append(projected)

    event_rows = _list(data.get("events"))
    trace_rows = _list(data.get("traces"))
    all_grounded_actions = _grounded_actions(
        event_rows, nodes_by_id, bounds, trace_rows, limit=None
    )
    grounded_actions = all_grounded_actions[-80:]
    action_visuals = _action_visuals(all_grounded_actions)
    current_actions = _current_actions(
        action_visuals,
        active_actions=_list(snapshot.get("active_actions")),
        action_history=_list(snapshot.get("action_history")),
        nodes_by_id=nodes_by_id,
        bounds=bounds,
    )
    impact_ripples = _impact_ripples(_dict(data.get("social_ripples")), nodes_by_id, bounds)
    key_character_trajectories = _key_character_trajectories(nodes, _list(data.get("events")), bounds)
    projection = ViewerProjection(
        summary={
            "world_id": snapshot.get("id", ""),
            "tick": snapshot.get("tick", 0),
            "scenario": world_attributes.get("scenario", ""),
            "viewer_scene": world_attributes.get("viewer_scene", ""),
            "scene_title": world_attributes.get("scene_title", world_attributes.get("viewer_title", "")),
            "viewer_title": world_attributes.get("viewer_title", world_attributes.get("scene_title", "")),
            "sovereign_scope": json_copy(_dict(world_attributes.get("sovereign_scope"))),
            "survival_loops": json_copy(_list(world_attributes.get("survival_loops"))),
            "node_count": len(nodes),
            "relationship_count": len(relationships),
            "score": scorecard.get("score", 0.0),
            "domain_summary": domain_summary,
            "domain_risk": _dict(domain_summary.get("risk")),
            "grounded_action_summary": _grounded_action_summary(scorecard_metrics),
            "run_health": _run_health_summary(scorecard),
            "governance_notice": _governance_notice(snapshot, domain_summary),
            "memory_maintenance": _memory_maintenance_summary(scorecard_metrics, _list(data.get("memory_consolidation_report"))),
        },
        organizations=organizations,
        characters=characters,
        people=people,
        relationships=[
            _project_relationship(edge)
            for edge in relationships
            if str(edge.get("source", "")) in visible_node_ids
            and str(edge.get("target", "")) in visible_node_ids
        ],
        thoughts=thoughts,
        actions=actions,
        speech_bubbles=speech_bubbles,
        grounded_actions=grounded_actions,
        action_visuals=action_visuals,
        current_actions=current_actions,
        impact_ripples=impact_ripples,
        key_character_trajectories=key_character_trajectories,
        ai_traces=json_copy(_dict(data.get("ai_causality_report")).get("recent", [])),
    )
    return projection


def _domain_summary(snapshot: JsonDict) -> JsonDict:
    try:
        return WorldDomainStateInspector().summarize_snapshot(snapshot).to_dict()
    except Exception:  # noqa: BLE001 - projection should remain available for partial snapshots.
        return {"node_count": 0, "risk": {"score": 0, "level": "low"}}


def _grounded_action_summary(metrics: JsonDict) -> JsonDict:
    return {
        "counts_by_type": json_copy(_dict(metrics.get("action_counts_by_type"))),
        "grounded_action_class_count": int(metrics.get("grounded_action_class_count", 0) or 0),
        "world_ecosystem_action_coverage": float(metrics.get("world_ecosystem_action_coverage", 0.0) or 0.0),
        "world_ecosystem_actions_hit": json_copy(_list(metrics.get("world_ecosystem_actions_hit"))),
        "world_ecosystem_actions_missing": json_copy(_list(metrics.get("world_ecosystem_actions_missing"))),
    }


def _run_health_summary(scorecard: JsonDict) -> JsonDict:
    metrics = _dict(scorecard.get("metrics"))
    return {
        "score": float(scorecard.get("score", 0.0) or 0.0),
        "penalty_count": len(_list(scorecard.get("penalties"))),
        "world_errors": int(metrics.get("world_errors", 0) or 0),
        "governance_rejections": int(metrics.get("provider_governance_rejections", 0) or 0),
        "domain_state_issues": int(metrics.get("domain_state_issues", 0) or 0),
        "unmatched_pressures": int(metrics.get("unmatched_pressures", 0) or 0),
        "missing_required_actions": json_copy(_list(metrics.get("missing_required_actions"))),
    }


def _governance_notice(snapshot: JsonDict, domain_summary: JsonDict) -> JsonDict:
    attributes = _dict(snapshot.get("attributes"))
    risk = _dict(domain_summary.get("risk"))
    return {
        "label": "场景模拟",
        "scenario": str(attributes.get("scenario", "") or ""),
        "message": "此运行是场景模拟和假设推演，不是对现实世界的确定性预测。",
        "risk_level": str(risk.get("level", "low") or "low"),
    }


def _memory_maintenance_summary(metrics: JsonDict, report: list[Any], limit: int = 3) -> JsonDict:
    rows: list[JsonDict] = []
    for item in report:
        row = _memory_maintenance_row(item)
        if row:
            rows.append(row)
    fallback_summary_count = sum(1 for item in rows if item.get("kind") == "memory_summary")
    fallback_forgotten_count = sum(int(item.get("forgotten_count", 0) or 0) for item in rows)
    return {
        "consolidated_nodes": int(metrics.get("memory_consolidated_nodes", len(rows)) or 0),
        "summary_count": int(metrics.get("memory_summary_count", fallback_summary_count) or 0),
        "forgotten_count": int(metrics.get("memory_forgotten_count", fallback_forgotten_count) or 0),
        "recent": json_copy(rows[-max(int(limit), 0) :]),
    }


def _memory_maintenance_row(item: Any) -> JsonDict:
    data = _dict(item)
    summary = _dict(data.get("summary"))
    if not summary:
        return {}
    return {
        "node_id": str(data.get("node_id", summary.get("node_id", "")) or ""),
        "tick": data.get("tick", summary.get("tick", "")),
        "kind": str(summary.get("kind", "memory_summary") or "memory_summary"),
        "text": _short_text(summary.get("summary") or summary.get("text") or "", limit=96),
        "memory_count": int(summary.get("memory_count", 0) or 0),
        "forgotten_count": int(summary.get("forgotten_count", 0) or 0),
        "tick_start": summary.get("tick_start", ""),
        "tick_end": summary.get("tick_end", ""),
        "keywords": json_copy(_list(summary.get("keywords"))[:5]),
    }


def _project_node(node: JsonDict, bounds: JsonDict) -> JsonDict:
    attributes = _dict(node.get("attributes"))
    position = _dict(node.get("position"))
    key_character = _dict(node.get("key_character"))
    projected_attributes = json_copy(attributes)
    memory_highlights = _memory_highlights(_list(node.get("memories")))
    if memory_highlights:
        projected_attributes["_memory_count"] = len(_list(node.get("memories")))
        projected_attributes["_memory_highlights"] = memory_highlights
    return {
        "id": node.get("id", ""),
        "type": node.get("type", ""),
        "name": node.get("name", ""),
        "role": attributes.get("identity") or attributes.get("role") or attributes.get("organization_kind") or node.get("type", ""),
        "x": _normalize(float(position.get("x", 0.0) or 0.0), bounds["min_x"], bounds["max_x"]),
        "y": _normalize(float(position.get("y", 0.0) or 0.0), bounds["min_y"], bounds["max_y"]),
        "attributes": projected_attributes,
        "key_character": json_copy(key_character),
        "privacy": attributes.get("privacy", ""),
        "synthetic": attributes.get("synthetic", False),
    }


def _memory_highlights(memories: list[Any], limit: int = 3) -> list[JsonDict]:
    highlights: list[JsonDict] = []
    for raw_memory in sorted(
        (_dict(memory) for memory in memories),
        key=lambda memory: (
            float(memory.get("importance", 0.0) or 0.0),
            int(memory.get("tick", 0) or 0),
            str(memory.get("text") or memory.get("summary") or ""),
        ),
        reverse=True,
    )[: max(int(limit), 0)]:
        text = raw_memory.get("text") or raw_memory.get("summary") or raw_memory.get("kind") or ""
        item: JsonDict = {
            "kind": str(raw_memory.get("kind", "memory")),
            "text": _short_text(text, limit=72),
            "source": str(raw_memory.get("source", "")),
            "tick": raw_memory.get("tick", ""),
        }
        if isinstance(raw_memory.get("importance"), (int, float)):
            item["importance"] = raw_memory.get("importance")
        if isinstance(raw_memory.get("memory_count"), (int, float)):
            item["memory_count"] = raw_memory.get("memory_count")
        highlights.append(item)
    return highlights


def _display_payloads(
    events: list[Any],
    nodes_by_id: dict[str, JsonDict],
    bounds: JsonDict,
    current_tick: int | None = None,
) -> tuple[list[JsonDict], list[JsonDict], list[JsonDict]]:
    thoughts: list[JsonDict] = []
    actions: list[JsonDict] = []
    speech_bubbles: list[JsonDict] = []
    for event in events:
        event_data = _dict(event)
        payload = _dict(event_data.get("payload"))
        payload_type = payload.get("type")
        if payload_type == "thought_schedule":
            thoughts.extend(
                _expand_thought_schedule(
                    event_data,
                    payload,
                    nodes_by_id,
                    bounds,
                    None,
                )
            )
            continue
        if payload_type not in {
            "thought_bubble",
            "action_bullet",
            "speech_bubble",
        }:
            continue
        if current_tick is not None and _display_payload_finished(
            event_data, payload, current_tick
        ):
            continue
        node_id = str(payload.get("node_id", ""))
        item = json_copy(payload)
        item.pop("type", None)
        item["node_id"] = node_id
        item["sequence"] = int(event_data.get("sequence", 0) or 0)
        item.setdefault("text", "")
        item.setdefault("source", event_data.get("source", ""))
        item["tick"] = event_data.get("tick", 0)
        item.setdefault("salience", 0.5)
        if node_id in nodes_by_id:
            projected = _project_node(nodes_by_id[node_id], bounds)
            item["x"] = projected["x"]
            item["y"] = projected["y"]
        if payload_type == "thought_bubble":
            thoughts.append(item)
        elif payload_type == "action_bullet":
            actions.append(item)
        elif payload_type == "speech_bubble":
            speech_bubbles.append(item)
    return thoughts, actions, speech_bubbles


def _expand_thought_schedule(
    event: JsonDict,
    payload: JsonDict,
    nodes_by_id: dict[str, JsonDict],
    bounds: JsonDict,
    current_tick: int | None,
) -> list[JsonDict]:
    """Expand one durable schedule into ephemeral Viewer bubble slices."""

    explicit_occurrences = [
        _dict(item) for item in _list(payload.get("occurrences")) if _dict(item)
    ]
    if explicit_occurrences:
        rows = []
        for index, occurrence in enumerate(explicit_occurrences):
            row = _schedule_bubble(
                event,
                payload,
                nodes_by_id,
                bounds,
                node_id=str(
                    occurrence.get("node_id", payload.get("node_id", ""))
                ),
                text=str(occurrence.get("text", "")),
                delay=max(float(occurrence.get("delay", 0.0) or 0.0), 0.0),
                ttl=max(
                    float(occurrence.get("duration", payload.get("ttl", 4.0)) or 4.0),
                    0.0,
                ),
                derived_index=index,
                sequence_index=int(occurrence.get("slice_index", index) or 0),
                sequence_total=len(explicit_occurrences),
                origin=str(
                    occurrence.get("origin", payload.get("origin", "active_node"))
                ),
                current_tick=current_tick,
            )
            if row:
                row["occurrence_id"] = str(
                    occurrence.get("occurrence_id", "")
                )
                row["generation"] = int(payload.get("generation", 0) or 0)
                row["cognition_id"] = str(payload.get("cognition_id", ""))
                row["ripple_from"] = str(
                    occurrence.get("ripple_from", payload.get("ripple_from", ""))
                )
                rows.append(row)
        return rows

    slice_count = max(int(payload.get("slice_count", 6) or 6), 1)
    explicit = [
        str(item).strip()
        for item in _list(payload.get("explicit_slices"))
        if str(item).strip()
    ]
    slices = explicit if len(explicit) == slice_count else _split_schedule_text(
        str(payload.get("text", "保持观察。")), slice_count
    )
    base_delay = max(float(payload.get("delay", 0.0) or 0.0), 0.0)
    interval = max(float(payload.get("interval", 8.0) or 8.0), 0.0)
    ttl = max(float(payload.get("ttl", 4.0) or 4.0), 0.0)
    rows: list[JsonDict] = []
    for index, text in enumerate(slices):
        rows.append(
            _schedule_bubble(
                event,
                payload,
                nodes_by_id,
                bounds,
                node_id=str(payload.get("node_id", "")),
                text=text,
                delay=base_delay + index * interval,
                ttl=ttl,
                derived_index=index,
                sequence_index=index,
                sequence_total=slice_count,
                origin="active_node",
                current_tick=current_tick,
            )
        )
    return [row for row in rows if row]


def _schedule_bubble(
    event: JsonDict,
    payload: JsonDict,
    nodes_by_id: dict[str, JsonDict],
    bounds: JsonDict,
    *,
    node_id: str,
    text: str,
    delay: float,
    ttl: float,
    derived_index: int,
    sequence_index: int,
    sequence_total: int,
    origin: str,
    current_tick: int | None,
    salience: float | None = None,
) -> JsonDict:
    if not node_id or node_id not in nodes_by_id:
        return {}
    timing = {"delay": delay, "ttl": ttl}
    if current_tick is not None and _display_payload_finished(
        event, timing, current_tick
    ):
        return {}
    projected = _project_node(nodes_by_id[node_id], bounds)
    source_sequence = int(event.get("sequence", 0) or 0)
    return {
        "node_id": node_id,
        "text": text,
        "source": payload.get("source", event.get("source", "")),
        "salience": float(
            salience if salience is not None else payload.get("salience", 0.82)
        ),
        "ttl": ttl,
        "delay": delay,
        "tick": event.get("tick", 0),
        "sequence": source_sequence * 100 + derived_index + 1,
        "schedule_sequence": source_sequence,
        "sequence_index": sequence_index,
        "sequence_total": sequence_total,
        "origin": origin,
        "ripple_from": str(payload.get("node_id", ""))
        if origin == "ripple_response"
        else "",
        "source_node": str(payload.get("node_id", ""))
        if origin == "ripple_response"
        else "",
        "x": projected["x"],
        "y": projected["y"],
    }


def _split_schedule_text(text: str, count: int) -> list[str]:
    return split_thought_for_presentation(text, count)


def _display_payload_finished(
    event: JsonDict, payload: JsonDict, current_tick: int
) -> bool:
    event_tick = float(event.get("tick", 0) or 0)
    delay = max(float(payload.get("delay", 0.0) or 0.0), 0.0)
    ttl = max(float(payload.get("ttl", 0.0) or 0.0), 0.0)
    return event_tick + delay + ttl < float(current_tick)


def _grounded_actions(
    events: list[Any],
    nodes_by_id: dict[str, JsonDict],
    bounds: JsonDict,
    traces: list[Any] | None = None,
    limit: int | None = 80,
) -> list[JsonDict]:
    grounded: list[JsonDict] = []
    decisions = _rule_decision_evidence(_list(traces))
    for event in events:
        event_data = _dict(event)
        if event_data.get("kind") != "action_feedback":
            continue
        payload = _dict(event_data.get("payload"))
        apply_mode = str(payload.get("apply_mode", ""))
        if apply_mode and apply_mode != "authoritative":
            continue
        actor_type = str(payload.get("actor_type", ""))
        action = str(payload.get("action", "")).strip()
        actor_id = str(payload.get("actor_id", "")).strip()
        if actor_type not in {"node", "person", "user", "operator"} or not action or not actor_id:
            continue
        projected_effects = _project_effects(_list(payload.get("effects")), nodes_by_id)
        item: JsonDict = {
            "tick": event_data.get("tick", 0),
            "sequence": event_data.get("sequence", 0),
            "action": action,
            "summary": str(payload.get("summary", "")),
            "source": str(payload.get("source", "")),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "actor_name": _node_name(nodes_by_id, actor_id),
            "actor_attributes": _node_attributes(nodes_by_id, actor_id),
            "targets": _project_targets(_list(payload.get("targets")), nodes_by_id),
            "effect_count": len(_list(payload.get("effects"))),
            "effects": projected_effects,
            "intervention": _project_intervention_metadata(payload.get("intervention") or _dict(payload.get("metadata")).get("intervention")),
            "sovereign_intent": _project_sovereign_intent_metadata(
                payload.get("sovereign_intent") or _dict(payload.get("metadata")).get("sovereign_intent")
            ),
            "caused_by_pressure_ids": json_copy(
                _list(payload.get("caused_by_pressure_ids"))
            ),
            "caused_by_provider_job_ids": json_copy(
                _list(payload.get("caused_by_provider_job_ids"))
            ),
            "selected_action_option_id": str(
                payload.get("selected_action_option_id", "")
            ),
        }
        decision = decisions.get((int(event_data.get("tick", 0) or 0), actor_id, action))
        if decision:
            item["decision"] = decision
        if not item["targets"]:
            item["targets"] = _targets_from_effects(projected_effects)
        if actor_id in nodes_by_id:
            projected = _project_node(nodes_by_id[actor_id], bounds)
            item["x"] = projected["x"]
            item["y"] = projected["y"]
        grounded.append(item)
    if limit is None:
        return grounded
    return grounded[-max(int(limit), 0) :]


def _action_visuals(grounded_actions: list[JsonDict]) -> list[JsonDict]:
    visuals: list[JsonDict] = []
    seen_sequences: set[int] = set()
    for action in grounded_actions:
        sequence = int(action.get("sequence", 0) or 0)
        actor_id = str(action.get("actor_id", ""))
        if sequence <= 0 or sequence in seen_sequences or not actor_id:
            continue
        seen_sequences.add(sequence)
        label = ""
        for raw_effect in _list(action.get("effects")):
            effect_data = _dict(raw_effect)
            if effect_data.get("type") != "action_bullet_add":
                continue
            target_id = str(_dict(effect_data.get("target")).get("id", ""))
            text = str(effect_data.get("text", "")).strip()
            if text and (not target_id or target_id == actor_id):
                label = text
                break
        item = json_copy(action)
        item["feedback_sequence"] = sequence
        item["label"] = label or str(action.get("action", "")).replace("_", " ")
        item["ttl"] = 2.4
        visuals.append(item)
    return visuals


def _current_actions(
    action_visuals: list[JsonDict],
    *,
    active_actions: list[Any] | None = None,
    action_history: list[Any] | None = None,
    nodes_by_id: dict[str, JsonDict] | None = None,
    bounds: JsonDict | None = None,
) -> list[JsonDict]:
    active_rows = _active_action_rows(
        active_actions or [], nodes_by_id or {}, bounds or {}
    )
    active_by_actor = {
        str(item.get("actor_id", "")): item for item in active_rows
    }
    v2_actor_ids = set(active_by_actor)
    for raw_action in action_history or []:
        action = _dict(raw_action)
        actor_id = str(action.get("actor_id", "")).strip()
        if actor_id:
            v2_actor_ids.add(actor_id)
    latest_by_actor: dict[str, JsonDict] = {}
    for visual in action_visuals:
        actor_type = str(visual.get("actor_type", ""))
        actor_id = str(visual.get("actor_id", "")).strip()
        sequence = int(visual.get("feedback_sequence", 0) or 0)
        if actor_type not in {"node", "person"} or not actor_id or sequence <= 0:
            continue
        if actor_id in v2_actor_ids:
            continue
        current = latest_by_actor.get(actor_id)
        if current is None or sequence > int(current.get("feedback_sequence", 0) or 0):
            latest_by_actor[actor_id] = visual
    latest_by_actor.update(active_by_actor)
    return [
        json_copy(latest_by_actor[actor_id])
        for actor_id in sorted(latest_by_actor)
    ]


def _active_action_rows(
    active_actions: list[Any],
    nodes_by_id: dict[str, JsonDict],
    bounds: JsonDict,
) -> list[JsonDict]:
    selected_by_actor: dict[str, JsonDict] = {}
    for raw_action in active_actions:
        action = _dict(raw_action)
        status = str(action.get("status", ""))
        actor_type = str(action.get("actor_type", ""))
        actor_id = str(action.get("actor_id", "")).strip()
        if (
            status not in {"starting", "running"}
            or actor_type not in {"node", "person"}
            or not actor_id
        ):
            continue
        row = {
            "action_id": str(action.get("id", "")),
            "feedback_sequence": _action_ordinal(str(action.get("id", ""))),
            "action": str(action.get("definition_id", "")),
            "definition_id": str(action.get("definition_id", "")),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "actor_name": _node_name(nodes_by_id, actor_id),
            "channel": str(action.get("channel", "physical")),
            "status": status,
            "progress": float(action.get("progress", 0.0) or 0.0),
            "tick": int(action.get("updated_tick", 0) or 0),
            "started_tick": int(action.get("started_tick", 0) or 0),
            "updated_tick": int(action.get("updated_tick", 0) or 0),
            "deadline_tick": action.get("deadline_tick"),
            "target_ids": json_copy(_list(action.get("target_ids"))),
            "locks": json_copy(_list(action.get("locks"))),
            "label": str(
                action.get("behavior_label")
                or action.get("definition_id")
                or "行动"
            ),
            "salience": float(action.get("salience", 0.5) or 0.0),
            "package_id": str(action.get("package_id", "")),
            "package_version": str(action.get("package_version", "")),
            "root_causality_id": str(action.get("root_causality_id", "")),
            "caused_by": json_copy(_list(action.get("caused_by"))),
            "activity_id": str(_dict(action.get("parameters")).get("activity_id", "")),
            "activity_step": int(_dict(action.get("parameters")).get("activity_step", 0) or 0),
            "activity_role": str(_dict(action.get("parameters")).get("activity_role", "")),
            "source": f"action_runtime:{action.get('package_id', '')}",
            "ttl": 0.5,
        }
        if actor_id in nodes_by_id and bounds:
            projected = _project_node(nodes_by_id[actor_id], bounds)
            row["x"] = projected["x"]
            row["y"] = projected["y"]
        current = selected_by_actor.get(actor_id)
        if current is None or _active_action_priority(row) > _active_action_priority(
            current
        ):
            selected_by_actor[actor_id] = row
    return [selected_by_actor[actor_id] for actor_id in sorted(selected_by_actor)]


def _active_action_priority(action: JsonDict) -> tuple[int, float, int, str]:
    return (
        1 if str(action.get("channel", "")) == "social" else 0,
        float(action.get("salience", 0.0) or 0.0),
        int(action.get("updated_tick", 0) or 0),
        str(action.get("action_id", "")),
    )


def _action_ordinal(action_id: str) -> int:
    parts = action_id.split(":")
    if len(parts) >= 3 and parts[0] == "action":
        try:
            return max(int(parts[2]), 1)
        except ValueError:
            return 1
    return 1


def _impact_ripples(
    social_ripples: JsonDict,
    nodes_by_id: dict[str, JsonDict],
    bounds: JsonDict,
    limit: int = 80,
) -> list[JsonDict]:
    rows: list[JsonDict] = []
    chains = _list(_dict(social_ripples).get("chains"))
    scatter = _list(_dict(social_ripples).get("scatter"))
    for raw_chain in chains:
        chain = _dict(raw_chain)
        node_id = str(chain.get("node_id", ""))
        item: JsonDict = {
            "kind": "chain",
            "node_id": node_id,
            "start_sequence": chain.get("start_sequence", 0),
            "end_sequence": chain.get("end_sequence", 0),
            "domains": json_copy(_list(chain.get("domains"))),
            "items": json_copy(_list(chain.get("items"))[:8]),
        }
        if node_id in nodes_by_id:
            projected = _project_node(nodes_by_id[node_id], bounds)
            item["x"] = projected["x"]
            item["y"] = projected["y"]
            item["node_name"] = projected["name"]
        rows.append(item)
    if not rows:
        for raw_item in scatter[-limit:]:
            ripple = _dict(raw_item)
            node_id = str(ripple.get("node_id", ""))
            item = {
                "kind": str(ripple.get("kind", "ripple")),
                "domain": str(ripple.get("domain", "")),
                "node_id": node_id,
                "tick": ripple.get("tick", 0),
                "sequence": ripple.get("sequence", 0),
                "summary": _short_text(ripple.get("summary", ""), limit=120),
                "source": str(ripple.get("source", "")),
            }
            if node_id in nodes_by_id:
                projected = _project_node(nodes_by_id[node_id], bounds)
                item["x"] = projected["x"]
                item["y"] = projected["y"]
                item["node_name"] = projected["name"]
            rows.append(item)
    return rows[-max(int(limit), 0) :]


def _key_character_trajectories(nodes: list[JsonDict], events: list[Any], bounds: JsonDict, limit: int = 24) -> list[JsonDict]:
    thoughts_by_node, actions_by_node = _visible_counts_by_node(events)
    rows: list[JsonDict] = []
    for node in nodes:
        if not _is_key_character(node):
            continue
        projected = _project_node(node, bounds)
        state = _dict(node.get("key_character"))
        attributes = _dict(node.get("attributes"))
        node_id = str(node.get("id", ""))
        rows.append(
            {
                "node_id": node_id,
                "name": str(node.get("name", node_id)),
                "x": projected["x"],
                "y": projected["y"],
                "identity": state.get("identity") or attributes.get("identity") or attributes.get("role", ""),
                "status": state.get("status", ""),
                "goal": state.get("goal", state.get("long_term_goal", "")),
                "current_step": state.get("current_step", state.get("plan_step", "")),
                "salience_score": state.get("salience_score", 0),
                "thought_count": thoughts_by_node.get(node_id, 0),
                "action_bullet_count": actions_by_node.get(node_id, 0),
                "memory_highlights": _memory_highlights(_list(node.get("memories")), limit=2),
            }
        )
    rows.sort(key=lambda item: (-float(item.get("salience_score", 0) or 0), str(item.get("node_id", ""))))
    return rows[: max(int(limit), 0)]


def _visible_counts_by_node(events: list[Any]) -> tuple[dict[str, int], dict[str, int]]:
    thoughts: dict[str, int] = {}
    actions: dict[str, int] = {}
    for event in events:
        payload = _dict(_dict(event).get("payload"))
        node_id = str(payload.get("node_id", ""))
        if not node_id:
            continue
        if payload.get("type") == "thought_bubble":
            thoughts[node_id] = thoughts.get(node_id, 0) + 1
        elif payload.get("type") == "action_bullet":
            actions[node_id] = actions.get(node_id, 0) + 1
    return thoughts, actions


def _rule_decision_evidence(traces: list[Any]) -> dict[tuple[int, str, str], JsonDict]:
    decisions: dict[tuple[int, str, str], JsonDict] = {}
    for raw_trace in traces:
        trace = _dict(raw_trace)
        if trace.get("kind") != "rule_decision":
            continue
        selected = _dict(trace.get("selected"))
        node_id = str(selected.get("node_id", "")).strip()
        action = str(selected.get("action", "")).strip()
        if not node_id or not action:
            continue
        decisions[(int(trace.get("tick", 0) or 0), node_id, action)] = {
            "rule": str(selected.get("rule", "")),
            "reason": _short_text(selected.get("reason", ""), limit=96),
            "score": float(selected.get("score", 0.0) or 0.0),
            "candidate_count": len(_list(trace.get("candidates"))),
        }
    return decisions


def _project_effects(
    effects: list[Any],
    nodes_by_id: dict[str, JsonDict],
    limit: int = 10,
) -> list[JsonDict]:
    projected: list[JsonDict] = []
    for raw_effect in effects[: max(int(limit), 0)]:
        effect_data = _dict(raw_effect)
        effect_type = str(effect_data.get("type", ""))
        if not effect_type:
            continue
        projected.append(
            {
                "type": effect_type,
                "label": _effect_label(effect_data, nodes_by_id),
                "target": _project_effect_ref(effect_data.get("target"), nodes_by_id),
                "source": _project_effect_ref(effect_data.get("source"), nodes_by_id),
                "from": _project_effect_ref(effect_data.get("from"), nodes_by_id),
                "to": _project_effect_ref(effect_data.get("to"), nodes_by_id),
                "resource": effect_data.get("resource", ""),
                "field": effect_data.get("field", ""),
                "text": effect_data.get("text", ""),
                "delta": effect_data.get("delta", ""),
                "amount": effect_data.get("amount", ""),
                "change": _effect_change(effect_data, nodes_by_id),
            }
        )
    return projected


def _project_intervention_metadata(value: Any) -> JsonDict:
    metadata = _dict(value)
    if not metadata:
        return {}
    return {
        "id": str(metadata.get("id", "")),
        "scheduled_tick": metadata.get("scheduled_tick", ""),
        "effect_count": metadata.get("effect_count", ""),
    }


def _project_sovereign_intent_metadata(value: Any) -> JsonDict:
    metadata = _dict(value)
    if not metadata:
        return {}
    return {
        "id": str(metadata.get("id", "")),
        "title": str(metadata.get("title", "")),
        "impact_level": str(metadata.get("impact_level", "")),
        "scheduled_tick": metadata.get("scheduled_tick", ""),
    }


def _targets_from_effects(effects: list[JsonDict], limit: int = 4) -> list[JsonDict]:
    targets: list[JsonDict] = []
    seen: set[str] = set()
    for effect in effects:
        for key in ("target", "to", "from", "source"):
            ref = _dict(effect.get(key))
            node_id = str(ref.get("id", ""))
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            targets.append(ref)
            if len(targets) >= max(int(limit), 0):
                return targets
    return targets


def _effect_change(effect_data: JsonDict, nodes_by_id: dict[str, JsonDict]) -> JsonDict:
    effect_type = str(effect_data.get("type", ""))
    if effect_type == "resource_delta":
        node_id = _node_id(effect_data.get("target"))
        resource = str(effect_data.get("resource", ""))
        delta = _number(effect_data.get("delta"))
        after = _resource_value(nodes_by_id, node_id, resource)
        if not node_id or not resource or delta is None or after is None:
            return {}
        before = after - delta
        return {
            "kind": "resource",
            "node_id": node_id,
            "node_name": _node_name(nodes_by_id, node_id),
            "resource": resource,
            "before": before,
            "after": after,
            "delta": delta,
            "label": f"{resource}: {_format_number(before)} → {_format_number(after)}",
        }
    if effect_type == "resource_transfer":
        from_id = _node_id(effect_data.get("from"))
        to_id = _node_id(effect_data.get("to"))
        resource = str(effect_data.get("resource", ""))
        amount = _number(effect_data.get("amount"))
        from_after = _resource_value(nodes_by_id, from_id, resource)
        to_after = _resource_value(nodes_by_id, to_id, resource)
        if not from_id or not to_id or not resource or amount is None or from_after is None or to_after is None:
            return {}
        return {
            "kind": "resource_transfer",
            "resource": resource,
            "amount": amount,
            "from": {
                "node_id": from_id,
                "node_name": _node_name(nodes_by_id, from_id),
                "before": from_after + amount,
                "after": from_after,
            },
            "to": {
                "node_id": to_id,
                "node_name": _node_name(nodes_by_id, to_id),
                "before": to_after - amount,
                "after": to_after,
            },
            "label": (
                f"{resource}: {_node_name(nodes_by_id, from_id)} "
                f"{_format_number(from_after + amount)} → {_format_number(from_after)}, "
                f"{_node_name(nodes_by_id, to_id)} {_format_number(to_after - amount)} → {_format_number(to_after)}"
            ),
        }
    if effect_type == "node_attribute_delta":
        node_id = _node_id(effect_data.get("target"))
        field = str(effect_data.get("field", ""))
        delta = _number(effect_data.get("delta"))
        after = _number(_node_attributes(nodes_by_id, node_id).get(field))
        if not node_id or not field or delta is None or after is None:
            return {}
        before = after - delta
        return {
            "kind": "attribute",
            "node_id": node_id,
            "node_name": _node_name(nodes_by_id, node_id),
            "field": field,
            "before": before,
            "after": after,
            "delta": delta,
            "label": f"{field}: {_format_number(before)} → {_format_number(after)}",
        }
    return {}


def _effect_label(effect_data: JsonDict, nodes_by_id: dict[str, JsonDict]) -> str:
    effect_type = str(effect_data.get("type", ""))
    target = _effect_ref_name(effect_data.get("target"), nodes_by_id)
    source = _effect_ref_name(effect_data.get("source"), nodes_by_id)
    from_name = _effect_ref_name(effect_data.get("from"), nodes_by_id)
    to_name = _effect_ref_name(effect_data.get("to"), nodes_by_id)
    resource = str(effect_data.get("resource", ""))
    field = str(effect_data.get("field", ""))
    delta = effect_data.get("delta")
    amount = effect_data.get("amount")
    if effect_type == "resource_delta":
        return f"{target} {resource} {_signed(delta)}".strip()
    if effect_type == "resource_transfer":
        return f"{from_name} → {to_name} {amount:g} {resource}".strip() if isinstance(amount, (int, float)) else f"{from_name} → {to_name} {resource}".strip()
    if effect_type == "node_attribute_delta":
        return f"{target} {field} {_signed(delta)}".strip()
    if effect_type == "node_attribute_merge":
        return f"{target} 更新 {field}".strip()
    if effect_type == "node_state":
        return f"{target} {field}".strip()
    if effect_type == "relationship_delta":
        relation = str(effect_data.get("relation", "relationship"))
        return f"{source} ↔ {target} {relation} {_signed(delta)}".strip()
    if effect_type == "memory_add":
        return f"{target} 记忆：{_short_text(effect_data.get('text'))}".strip()
    if effect_type == "action_bullet_add":
        return f"{target} 显示：{_short_text(effect_data.get('text'))}".strip()
    if effect_type == "policy_state":
        policy = str(effect_data.get("policy", "policy"))
        status = str(effect_data.get("status", ""))
        return f"{target} {policy} {status}".strip()
    if target:
        return f"{target} {effect_type}".strip()
    return effect_type


def _project_effect_ref(value: Any, nodes_by_id: dict[str, JsonDict]) -> JsonDict:
    node_id = _node_id(value)
    if not node_id:
        return {}
    return {
        "id": node_id,
        "name": _node_name(nodes_by_id, node_id),
        "attributes": _node_attributes(nodes_by_id, node_id),
    }


def _effect_ref_name(value: Any, nodes_by_id: dict[str, JsonDict]) -> str:
    node_id = _node_id(value)
    if not node_id:
        return ""
    return _node_name(nodes_by_id, node_id)


def _signed(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    return f"{value:+g}"


def _resource_value(nodes_by_id: dict[str, JsonDict], node_id: str, resource: str) -> float | None:
    value = _dict(_node_attributes(nodes_by_id, node_id).get("resources")).get(resource)
    return _number(value)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _format_number(value: float) -> str:
    return f"{value:g}"


def _short_text(value: Any, limit: int = 34) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: max(limit - 1, 0)]}…"


def _project_targets(targets: list[Any], nodes_by_id: dict[str, JsonDict]) -> list[JsonDict]:
    projected: list[JsonDict] = []
    for raw_target in targets:
        target_data = _dict(raw_target)
        target_id = str(target_data.get("id", ""))
        target_type = str(target_data.get("type", ""))
        if not target_id:
            continue
        projected.append(
            {
                "id": target_id,
                "type": target_type,
                "name": _node_name(nodes_by_id, target_id),
                "attributes": _node_attributes(nodes_by_id, target_id),
            }
        )
    return projected


def _node_name(nodes_by_id: dict[str, JsonDict], node_id: str) -> str:
    node = nodes_by_id.get(node_id)
    return str(_dict(node).get("name", node_id) or node_id)


def _node_attributes(nodes_by_id: dict[str, JsonDict], node_id: str) -> JsonDict:
    return json_copy(_dict(_dict(nodes_by_id.get(node_id)).get("attributes")))


def _node_id(value: Any) -> str:
    text = str(value or "")
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _organization_members(
    relationships: list[JsonDict],
    nodes_by_id: dict[str, JsonDict],
) -> dict[str, list[str]]:
    member_map: dict[str, list[str]] = {}
    for edge in relationships:
        if edge.get("type") != "member_of":
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if target in nodes_by_id:
            member_map.setdefault(target, []).append(source)
    return member_map


def _project_relationship(edge: JsonDict) -> JsonDict:
    return {
        "source": edge.get("source", ""),
        "target": edge.get("target", ""),
        "type": edge.get("type", ""),
        "weight": edge.get("weight", 0.0),
        "metadata": json_copy(_dict(edge.get("metadata"))),
    }


def _bounds(nodes: list[JsonDict]) -> JsonDict:
    xs = [float(_dict(node.get("position")).get("x", 0.0) or 0.0) for node in nodes] or [0.0]
    ys = [float(_dict(node.get("position")).get("y", 0.0) or 0.0) for node in nodes] or [0.0]
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
    }


def _normalize(value: float, low: float, high: float) -> float:
    if high == low:
        return 50.0
    return round(15.0 + ((value - low) / (high - low)) * 70.0, 3)


def _is_viewer_visible_node(
    node: JsonDict,
    display_node_ids: set[str],
    include_tribe_members: bool = False,
) -> bool:
    node_id = str(node.get("id", ""))
    attributes = _dict(node.get("attributes"))
    # Tribe's relationship-network members are intentionally rendered as a
    # person-level population. `viewer_background` remains a simulation-cost
    # hint there, rather than a projection filter.
    if include_tribe_members and attributes.get("agent_layer") == "relationship_network_member":
        return True
    return (
        not bool(attributes.get("viewer_background", False))
        or node_id in display_node_ids
    )


def _is_relationship_network(node: JsonDict) -> bool:
    attributes = _dict(node.get("attributes"))
    return node.get("type") == "organization" and attributes.get("agent_layer") == "relationship_network"


def _is_key_character(node: JsonDict) -> bool:
    return node.get("type") == "key_character" or _dict(node.get("key_character")).get("agent_layer") == "key_character"


def _is_people_node(node: JsonDict) -> bool:
    return node.get("type") in {"person", "population_cohort", "organization_member"}


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
