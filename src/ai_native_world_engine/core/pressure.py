"""结构化压力模型和压力视图。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .feedback import effect
from .world import World


JsonDict = dict[str, Any]


@dataclass(slots=True)
class RulePressure:
    target: str
    rule: str
    weight: float
    ttl: int
    source: str
    reason: str = ""

    def to_effect(self) -> JsonDict:
        return effect(
            "rule_pressure_add",
            target=f"node:{self.target}",
            rule=self.rule,
            weight=self.weight,
            ttl=self.ttl,
            source=self.source,
            reason=self.reason,
        ).to_dict()


@dataclass(slots=True)
class RelationshipPressure:
    source: str
    target: str
    relation: str
    delta: float
    ttl: int
    source_label: str
    reason: str = ""

    def to_effect(self) -> JsonDict:
        return effect(
            "relationship_delta",
            source=f"node:{self.source}",
            target=f"node:{self.target}",
            relation=self.relation,
            delta=self.delta,
            ttl=self.ttl,
            source_label=self.source_label,
            reason=self.reason,
        ).to_dict()


@dataclass(slots=True)
class MemoryPressure:
    target: str
    text: str
    source: str
    importance: float = 0.0

    def to_effect(self) -> JsonDict:
        return effect(
            "memory_add",
            target=f"node:{self.target}",
            text=self.text,
            source=self.source,
            importance=self.importance,
        ).to_dict()


@dataclass(slots=True)
class KeyCharacterPressure:
    target: str
    value: JsonDict = field(default_factory=dict)

    def to_effect(self) -> JsonDict:
        return effect("key_character_state", target=f"node:{self.target}", value=self.value).to_dict()


class StructuredPressureView:
    def build(self, world: World) -> JsonDict:
        top_nodes = []
        totals = {
            "nodes_with_pressure": 0,
            "rule_pressures": 0,
            "memories": 0,
            "key_characters": 0,
            "relationship_edges": len(world.relationships),
        }
        for node in world.nodes.values():
            score = (
                sum(float(item.get("weight", 0.0)) * max(int(item.get("ttl", 1)), 1) for item in node.rule_pressures)
                + len(node.memories) * 0.2
                + (2.0 if node.key_character else 0.0)
            )
            totals["rule_pressures"] += len(node.rule_pressures)
            totals["memories"] += len(node.memories)
            if node.key_character:
                totals["key_characters"] += 1
            if score > 0:
                totals["nodes_with_pressure"] += 1
                top_nodes.append(
                    {
                        "id": node.id,
                        "name": node.name,
                        "pressure_score": round(score, 3),
                        "rule_pressures": node.rule_pressures,
                        "recent_thought": "",
                        "key_character": node.key_character,
                        "key_character_continuity": _key_character_continuity(node.key_character),
                    }
                )
        top_nodes.sort(key=lambda item: item["pressure_score"], reverse=True)
        return {"totals": totals, "top_nodes": top_nodes}


def _key_character_continuity(value: JsonDict) -> JsonDict:
    if not value:
        return {}
    influence_circle = value.get("influence_circle", [])
    influence_count = len(influence_circle) if isinstance(influence_circle, list) else int(value.get("influence_circle_count", 0) or 0)
    return {
        "status": value.get("status", ""),
        "salience_score": value.get("salience_score", 0.0),
        "goal": value.get("goal", ""),
        "current_step": value.get("current_step", ""),
        "influence_circle_count": influence_count,
    }
