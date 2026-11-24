"""世界记忆检索和压力-行动对账。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import json_copy
from .world import World


JsonDict = dict[str, Any]


@dataclass(slots=True)
class MemoryRecord:
    node_id: str
    text: str
    tick: int
    source: str = "system"
    importance: float = 0.0

    def to_dict(self) -> JsonDict:
        return {
            "node_id": self.node_id,
            "text": self.text,
            "tick": self.tick,
            "source": self.source,
            "importance": self.importance,
        }


@dataclass(slots=True)
class MemoryQuery:
    node_id: str
    limit: int = 8
    text: str = ""


@dataclass(slots=True)
class MemorySearchResult:
    node_id: str
    memories: list[JsonDict] = field(default_factory=list)
    relationships: list[JsonDict] = field(default_factory=list)
    pressures: list[JsonDict] = field(default_factory=list)
    recent_feedback: list[JsonDict] = field(default_factory=list)
    traces: list[JsonDict] = field(default_factory=list)
    ranked_records: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "node_id": self.node_id,
            "memories": json_copy(self.memories),
            "relationships": json_copy(self.relationships),
            "pressures": json_copy(self.pressures),
            "recent_feedback": json_copy(self.recent_feedback),
            "traces": json_copy(self.traces),
            "ranked_records": json_copy(self.ranked_records),
        }


@dataclass(slots=True)
class MemoryConsolidationResult:
    node_id: str
    original_count: int
    retained_count: int
    summary: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "node_id": self.node_id,
            "original_count": self.original_count,
            "retained_count": self.retained_count,
            "summary": json_copy(self.summary),
        }


class WorldMemoryRetriever:
    def retrieve(self, world: World, query: MemoryQuery) -> MemorySearchResult:
        node = world.node(query.node_id)
        relationships = [
            edge.to_dict()
            for edge in world.relationships.values()
            if edge.source == node.id or edge.target == node.id
        ]
        feedback = [
            event
            for event in world.events.recent(query.limit * 4)
            if str(event.get("payload", {}).get("actor_id", "")) == node.id
            or _event_mentions_node(event, node.id)
        ][-query.limit :]
        traces = [
            trace
            for trace in world.traces.recent(query.limit * 4)
            if str(trace.get("observed", {}).get("node_id", "")) == node.id
            or str(trace.get("selected", {}).get("node_id", "")) == node.id
        ][-query.limit :]
        ranked_records = _rank_records(
            query.text,
            [
                *(_record("memory", item, item.get("text", item.get("summary", ""))) for item in node.memories),
                *(_record("relationship", item, f"{item.get('type', '')} {item.get('metadata', '')}") for item in relationships),
                *(_record("pressure", item, f"{item.get('rule', '')} {item.get('reason', '')}") for item in node.rule_pressures),
                *(_record("feedback", item, f"{item.get('payload', {}).get('summary', '')} {item.get('payload', {}).get('action', '')}") for item in feedback),
                *(_record("trace", item, f"{item.get('kind', '')} {item.get('source', '')} {item.get('observed', '')} {item.get('selected', '')}") for item in traces),
            ],
            query.limit,
        )
        return MemorySearchResult(
            node_id=node.id,
            memories=json_copy(node.memories[-query.limit :]),
            relationships=relationships[-query.limit :],
            pressures=json_copy(node.rule_pressures[-query.limit :]),
            recent_feedback=feedback,
            traces=traces,
            ranked_records=ranked_records,
        )


class WorldMemoryConsolidator:
    def consolidate_node(
        self,
        world: World,
        node_id: str,
        max_memories: int = 12,
        recent_keep: int = 6,
        source_credibility: dict[str, float] | None = None,
        retention_importance_floor: float | None = None,
    ) -> MemoryConsolidationResult:
        node = world.node(node_id)
        original = json_copy(node.memories)
        if len(original) <= max_memories:
            return MemoryConsolidationResult(node.id, len(original), len(original), {})

        recent_keep = max(min(int(recent_keep), int(max_memories) - 1), 1)
        older = original[: -recent_keep]
        recent = original[-recent_keep:]
        retained_older, forgotten = _apply_retention_floor(older, retention_importance_floor)
        summary = self._summary(
            world.tick,
            node.id,
            retained_older,
            source_credibility=source_credibility or {},
            forgotten=forgotten,
        )
        node.memories = [summary, *recent]
        return MemoryConsolidationResult(node.id, len(original), len(node.memories), summary)

    def consolidate_world(
        self,
        world: World,
        max_memories: int = 12,
        recent_keep: int = 6,
        source_credibility: dict[str, float] | None = None,
        retention_importance_floor: float | None = None,
    ) -> list[MemoryConsolidationResult]:
        return [
            result
            for node_id in sorted(world.nodes)
            if (
                result := self.consolidate_node(
                    world,
                    node_id,
                    max_memories,
                    recent_keep,
                    source_credibility=source_credibility,
                    retention_importance_floor=retention_importance_floor,
                )
            ).summary
        ]

    def _summary(
        self,
        tick: int,
        node_id: str,
        memories: list[JsonDict],
        *,
        source_credibility: dict[str, float],
        forgotten: list[JsonDict],
    ) -> JsonDict:
        sources = sorted({str(item.get("source", "unknown")) for item in memories if item.get("source")})
        ticks = [
            int(item.get("tick", tick) or tick)
            for item in memories
            if isinstance(item.get("tick", tick), int)
        ]
        keywords = _top_terms(" ".join(_memory_text(item) for item in memories), limit=8)
        importance_values = [
            float(item.get("importance", 0.0) or 0.0)
            for item in memories
            if isinstance(item.get("importance", 0.0), (int, float))
        ]
        highlights = [_memory_text(item) for item in sorted(memories, key=_memory_sort_key, reverse=True)[:3]]
        return {
            "kind": "memory_summary",
            "node_id": node_id,
            "text": " / ".join(highlights)[:520],
            "summary": " / ".join(highlights)[:520],
            "source": "memory_consolidator",
            "sources": sources,
            "tick": tick,
            "tick_start": min(ticks) if ticks else tick,
            "tick_end": max(ticks) if ticks else tick,
            "importance": round(sum(importance_values) / len(importance_values), 4) if importance_values else 0.0,
            "memory_count": len(memories),
            "keywords": keywords,
            "source_credibility": _source_credibility(sources, source_credibility),
            "average_credibility": _average_credibility(memories, source_credibility),
            "contradictions": _contradictions(memories),
            "forgotten_count": len(forgotten),
            "forgotten_sources": sorted({str(item.get("source", "unknown")) for item in forgotten if item.get("source")}),
        }


class PressureActionTraceLedger:
    def build_report(self, world: World, window: int = 6) -> JsonDict:
        pressures: list[JsonDict] = []
        actions: list[JsonDict] = []
        for event in world.events.recent():
            payload = event.get("payload", {})
            if event.get("kind") == "action_feedback":
                for raw_effect in payload.get("effects", []):
                    if raw_effect.get("type") == "rule_pressure_add":
                        pressures.append(
                            {
                                "tick": event["tick"],
                                "sequence": event["sequence"],
                                "node_id": _node_id(raw_effect.get("target", "")),
                                "rule": raw_effect.get("rule", ""),
                                "expected_action": raw_effect.get(
                                    "expected_action", raw_effect.get("action", "")
                                ),
                                "source": raw_effect.get("source", payload.get("source", "")),
                                "pressure_id": raw_effect.get("pressure_id", ""),
                                "provider_job_id": raw_effect.get("provider_job_id", ""),
                                "source_tick": raw_effect.get("source_tick", event["tick"]),
                                "applied_tick": raw_effect.get("applied_tick", event["tick"]),
                                "observation_deadline_tick": raw_effect.get(
                                    "observation_deadline_tick"
                                ),
                                "response_optional": bool(
                                    raw_effect.get("response_optional", False)
                                ),
                                "matched": False,
                                "status": "unmatched_terminal",
                                "action": {},
                            }
                        )
                if payload.get("action") and payload.get("actor_type") in {"node", "person"}:
                    actions.append(
                        {
                            "tick": event["tick"],
                            "sequence": event["sequence"],
                            "node_id": str(payload.get("actor_id", "")),
                            "action": payload.get("action", ""),
                            "summary": payload.get("summary", ""),
                            "caused_by_pressure_ids": _string_list(
                                payload.get("caused_by_pressure_ids")
                            ),
                        }
                    )
        for pressure in pressures:
            for action in actions:
                if action["sequence"] <= pressure["sequence"]:
                    continue
                if action["tick"] - pressure["tick"] > window:
                    continue
                if action["node_id"] != pressure["node_id"]:
                    continue
                pressure_id = str(pressure.get("pressure_id", ""))
                if pressure_id:
                    if pressure_id not in action["caused_by_pressure_ids"]:
                        continue
                    pressure["matched"] = True
                    pressure["status"] = "matched"
                    pressure["action"] = action
                    break
                if action["caused_by_pressure_ids"]:
                    continue
                expected_action = str(pressure.get("expected_action", ""))
                if expected_action and expected_action != str(action["action"]):
                    continue
                if expected_action or _action_matches_rule(str(action["action"]), str(action["summary"]), str(pressure["rule"])):
                    pressure["matched"] = True
                    pressure["status"] = "matched"
                    pressure["action"] = action
                    break
            if pressure["matched"]:
                continue
            if pressure["response_optional"]:
                pressure["status"] = "optional_unanswered"
                continue
            deadline = _observation_deadline(pressure)
            if deadline is not None and world.tick < deadline:
                pressure["status"] = "pending_observation"
        matched = sum(1 for pressure in pressures if pressure["matched"])
        pending = sum(
            1 for pressure in pressures if pressure["status"] == "pending_observation"
        )
        unmatched = len(pressures) - matched - pending
        optional_unanswered = sum(
            1
            for pressure in pressures
            if pressure["status"] == "optional_unanswered"
        )
        unmatched -= optional_unanswered
        terminal = matched + unmatched
        return {
            "totals": {
                "pressures": len(pressures),
                "matched": matched,
                "unmatched": unmatched,
                "unmatched_terminal": unmatched,
                "pending_observation": pending,
                "optional_unanswered": optional_unanswered,
                "terminal_pressures": terminal,
                "match_rate": matched / terminal if terminal else 0.0,
            },
            "recent": pressures[-20:],
        }


class AiCausalityTraceLedger:
    def build_report(self, world: World, window: int = 6, recent_limit: int = 24) -> JsonDict:
        thoughts_by_node: dict[str, list[JsonDict]] = {}
        traces: list[JsonDict] = []
        actions: list[JsonDict] = []
        by_node: dict[str, JsonDict] = {}

        for event in world.events.recent():
            payload = event.get("payload", {})
            if event.get("kind") != "action_feedback":
                continue
            effects = payload.get("effects", [])
            if isinstance(effects, list):
                for raw_effect in effects:
                    if not isinstance(raw_effect, dict):
                        continue
                    if raw_effect.get("type") in {"thought_bubble_add", "thought_schedule_add"} and _is_ai_pressure_payload(payload, raw_effect):
                        thought = _thought_record(event, raw_effect, payload)
                        if thought:
                            thoughts_by_node.setdefault(thought["node_id"], []).append(thought)
                            _node_summary(by_node, thought["node_id"])["thoughts"] += 1
                for raw_effect in effects:
                    if not isinstance(raw_effect, dict):
                        continue
                    if raw_effect.get("type") == "rule_pressure_add" and _is_ai_pressure_payload(payload, raw_effect):
                        trace = _ai_pressure_trace(event, raw_effect, payload, thoughts_by_node)
                        if trace:
                            traces.append(trace)
                            _node_summary(by_node, trace["node_id"])["pressures"] += 1
            action = _grounded_action_record(event)
            if action:
                actions.append(action)
                _node_summary(by_node, action["node_id"])["actions"] += 1
                _match_ai_action(action, traces, window, by_node)

        for trace in traces:
            if trace["matched"]:
                trace["status"] = "matched"
                continue
            deadline = _observation_deadline(trace["pressure"])
            if deadline is not None and world.tick < deadline:
                trace["status"] = "pending_observation"
                _node_summary(by_node, trace["node_id"])["pending_observation"] += 1
            else:
                trace["status"] = "unmatched_terminal"
                _node_summary(by_node, trace["node_id"])["unmatched_pressures"] += 1

        matched = sum(1 for trace in traces if trace["matched"])
        pending = sum(
            1 for trace in traces if trace["status"] == "pending_observation"
        )
        unmatched = len(traces) - matched - pending
        terminal = matched + unmatched
        return {
            "totals": {
                "thoughts": sum(len(items) for items in thoughts_by_node.values()),
                "pressures": len(traces),
                "actions": len(actions),
                "matched_pressures": matched,
                "unmatched_pressures": unmatched,
                "unmatched_terminal": unmatched,
                "pending_observation": pending,
                "terminal_pressures": terminal,
                "alignment_rate": matched / terminal if terminal else 0.0,
            },
            "by_node": by_node,
            "recent": json_copy(traces[-recent_limit:]),
        }


class ProviderOutcomeLedger:
    def build_report(self, world: World) -> JsonDict:
        ai_report = AiCausalityTraceLedger().build_report(
            world,
            recent_limit=max(len(world.events.recent()), 24),
        )
        providers: dict[str, JsonDict] = {}
        for trace in _list(ai_report.get("recent")):
            pressure = _dict(trace.get("pressure"))
            provider = str(pressure.get("source", "unknown")) or "unknown"
            row = providers.setdefault(
                provider,
                {
                    "provider": provider,
                    "pressures": 0,
                    "matched_pressures": 0,
                    "unmatched_pressures": 0,
                    "pending_observation": 0,
                    "latency_ticks_total": 0,
                    "latency_samples": 0,
                    "rules": {},
                    "nodes": {},
                },
            )
            row["pressures"] += 1
            rule = str(pressure.get("rule", ""))
            if rule:
                row["rules"][rule] = int(row["rules"].get(rule, 0) or 0) + 1
            node_id = str(trace.get("node_id", ""))
            if node_id:
                row["nodes"][node_id] = int(row["nodes"].get(node_id, 0) or 0) + 1
            if trace.get("matched"):
                row["matched_pressures"] += 1
                row["latency_ticks_total"] += int(trace.get("latency_ticks", 0) or 0)
                row["latency_samples"] += 1
            elif trace.get("status") == "pending_observation":
                row["pending_observation"] += 1
            else:
                row["unmatched_pressures"] += 1

        provider_rows = []
        for row in providers.values():
            pressures = int(row["pressures"])
            latency_samples = int(row["latency_samples"])
            terminal_pressures = int(row["matched_pressures"]) + int(
                row["unmatched_pressures"]
            )
            provider_rows.append(
                {
                    "provider": row["provider"],
                    "pressures": pressures,
                    "matched_pressures": int(row["matched_pressures"]),
                    "unmatched_pressures": int(row["unmatched_pressures"]),
                    "pending_observation": int(row["pending_observation"]),
                    "terminal_pressures": terminal_pressures,
                    "alignment_rate": round(
                        float(row["matched_pressures"]) / terminal_pressures, 4
                    )
                    if terminal_pressures
                    else 0.0,
                    "average_latency_ticks": round(float(row["latency_ticks_total"]) / latency_samples, 4)
                    if latency_samples
                    else 0.0,
                    "rules": json_copy(row["rules"]),
                    "nodes": json_copy(row["nodes"]),
                }
            )
        provider_rows.sort(key=lambda item: (-float(item["alignment_rate"]), str(item["provider"])))
        matched = sum(int(item["matched_pressures"]) for item in provider_rows)
        unmatched = sum(int(item["unmatched_pressures"]) for item in provider_rows)
        pending = sum(int(item["pending_observation"]) for item in provider_rows)
        pressures = sum(int(item["pressures"]) for item in provider_rows)
        terminal = matched + unmatched
        return {
            "totals": {
                "providers": len(provider_rows),
                "pressures": pressures,
                "matched_pressures": matched,
                "unmatched_pressures": unmatched,
                "unmatched_terminal": unmatched,
                "pending_observation": pending,
                "terminal_pressures": terminal,
                "alignment_rate": matched / terminal if terminal else 0.0,
            },
            "providers": provider_rows,
        }


class SocialRippleLedger:
    """Read-only social propagation view reconstructed from recent feedback."""

    def build_report(self, world: World, recent_limit: int = 80, chain_window: int = 6) -> JsonDict:
        scatter: list[JsonDict] = []
        by_node: dict[str, list[JsonDict]] = {}
        for event in world.events.recent(recent_limit):
            payload = event.get("payload", {})
            if event.get("kind") != "action_feedback":
                continue
            for raw_effect in _list(payload.get("effects")):
                if not isinstance(raw_effect, dict):
                    continue
                items = _ripple_items(event, payload, raw_effect)
                for item in items:
                    scatter.append(item)
                    by_node.setdefault(str(item["node_id"]), []).append(item)
            action = _grounded_action_record(event)
            if action:
                item = {
                    "kind": "grounded_action",
                    "tick": action["tick"],
                    "sequence": action["sequence"],
                    "node_id": action["node_id"],
                    "summary": action["summary"],
                    "source": action["source"],
                    "domain": "action",
                }
                scatter.append(item)
                by_node.setdefault(str(item["node_id"]), []).append(item)
        chains = _ripple_chains(by_node, chain_window)
        domain_counts: dict[str, int] = {}
        for item in scatter:
            domain = str(item.get("domain", "unknown"))
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        return {
            "totals": {
                "scatter_count": len(scatter),
                "chain_count": len(chains),
                "node_count": len(by_node),
            },
            "by_domain": domain_counts,
            "scatter": json_copy(scatter[-recent_limit:]),
            "chains": json_copy(chains[-recent_limit:]),
        }


def _ripple_item(event: JsonDict, payload: JsonDict, raw_effect: JsonDict) -> JsonDict:
    kind = str(raw_effect.get("type", ""))
    node_id = _node_id(raw_effect.get("target", raw_effect.get("node_id", raw_effect.get("source", ""))))
    if not node_id:
        return {}
    domains = {
        "thought_bubble_add": "thought",
        "thought_schedule_add": "thought",
        "rule_pressure_add": "pressure",
        "relationship_delta": "relationship",
        "memory_add": "memory",
        "key_character_state": "key_character",
    }
    if kind not in domains:
        return {}
    lens_id = str(raw_effect.get("lens_id", ""))
    origin = str(raw_effect.get("origin", ""))
    return {
        "kind": kind,
        "domain": lens_id or origin or domains[kind],
        "tick": event.get("tick", 0),
        "sequence": event.get("sequence", 0),
        "node_id": node_id,
        "source": raw_effect.get("source", payload.get("source", "")),
        "summary": raw_effect.get("text") or raw_effect.get("reason") or raw_effect.get("relation") or payload.get("summary", ""),
        "rule": raw_effect.get("rule", ""),
        "relation": raw_effect.get("relation", ""),
        "target": _node_id(raw_effect.get("target", raw_effect.get("to", ""))),
        "origin": origin,
        "lens_id": lens_id,
    }


def _ripple_items(
    event: JsonDict, payload: JsonDict, raw_effect: JsonDict
) -> list[JsonDict]:
    primary = _ripple_item(event, payload, raw_effect)
    if not primary:
        return []
    rows = [primary]
    if raw_effect.get("type") != "thought_schedule_add":
        return rows
    source_node = str(primary.get("node_id", ""))
    for raw_target in _list(raw_effect.get("ripple_targets")):
        target = raw_target if isinstance(raw_target, dict) else {}
        node_id = str(target.get("node_id", ""))
        if not node_id:
            continue
        rows.append(
            {
                **json_copy(primary),
                "node_id": node_id,
                "kind": "thought_schedule_ripple",
                "domain": "ripple_response",
                "origin": "ripple_response",
                "source_node": source_node,
                "summary": raw_effect.get("ripple_text", primary.get("summary", "")),
            }
        )
    return rows


def _ripple_chains(by_node: dict[str, list[JsonDict]], chain_window: int) -> list[JsonDict]:
    chains: list[JsonDict] = []
    for node_id, items in sorted(by_node.items()):
        ordered = sorted(items, key=lambda item: (int(item.get("sequence", 0)), int(item.get("tick", 0))))
        for start_index, start in enumerate(ordered):
            if start.get("kind") not in {"thought_bubble_add", "thought_schedule_add", "thought_schedule_ripple", "rule_pressure_add", "relationship_delta", "key_character_state"}:
                continue
            chain = [start]
            for item in ordered[start_index + 1 :]:
                if int(item.get("tick", 0)) - int(start.get("tick", 0)) > chain_window:
                    break
                if item.get("kind") == start.get("kind"):
                    continue
                chain.append(item)
                if item.get("kind") == "grounded_action":
                    break
            if len(chain) >= 2:
                chains.append(
                    {
                        "node_id": node_id,
                        "start_sequence": start.get("sequence", 0),
                        "end_sequence": chain[-1].get("sequence", 0),
                        "domains": [str(item.get("domain", "")) for item in chain],
                        "items": json_copy(chain),
                    }
                )
    return chains


def _event_mentions_node(event: JsonDict, node_id: str) -> bool:
    payload = event.get("payload", {})
    for target in payload.get("targets", []):
        if str(target.get("id", "")) == node_id:
            return True
    for raw_effect in payload.get("effects", []):
        for key in ("target", "source", "from", "to"):
            if _node_id(raw_effect.get(key, "")) == node_id:
                return True
    return False


def _record(kind: str, payload: JsonDict, text: object) -> JsonDict:
    return {
        "kind": kind,
        "text": str(text),
        "payload": json_copy(payload),
    }


def _rank_records(query: str, records: list[JsonDict], limit: int) -> list[JsonDict]:
    terms = _terms(query)
    if not terms:
        return []
    ranked: list[JsonDict] = []
    for index, record in enumerate(records):
        haystack = _terms(f"{record.get('kind', '')} {record.get('text', '')} {record.get('payload', '')}")
        term_score = sum(1 for term in terms if term in haystack)
        if term_score <= 0:
            continue
        item = json_copy(record)
        payload = _dict(item.get("payload"))
        score = (
            float(term_score)
            + _importance(payload) * 0.25
            + _payload_credibility(payload) * 0.25
            + (0.5 if payload.get("kind") == "memory_summary" else 0.0)
        )
        item["score"] = score
        item["rank"] = index
        ranked.append(item)
    ranked.sort(key=lambda item: (-float(item["score"]), int(item["rank"])))
    return ranked[:limit]


def _terms(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text))
    return {part for part in normalized.split() if part}


def _top_terms(text: str, limit: int) -> list[str]:
    counts: dict[str, int] = {}
    for term in _terms(text):
        if len(term) < 3:
            continue
        counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ranked[: max(limit, 0)]]


def _apply_retention_floor(
    older: list[JsonDict],
    retention_importance_floor: float | None,
) -> tuple[list[JsonDict], list[JsonDict]]:
    if retention_importance_floor is None:
        return older, []
    floor = float(retention_importance_floor)
    retained = [item for item in older if _importance(item) >= floor]
    forgotten = [item for item in older if _importance(item) < floor]
    if not retained and older:
        survivor = max(older, key=_memory_sort_key)
        retained = [survivor]
        forgotten = [item for item in older if item is not survivor]
    return retained, forgotten


def _source_credibility(sources: list[str], source_credibility: dict[str, float]) -> JsonDict:
    return {
        source: round(_clamp(float(source_credibility.get(source, 0.5)), 0.0, 1.0), 4)
        for source in sources
    }


def _average_credibility(memories: list[JsonDict], source_credibility: dict[str, float]) -> float:
    if not memories:
        return 0.0
    values = [
        _payload_credibility(memory, source_credibility)
        for memory in memories
    ]
    return round(sum(values) / len(values), 4)


def _contradictions(memories: list[JsonDict]) -> list[JsonDict]:
    claims: dict[str, dict[str, list[JsonDict]]] = {}
    for memory in memories:
        claim_key = str(memory.get("claim_key", memory.get("subject", ""))).strip()
        if not claim_key:
            continue
        if "claim_value" in memory:
            claim_value = memory.get("claim_value")
        elif "value" in memory:
            claim_value = memory.get("value")
        else:
            continue
        value_key = str(claim_value)
        claims.setdefault(claim_key, {}).setdefault(value_key, []).append(memory)

    contradictions: list[JsonDict] = []
    for claim_key, values in sorted(claims.items()):
        if len(values) <= 1:
            continue
        contradictions.append(
            {
                "claim_key": claim_key,
                "values": [
                    {
                        "value": value,
                        "count": len(items),
                        "sources": sorted({str(item.get("source", "unknown")) for item in items}),
                    }
                    for value, items in sorted(values.items())
                ],
            }
        )
    return contradictions


def _importance(payload: JsonDict) -> float:
    value = payload.get("importance", 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _payload_credibility(payload: JsonDict, source_credibility: dict[str, float] | None = None) -> float:
    if isinstance(payload.get("credibility"), (int, float)):
        return _clamp(float(payload["credibility"]), 0.0, 1.0)
    if isinstance(payload.get("average_credibility"), (int, float)):
        return _clamp(float(payload["average_credibility"]), 0.0, 1.0)
    if isinstance(payload.get("source_credibility"), (int, float)):
        return _clamp(float(payload["source_credibility"]), 0.0, 1.0)
    source = str(payload.get("source", ""))
    if source_credibility and source in source_credibility:
        return _clamp(float(source_credibility[source]), 0.0, 1.0)
    return 0.5


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _memory_text(memory: JsonDict) -> str:
    return str(memory.get("text") or memory.get("summary") or memory.get("kind") or "").strip()


def _memory_sort_key(memory: JsonDict) -> tuple[float, int, str]:
    return (
        float(memory.get("importance", 0.0) or 0.0),
        int(memory.get("tick", 0) or 0),
        _memory_text(memory),
    )


def _is_ai_pressure_payload(payload: JsonDict, raw_effect: JsonDict) -> bool:
    actor_type = str(payload.get("actor_type", ""))
    if actor_type == "agent":
        return True
    source = str(raw_effect.get("source", payload.get("source", "")))
    return source.startswith("deterministic-") or source.startswith("agent")


def _thought_record(event: JsonDict, raw_effect: JsonDict, payload: JsonDict) -> JsonDict:
    node_id = _node_id(raw_effect.get("target", raw_effect.get("node_id", "")))
    text = str(raw_effect.get("text", "")).strip()
    if not node_id or not text:
        return {}
    return {
        "tick": event["tick"],
        "sequence": event["sequence"],
        "node_id": node_id,
        "text": text,
        "source": raw_effect.get("source", payload.get("source", "")),
        "origin": raw_effect.get("origin", ""),
    }


def _ai_pressure_trace(
    event: JsonDict,
    raw_effect: JsonDict,
    payload: JsonDict,
    thoughts_by_node: dict[str, list[JsonDict]],
) -> JsonDict:
    node_id = _node_id(raw_effect.get("target", raw_effect.get("node_id", "")))
    rule = str(raw_effect.get("rule", "")).strip()
    if not node_id or not rule:
        return {}
    return {
        "tick": event["tick"],
        "sequence": event["sequence"],
        "node_id": node_id,
        "thought": _latest_thought(thoughts_by_node.get(node_id, []), event["sequence"]),
        "pressure": {
            "rule": rule,
            "weight": raw_effect.get("weight", 0.0),
            "ttl": raw_effect.get("ttl", 0),
            "source": raw_effect.get("source", payload.get("source", "")),
            "origin": raw_effect.get("origin", ""),
            "reason": raw_effect.get("reason", ""),
            "action": raw_effect.get(
                "expected_action", raw_effect.get("action", "")
            ),
            "pressure_id": raw_effect.get("pressure_id", ""),
            "provider_job_id": raw_effect.get("provider_job_id", ""),
            "option_id": raw_effect.get("option_id", ""),
            "source_tick": raw_effect.get("source_tick", event["tick"]),
            "applied_tick": raw_effect.get("applied_tick", event["tick"]),
            "observation_deadline_tick": raw_effect.get(
                "observation_deadline_tick"
            ),
        },
        "matched": False,
        "status": "unmatched_terminal",
        "action": {},
    }


def _latest_thought(thoughts: list[JsonDict], sequence: int) -> JsonDict:
    candidates = [thought for thought in thoughts if int(thought.get("sequence", 0)) <= int(sequence)]
    return json_copy(candidates[-1]) if candidates else {}


def _grounded_action_record(event: JsonDict) -> JsonDict:
    payload = event.get("payload", {})
    if payload.get("actor_type") not in {"node", "person"} or not payload.get("action"):
        return {}
    return {
        "tick": event["tick"],
        "sequence": event["sequence"],
        "node_id": str(payload.get("actor_id", "")),
        "action": payload.get("action", ""),
        "summary": payload.get("summary", ""),
        "source": payload.get("source", ""),
        "caused_by_pressure_ids": _string_list(
            payload.get("caused_by_pressure_ids")
        ),
        "caused_by_provider_job_ids": _string_list(
            payload.get("caused_by_provider_job_ids")
        ),
    }


def _match_ai_action(action: JsonDict, traces: list[JsonDict], window: int, by_node: dict[str, JsonDict]) -> None:
    for trace in traces:
        if trace["matched"]:
            continue
        if trace["node_id"] != action["node_id"]:
            continue
        if action["sequence"] <= trace["sequence"]:
            continue
        latency = int(action["tick"]) - int(trace["tick"])
        if latency < 0:
            continue
        pressure_id = str(trace["pressure"].get("pressure_id", ""))
        if pressure_id:
            if pressure_id not in action["caused_by_pressure_ids"]:
                continue
        else:
            if action["caused_by_pressure_ids"] or latency > window:
                continue
            expected_action = str(trace["pressure"].get("action", ""))
            if expected_action and expected_action != str(action["action"]):
                continue
            if not expected_action and not _action_matches_rule(
                str(action["action"]),
                str(action["summary"]),
                str(trace["pressure"]["rule"]),
            ):
                continue
        trace["matched"] = True
        trace["status"] = "matched"
        trace["latency_ticks"] = latency
        trace["action"] = json_copy(action)
        _node_summary(by_node, trace["node_id"])["matched_pressures"] += 1
        return


def _node_summary(by_node: dict[str, JsonDict], node_id: str) -> JsonDict:
    if node_id not in by_node:
        by_node[node_id] = {
            "thoughts": 0,
            "pressures": 0,
            "actions": 0,
            "matched_pressures": 0,
            "unmatched_pressures": 0,
            "pending_observation": 0,
        }
    return by_node[node_id]


def _node_id(value: Any) -> str:
    text = str(value)
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _action_matches_rule(action: str, summary: str, rule: str) -> bool:
    text = f"{action} {summary}".lower()
    rule_text = rule.lower()
    if rule_text and rule_text in text:
        return True
    aliases = {
        "combat": ["combat", "attack", "combat_attack", "攻击", "战斗"],
        "collaboration": ["collaboration", "collaborate", "合作", "协作"],
        "economic_exchange": ["economic_exchange", "market_exchange", "trade", "交易", "经济交换"],
        "infection": ["infection", "infect", "infection_spread", "感染"],
        "logistics": ["logistics", "logistics_transfer", "supply", "transport", "调拨", "补给", "物流"],
        "move": ["move", "movement", "移动"],
        "movement": ["move", "movement", "移动"],
        "migration": ["migration", "migrate", "迁徙", "迁移"],
        "organization_decision": ["organization_decision", "decision", "组织决策"],
        "production": ["production", "produce", "manufacture", "生产", "产能"],
        "quarantine": ["quarantine", "quarantine_policy", "隔离"],
        "移动": ["move", "移动"],
        "resource_transfer": ["resource_transfer", "transfer", "转移"],
        "science_publish": ["science_publish", "publish", "publication", "发表"],
        "social_spread": ["social_spread", "influence", "spread", "传播", "舆论"],
        "transfer": ["resource_transfer", "transfer", "转移"],
        "资源转移": ["resource_transfer", "transfer", "转移"],
        "attack": ["attack", "攻击"],
    }
    return any(alias in text for alias in aliases.get(rule, []))


def _observation_deadline(pressure: JsonDict) -> int | None:
    value = pressure.get("observation_deadline_tick")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
