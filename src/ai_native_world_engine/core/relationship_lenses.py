"""AI-Isekai relationship lens providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .feedback import WorldEffect, effect
from .providers import ProviderContext, ProviderOutput
from .world import World, WorldNode


JsonDict = dict[str, Any]

RELATIONSHIP_LENS_ORIGIN = "ai_isekai_relationship_lens"


@dataclass(frozen=True, slots=True)
class RelationshipLens:
    id: str
    label: str
    keywords: tuple[str, ...]
    relation: str
    rule: str
    message: str

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "label": self.label,
            "keywords": list(self.keywords),
            "relation": self.relation,
            "rule": self.rule,
            "message": self.message,
        }


RELATIONSHIP_LENSES: tuple[RelationshipLens, ...] = (
    RelationshipLens("tribe", "Tribe Composite Graph", ("leader", "coordination", "network", "member"), "authority", "move", "综合关系网正在重读群体策略。"),
    RelationshipLens("family", "Family Graph Lens", ("family", "care", "support", "humanitarian"), "care", "collaborate", "家庭/照料透镜正在加深照料与承诺压力。"),
    RelationshipLens("war", "War Graph Lens", ("security", "conflict", "risk", "defense"), "fear", "combat", "战争透镜正在识别恐惧、威慑与防御压力。"),
    RelationshipLens("ecology", "Ecology Graph Lens", ("health", "field", "risk", "environment"), "danger", "quarantine", "生态透镜正在追踪危险、接触和恢复压力。"),
    RelationshipLens("territory", "Territory Graph Lens", ("infrastructure", "route", "field", "operations"), "route_memory", "migration", "领地/路线透镜正在解释边界、路线和迁徙压力。"),
    RelationshipLens("production", "Production Graph Lens", ("supply", "logistics", "research", "production"), "dependency", "production", "生产透镜正在把物资、工艺和交换需求写入压力层。"),
)


class DeterministicRelationshipLensProvider:
    def __init__(self, lens_id: str, max_targets: int = 6) -> None:
        self.lens = relationship_lens(lens_id)
        self.max_targets = int(max_targets)
        self.name = f"deterministic-relationship-lens:{self.lens.id}"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        targets = _select_targets(context.world, self.lens, self.max_targets)
        effects: list[WorldEffect] = []
        for index, node in enumerate(targets):
            effects.extend(_lens_effects(context.world, self.lens, node, index, self.name))
        return ProviderOutput(
            source=self.name,
            summary=f"{self.lens.label} emitted AI-Isekai relationship pressure for {len(targets)} nodes",
            effects=effects,
            metadata={
                "provider_tick": context.tick,
                "relationship_lens": {
                    "id": self.lens.id,
                    "label": self.lens.label,
                    "target_nodes": [node.id for node in targets],
                    "effect_count": len(effects),
                },
            },
        )


def relationship_lens(lens_id: str) -> RelationshipLens:
    for lens in RELATIONSHIP_LENSES:
        if lens.id == lens_id:
            return lens
    raise ValueError(f"unknown relationship lens: {lens_id}")


def relationship_lens_ids(include_tribe: bool = True) -> list[str]:
    return [lens.id for lens in RELATIONSHIP_LENSES if include_tribe or lens.id != "tribe"]


def _select_targets(world: World, lens: RelationshipLens, max_targets: int) -> list[WorldNode]:
    candidates = [
        node
        for node in world.nodes.values()
        if node.attributes.get("agent_layer") == "relationship_network_member"
        and _matches(node, lens)
    ]
    if not candidates:
        candidates = [
            node
            for node in world.nodes.values()
            if node.attributes.get("agent_layer") == "relationship_network_member"
        ]
    candidates.sort(key=lambda item: (-_pressure_score(item), str(item.attributes.get("parent_network", "")), item.id))
    return candidates[: max(max_targets, 0)]


def _lens_effects(world: World, lens: RelationshipLens, node: WorldNode, index: int, source: str) -> list[WorldEffect]:
    parent_id = str(node.attributes.get("parent_network", ""))
    target_ref = f"node:{parent_id}" if parent_id and world.has_node(parent_id) else f"node:{node.id}"
    common = {
        "origin": RELATIONSHIP_LENS_ORIGIN,
        "lens_id": lens.id,
        "lens_label": lens.label,
    }
    return [
        effect(
            "thought_bubble_add",
            target=f"node:{node.id}",
            text=f"{lens.message}{node.name} 正在重新解释身边关系。",
            source=source,
            salience=0.58,
            ttl=4.0,
            delay=round(index * 0.45, 3),
            **common,
        ),
        effect(
            "rule_pressure_add",
            target=f"node:{node.id}",
            rule=lens.rule,
            weight=0.34,
            ttl=4,
            source=source,
            reason=f"{lens.label} pressure",
            **common,
        ),
        effect(
            "relationship_delta",
            source=f"node:{node.id}",
            target=target_ref,
            relation=lens.relation,
            delta=0.05,
            ttl=12,
            source_label=source,
            reason=lens.message,
            **common,
        ),
        effect(
            "memory_add",
            target=f"node:{node.id}",
            text=f"{lens.label}: {lens.message}",
            source=source,
            importance=0.48,
            **common,
        ),
    ]


def _matches(node: WorldNode, lens: RelationshipLens) -> bool:
    text = f"{node.name} {node.type} {node.attributes}".lower()
    return any(keyword.lower() in text for keyword in lens.keywords)


def _pressure_score(node: WorldNode) -> float:
    return sum(float(item.get("weight", 0.0) or 0.0) for item in node.rule_pressures)
