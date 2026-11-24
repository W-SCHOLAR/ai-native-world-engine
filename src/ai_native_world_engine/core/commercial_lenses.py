"""Commercial relationship lens providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .feedback import WorldEffect, effect
from .providers import ProviderContext, ProviderOutput
from .world import World, WorldNode


JsonDict = dict[str, Any]

COMMERCIAL_LENS_ORIGIN = "commercial_relationship_lens"


@dataclass(frozen=True, slots=True)
class CommercialLens:
    id: str
    label: str
    organization_keywords: tuple[str, ...]
    member_keywords: tuple[str, ...]
    relation: str
    rule: str
    message: str

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "label": self.label,
            "organization_keywords": list(self.organization_keywords),
            "member_keywords": list(self.member_keywords),
            "relation": self.relation,
            "rule": self.rule,
            "message": self.message,
        }


COMMERCIAL_LENSES: tuple[CommercialLens, ...] = (
    CommercialLens(
        id="organization_collaboration",
        label="Organization Collaboration",
        organization_keywords=("science", "health", "civic", "humanitarian"),
        member_keywords=("coordination", "operations", "planning", "communications"),
        relation="coordination",
        rule="move",
        message="协作透镜正在把跨组织节奏转成可审计压力。",
    ),
    CommercialLens(
        id="risk_public_opinion",
        label="Risk And Public Opinion",
        organization_keywords=("media", "security", "civic", "incident"),
        member_keywords=("communications", "security", "analysis", "ethics"),
        relation="trust",
        rule="move",
        message="风险舆情透镜正在追踪信任、沟通和事件响应压力。",
    ),
    CommercialLens(
        id="resource_supply",
        label="Resource Supply",
        organization_keywords=("humanitarian", "infrastructure", "health", "response"),
        member_keywords=("logistics", "supply", "field", "operations"),
        relation="dependency",
        rule="resource_transfer",
        message="资源供给透镜正在识别物流、依赖和分发压力。",
    ),
    CommercialLens(
        id="market_competition",
        label="Market Competition",
        organization_keywords=("science", "technology", "finance", "standards"),
        member_keywords=("research", "data", "finance", "standards"),
        relation="competition",
        rule="move",
        message="市场竞争透镜正在比较创新、资本和标准化压力。",
    ),
    CommercialLens(
        id="governance_compliance",
        label="Governance Compliance",
        organization_keywords=("policy", "standards", "security", "civic"),
        member_keywords=("policy", "ethics", "standards", "security"),
        relation="governance_pressure",
        rule="move",
        message="治理合规透镜正在把政策、伦理和审计约束写入压力层。",
    ),
)


class DeterministicCommercialLensProvider:
    """Deterministic provider for one commercial relationship lens."""

    def __init__(self, lens_id: str, max_targets: int = 6) -> None:
        self.lens = commercial_lens(lens_id)
        self.max_targets = int(max_targets)
        self.name = f"deterministic-commercial-lens:{self.lens.id}"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        targets = _select_targets(context.world, self.lens, self.max_targets)
        effects: list[WorldEffect] = []
        for index, node in enumerate(targets):
            effects.extend(_lens_effects(context.world, self.lens, node, index, self.name))
        return ProviderOutput(
            source=self.name,
            summary=f"{self.lens.label} lens emitted pressure for {len(targets)} nodes",
            effects=effects,
            metadata={
                "provider_tick": context.tick,
                "commercial_lens": {
                    "id": self.lens.id,
                    "label": self.lens.label,
                    "target_nodes": [node.id for node in targets],
                    "effect_count": len(effects),
                },
            },
        )


def commercial_lens(lens_id: str) -> CommercialLens:
    for lens in COMMERCIAL_LENSES:
        if lens.id == lens_id:
            return lens
    raise ValueError(f"unknown commercial lens: {lens_id}")


def commercial_lens_ids() -> list[str]:
    return [lens.id for lens in COMMERCIAL_LENSES]


def _select_targets(world: World, lens: CommercialLens, max_targets: int) -> list[WorldNode]:
    members = [
        node
        for node in world.nodes.values()
        if node.attributes.get("agent_layer") == "relationship_network_member"
        and _matches_keywords(str(node.attributes.get("role", "")), lens.member_keywords)
    ]
    if not members:
        org_ids = {
            node.id
            for node in world.nodes.values()
            if node.type == "organization"
            and _matches_keywords(
                f"{node.name} {node.attributes.get('organization_kind', '')}",
                lens.organization_keywords,
            )
        }
        members = [
            node
            for node in world.nodes.values()
            if node.attributes.get("agent_layer") == "relationship_network_member"
            and node.attributes.get("parent_network") in org_ids
        ]
    if not members:
        members = [
            node
            for node in world.nodes.values()
            if node.attributes.get("agent_layer") == "relationship_network_member"
        ]
    members.sort(key=lambda item: (str(item.attributes.get("parent_network", "")), item.id))
    return members[: max(max_targets, 0)]


def _lens_effects(world: World, lens: CommercialLens, node: WorldNode, index: int, source: str) -> list[WorldEffect]:
    parent_id = str(node.attributes.get("parent_network", ""))
    parent_name = world.node(parent_id).name if parent_id and world.has_node(parent_id) else "network"
    common = {
        "origin": COMMERCIAL_LENS_ORIGIN,
        "lens_id": lens.id,
        "lens_label": lens.label,
        "lens_target": parent_id,
    }
    return [
        effect(
            "thought_bubble_add",
            target=f"node:{node.id}",
            text=f"{lens.message} {node.name} 正在读取 {parent_name} 的专业信号。",
            source=source,
            salience=0.5,
            ttl=4.0,
            delay=round(index * 0.5, 3),
            **common,
        ),
        effect(
            "rule_pressure_add",
            target=f"node:{node.id}",
            rule=lens.rule,
            weight=0.32,
            ttl=3,
            source=source,
            reason=f"{lens.label} lens pressure",
            **common,
        ),
        effect(
            "memory_add",
            target=f"node:{node.id}",
            text=f"{lens.label}: {lens.message}",
            source=source,
            importance=0.42,
            **common,
        ),
        effect(
            "relationship_delta",
            source=f"node:{node.id}",
            target=f"node:{parent_id}",
            relation=lens.relation,
            delta=0.06,
            ttl=6,
            source_label=source,
            reason=f"{lens.label} lens updated {parent_name}",
            **common,
        ),
    ]


def _matches_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)
