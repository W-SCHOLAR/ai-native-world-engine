"""Agent provider protocols and deterministic baseline providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock
from time import perf_counter
from typing import Any, Protocol

from .feedback import WorldEffect, effect
from .key_character_continuity import KeyCharacterContinuityApplier
from .pressure_grounding import rule_pressure_is_groundable
from .relationship_round import ACTIVE_NODE_LIMIT, RelationshipNodeUpdate, RelationshipRoundApplier
from .world import World, WorldNode


JsonDict = dict[str, Any]


class ProviderCancelled(RuntimeError):
    """A Provider invocation was cooperatively canceled by its owner."""


class ProviderBudgetExhausted(RuntimeError):
    """No further billable transport attempts may be started for this Run."""


class ProviderAttemptBudget:
    """Thread-safe Run-scoped cap shared by concurrent provider jobs."""

    def __init__(
        self,
        limit: int = 0,
        used: int = 0,
        max_prompt_tokens: int = 0,
        max_completion_tokens: int = 0,
        max_estimated_cost: float = 0.0,
        completion_tokens: int = 0,
        prompt_tokens: int = 0,
        estimated_cost: float = 0.0,
    ) -> None:
        self.limit = max(int(limit), 0)
        self._used = max(int(used), 0)
        self.max_prompt_tokens = max(int(max_prompt_tokens), 0)
        self.max_completion_tokens = max(int(max_completion_tokens), 0)
        self.max_estimated_cost = max(float(max_estimated_cost), 0.0)
        self._completion_tokens = max(int(completion_tokens), 0)
        self._prompt_tokens = max(int(prompt_tokens), 0)
        self._estimated_cost = max(float(estimated_cost), 0.0)
        self._reserved_completion_tokens = 0
        self._reserved_prompt_tokens = 0
        self._reserved_estimated_cost = 0.0
        self._lock = Lock()

    def reserve(
        self,
        max_prompt_tokens: int = 0,
        max_completion_tokens: int = 0,
        estimated_cost: float = 0.0,
    ) -> int:
        with self._lock:
            if self.limit and self._used >= self.limit:
                raise ProviderBudgetExhausted(
                    f"provider transport-attempt budget exhausted ({self.limit})"
                )
            reserved_prompt = max(int(max_prompt_tokens), 0)
            reserved_completion = max(int(max_completion_tokens), 0)
            reserved_cost = max(float(estimated_cost), 0.0)
            if self.max_prompt_tokens and self._prompt_tokens + self._reserved_prompt_tokens + reserved_prompt > self.max_prompt_tokens:
                raise ProviderBudgetExhausted("provider prompt-token budget exhausted")
            if self.max_completion_tokens and self._completion_tokens + self._reserved_completion_tokens + reserved_completion > self.max_completion_tokens:
                raise ProviderBudgetExhausted("provider completion-token budget exhausted")
            if self.max_estimated_cost and self._estimated_cost + self._reserved_estimated_cost + reserved_cost > self.max_estimated_cost:
                raise ProviderBudgetExhausted("provider estimated-cost budget exhausted")
            self._used += 1
            self._reserved_prompt_tokens += reserved_prompt
            self._reserved_completion_tokens += reserved_completion
            self._reserved_estimated_cost += reserved_cost
            return self._used

    def record_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost: float = 0.0,
        reserved_prompt_tokens: int = 0,
        reserved_completion_tokens: int = 0,
        reserved_estimated_cost: float = 0.0,
    ) -> None:
        with self._lock:
            self._reserved_prompt_tokens = max(
                self._reserved_prompt_tokens - max(int(reserved_prompt_tokens), 0), 0
            )
            self._reserved_completion_tokens = max(
                self._reserved_completion_tokens - max(int(reserved_completion_tokens), 0), 0
            )
            self._reserved_estimated_cost = max(
                self._reserved_estimated_cost - max(float(reserved_estimated_cost), 0.0), 0.0
            )
            self._completion_tokens += max(int(completion_tokens), 0)
            self._estimated_cost += max(float(estimated_cost), 0.0)
            self._prompt_tokens += max(int(prompt_tokens), 0)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "limit": self.limit,
                "used": self._used,
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "estimated_cost": self._estimated_cost,
            }


class CancellationToken:
    """Thread-safe cooperative cancellation and deadline signal."""

    def __init__(self, deadline_at: float | None = None) -> None:
        self._event = Event()
        self._reason = ""
        self.deadline_at = deadline_at

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (
            self.deadline_at is not None and perf_counter() >= self.deadline_at
        )

    @property
    def reason(self) -> str:
        if self._event.is_set():
            return self._reason or "provider canceled"
        if self.deadline_at is not None and perf_counter() >= self.deadline_at:
            return "provider deadline exceeded"
        return ""

    def cancel(self, reason: str = "provider canceled") -> None:
        self._reason = str(reason)
        self._event.set()

    def remaining_seconds(self) -> float | None:
        if self.deadline_at is None:
            return None
        return max(self.deadline_at - perf_counter(), 0.0)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ProviderCancelled(self.reason)


@dataclass(slots=True)
class ProviderContext:
    world: World
    tick: int
    snapshot: JsonDict
    params: JsonDict = field(default_factory=dict)
    cancellation: CancellationToken | None = None
    attempt_budget: ProviderAttemptBudget | None = None


@dataclass(slots=True)
class ProviderOutput:
    source: str
    summary: str
    effects: list[WorldEffect] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        result: JsonDict = dict(self.metadata)
        result.update(
            {
                "source": self.source,
                "summary": self.summary,
                "effects": [item.to_dict() for item in self.effects],
            }
        )
        return result


class AgentProvider(Protocol):
    name: str

    def observe(self, context: ProviderContext) -> ProviderOutput:
        ...


class DeterministicPressureProvider:
    """Baseline provider that emits grounded pressure for visible movement goals."""

    name = "deterministic-pressure"

    def __init__(
        self,
        rule: str = "move",
        weight: float = 0.5,
        ttl: int = 2,
        emit_thoughts: bool = True,
    ) -> None:
        self.rule = rule
        self.weight = float(weight)
        self.ttl = int(ttl)
        self.emit_thoughts = emit_thoughts

    def observe(self, context: ProviderContext) -> ProviderOutput:
        effects: list[WorldEffect] = []
        for node in context.world.nodes.values():
            if node.movement_target is None or node.movement_speed <= 0:
                continue
            effects.append(
                effect(
                    "rule_pressure_add",
                    target=f"node:{node.id}",
                    rule=self.rule,
                    weight=self.weight,
                    ttl=self.ttl,
                    source=self.name,
                    reason="node has an active movement target",
                )
            )
            if self.emit_thoughts:
                effects.append(
                    effect(
                        "thought_bubble_add",
                        target=f"node:{node.id}",
                        text="I should keep moving toward the target.",
                        source=self.name,
                        salience=0.35,
                    )
                )
        return ProviderOutput(
            source=self.name,
            summary="deterministic provider emitted movement pressure",
            effects=effects,
            metadata={"provider_tick": context.tick, "provider_runtime": _runtime_metadata(self.name)},
        )


class DeterministicRelationshipRoundProvider:
    """Deterministic relationship-network round provider for visible time-sliced output."""

    name = "deterministic-relationship-round"

    def __init__(self, graph_type: str = "relationship_network", rule: str = "move") -> None:
        self.graph_type = graph_type
        self.rule = rule
        self.applier = RelationshipRoundApplier()

    def observe(self, context: ProviderContext) -> ProviderOutput:
        updates: list[RelationshipNodeUpdate] = []
        packet = context.params.get("agent_context_packet", {})
        raw_candidates = packet.get("active_candidates", []) if isinstance(packet, dict) else []
        candidate_ids = [
            str(item.get("id", ""))
            for item in raw_candidates
            if isinstance(item, dict) and context.world.has_node(str(item.get("id", "")))
        ]
        if candidate_ids:
            candidates = [context.world.node(node_id) for node_id in candidate_ids]
        else:
            candidates = [
                node
                for node in context.world.nodes.values()
                if node.attributes.get("agent_layer") == "relationship_network_member"
                or node.type in {"person", "organization_member"}
            ]
            candidates.sort(key=lambda node: node.id)
        for index, node in enumerate(candidates[: ACTIVE_NODE_LIMIT + 3]):
            updates.append(
                RelationshipNodeUpdate(
                    node_id=node.id,
                    thought=f"{node.name} is reading the network pressure and deciding how to coordinate with nearby members.",
                    thought_bubbles=_relationship_thought_bubbles(node.name),
                    action_tendencies=[
                        {
                            "rule": self.rule,
                            "weight": round(0.42 + (index % 4) * 0.06, 3),
                            "ttl": 3,
                            "reason": "relationship round selected this node as active",
                        }
                    ],
                )
            )
        result = self.applier.build_effects(
            context.world,
            updates,
            source=self.name,
            memory_prefix="relationship round",
            expected_node_ids=candidate_ids or None,
            propagation_node_ids=[
                str(item.get("id", ""))
                for item in (packet.get("coverage_nodes", []) if isinstance(packet, dict) else [])
                if isinstance(item, dict)
            ] or None,
        )
        return ProviderOutput(
            source=self.name,
            summary=f"relationship round selected {len(result.active_node_ids)} active nodes and {len(result.ripple_node_ids)} ripple nodes",
            effects=result.effects,
            metadata={
                "provider_tick": context.tick,
                "provider_runtime": _runtime_metadata(self.name),
                "graph_type": self.graph_type,
                "relationship_round": result.to_metadata(),
            },
        )


def _relationship_thought_bubbles(node_name: str) -> list[JsonDict]:
    return [
        {"text": f"{node_name} notices the network pressure rising."},
        {"text": f"{node_name} checks signals from nearby members."},
        {"text": f"{node_name} compares trust across the relationship graph."},
        {"text": f"{node_name} weighs the risk of acting alone."},
        {"text": f"{node_name} identifies partners for coordination."},
        {"text": f"{node_name} prepares a coordinated response."},
    ]


class DeterministicKeyCharacterContinuityProvider:
    """Deterministic key-character continuity provider without survival fields."""

    name = "deterministic-key-character-continuity"

    def __init__(self, grounded_rule: str = "move") -> None:
        self.grounded_rule = grounded_rule
        self.applier = KeyCharacterContinuityApplier()

    def observe(self, context: ProviderContext) -> ProviderOutput:
        packet = context.params.get("agent_context_packet", {})
        target_node_ids = [
            str(item.get("id", ""))
            for item in (packet.get("active_candidates", []) if isinstance(packet, dict) else [])
            if isinstance(item, dict) and str(item.get("id", ""))
        ]
        result = self.applier.build_effects(
            context.world,
            source=self.name,
            grounded_rule=self.grounded_rule,
            target_node_ids=target_node_ids or None,
        )
        return ProviderOutput(
            source=self.name,
            summary=(
                f"key character continuity activated {len(result.active_character_ids)} characters "
                f"and influenced {len(result.influence_node_ids)} network members"
            ),
            effects=result.effects,
            metadata={
                "provider_tick": context.tick,
                "provider_runtime": _runtime_metadata(self.name),
                "key_character_continuity": result.to_metadata(),
            },
        )


class DeterministicEnterpriseAgentProvider:
    """Enterprise demo provider combining relationship rounds and key-character continuity."""

    name = "deterministic-enterprise-agent"

    def __init__(self, rule: str = "move") -> None:
        self.relationship_provider = DeterministicRelationshipRoundProvider(rule=rule)
        self.key_character_provider = DeterministicKeyCharacterContinuityProvider(grounded_rule=rule)

    def observe(self, context: ProviderContext) -> ProviderOutput:
        relationship = self.relationship_provider.observe(context)
        key_character = self.key_character_provider.observe(
            ProviderContext(
                world=context.world,
                tick=context.tick,
                snapshot=context.snapshot,
                params={
                    key: value
                    for key, value in context.params.items()
                    if key != "agent_context_packet"
                },
            )
        )
        return ProviderOutput(
            source=self.name,
            summary=f"{relationship.summary}; {key_character.summary}",
            effects=[*relationship.effects, *key_character.effects],
            metadata={
                "provider_tick": context.tick,
                "provider_runtime": _runtime_metadata(self.name),
                "relationship_round": relationship.metadata.get("relationship_round", {}),
                "key_character_continuity": key_character.metadata.get("key_character_continuity", {}),
            },
        )


class DeterministicHighPressureResponseProvider:
    """Deterministic response provider for scheduler-triggered high-pressure nodes."""

    name = "deterministic-high-pressure-response"

    def __init__(self, fallback_rule: str = "move") -> None:
        self.fallback_rule = fallback_rule

    def observe(self, context: ProviderContext) -> ProviderOutput:
        packet = context.params.get("agent_context_packet", {})
        candidates = packet.get("active_candidates", []) if isinstance(packet, dict) else []
        effects: list[WorldEffect] = []
        active_ids: list[str] = []
        grounded_pressure_ids: list[str] = []
        for index, candidate in enumerate(candidates[:8] if isinstance(candidates, list) else []):
            if not isinstance(candidate, dict):
                continue
            node_id = str(candidate.get("id", ""))
            if not node_id or not context.world.has_node(node_id):
                continue
            node = context.world.node(node_id)
            rule = _dominant_rule(node) or self.fallback_rule
            active_ids.append(node_id)
            effects.extend(
                [
                    effect(
                        "thought_bubble_add",
                        target=f"node:{node_id}",
                        text=f"{node.name} 正在响应高压信号并请求规则层裁决。",
                        source=self.name,
                        salience=0.74,
                        ttl=4.0,
                        delay=round(index * 0.25, 3),
                        origin="high_pressure_trigger",
                    ),
                    effect(
                        "memory_add",
                        target=f"node:{node_id}",
                        text=f"high pressure response scheduled for rule {rule}",
                        source=self.name,
                        importance=0.62,
                    ),
                ]
            )
            if rule_pressure_is_groundable(context.world, node_id, rule):
                grounded_pressure_ids.append(node_id)
                effects.append(
                    effect(
                        "rule_pressure_add",
                        target=f"node:{node_id}",
                        rule=rule,
                        weight=0.38,
                        ttl=2,
                        source=self.name,
                        reason="scheduler high-pressure response",
                        origin="high_pressure_trigger",
                    )
                )
        return ProviderOutput(
            source=self.name,
            summary=(
                f"high-pressure response processed {len(active_ids)} nodes "
                f"and emitted grounded pressure for {len(grounded_pressure_ids)} nodes"
            ),
            effects=effects,
            metadata={
                "provider_tick": context.tick,
                "provider_runtime": _runtime_metadata(self.name),
                "high_pressure_response": {
                    "active_node_ids": active_ids,
                    "active_node_count": len(active_ids),
                    "grounded_pressure_node_ids": grounded_pressure_ids,
                    "grounded_pressure_node_count": len(grounded_pressure_ids),
                },
            },
        )


def _runtime_metadata(provider: str) -> JsonDict:
    return {
        "provider": provider,
        "attempts": 1,
        "estimated_cost": 0.0,
        "cost_unit": "credits",
        "latency_ms": 0.0,
    }


def _dominant_rule(node: WorldNode) -> str:
    if not node.rule_pressures:
        return ""
    ranked = sorted(
        node.rule_pressures,
        key=lambda item: (
            -float(item.get("weight", 0.0) or 0.0),
            -int(item.get("ttl", 1) or 1),
            str(item.get("rule", "")),
        ),
    )
    return str(ranked[0].get("rule", ""))
