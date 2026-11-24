"""Shared product-facing world intervention contracts and visibility propagation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .events import json_copy
from .feedback import WorldEffect
from .world import World


JsonDict = dict[str, Any]

WORLD_INTERVENTION_SCHEMA = "world_intervention.v1"
AUDIENCE_WORLD_INPUT_SOURCE = "audience_world_input"

WORLD_INTERVENTION_TYPES = frozenset(
    {
        "weather_change",
        "resource_change",
        "public_notice",
        "wanted_notice",
        "rumor_spread",
        "clue_injection",
        "secondary_actor_action",
        "organization_pressure",
        "event_trigger",
    }
)

INTERVENTION_VISIBILITY_MODES = frozenset(
    {"none", "direct", "public", "relationship", "location", "organization"}
)

ALLOWED_INTERVENTION_EFFECT_TYPES = frozenset(
    {
        "action_bullet_add",
        "relationship_delta",
        "resource_delta",
        "resource_transfer",
        "rule_pressure_add",
        "world_state",
    }
)

FORBIDDEN_INTERVENTION_EFFECT_TYPES = frozenset(
    {
        "key_character_state",
        "memory_add",
        "node_state",
        "thought_bubble_add",
    }
)

FORBIDDEN_INTERVENTION_OPERATIONS = frozenset(
    {
        "key_character_direct_control",
        "key_character_emotion_override",
        "key_character_memory_rewrite",
        "key_character_dialogue_forcing",
    }
)


@dataclass(frozen=True, slots=True)
class InterventionValidationReport:
    valid: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return {"valid": self.valid, "errors": list(self.errors)}


@dataclass(slots=True)
class WorldIntervention:
    id: str
    intervention_type: str
    scope: JsonDict
    payload: JsonDict
    visibility: JsonDict
    duration: int = 1
    constraints: JsonDict = field(default_factory=dict)
    source: str = AUDIENCE_WORLD_INPUT_SOURCE
    scheduled_tick: int = 0
    actor_type: str = "user"
    actor_id: str = "audience"
    action: str = "world_intervention"
    effects: list[JsonDict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        for key in ("summary", "text", "title"):
            value = str(self.payload.get(key, "")).strip()
            if value:
                return value
        return f"{self.intervention_type}:{self.id}"

    def to_dict(self) -> JsonDict:
        return {
            "schema": WORLD_INTERVENTION_SCHEMA,
            "id": self.id,
            "tick": self.scheduled_tick,
            "source": self.source,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "action": self.action,
            "summary": self.summary,
            "intervention_type": self.intervention_type,
            "scope": json_copy(self.scope),
            "payload": json_copy(self.payload),
            "visibility": json_copy(self.visibility),
            "duration": self.duration,
            "constraints": json_copy(self.constraints),
            "effects": json_copy(self.effects),
        }

    @classmethod
    def from_dict(cls, value: JsonDict) -> "WorldIntervention":
        return cls(
            id=str(value.get("id", "")),
            intervention_type=str(value.get("intervention_type", "")),
            scope=_dict(value.get("scope")),
            payload=_dict(value.get("payload")),
            visibility=_dict(value.get("visibility")),
            duration=int(value.get("duration", 1) or 1),
            constraints=_dict(value.get("constraints")),
            source=str(value.get("source", AUDIENCE_WORLD_INPUT_SOURCE)),
            scheduled_tick=int(value.get("tick", value.get("scheduled_tick", 0)) or 0),
            actor_type=str(value.get("actor_type", "user")),
            actor_id=str(value.get("actor_id", "audience")),
            action=str(value.get("action", "world_intervention")),
            effects=_dict_list(value.get("effects")),
        )


@dataclass(frozen=True, slots=True)
class CompiledWorldIntervention:
    intervention: WorldIntervention
    recipient_node_ids: tuple[str, ...]
    effects: tuple[WorldEffect, ...]

    def to_metadata(self) -> JsonDict:
        return {
            "schema": WORLD_INTERVENTION_SCHEMA,
            "id": self.intervention.id,
            "intervention_type": self.intervention.intervention_type,
            "visibility_mode": str(self.intervention.visibility.get("mode", "none")),
            "recipient_count": len(self.recipient_node_ids),
            "recipient_node_ids": list(self.recipient_node_ids),
            "duration": self.intervention.duration,
        }


class InterventionValidator:
    def validate(self, intervention: WorldIntervention) -> InterventionValidationReport:
        errors: list[str] = []
        if not intervention.id.strip():
            errors.append("intervention id cannot be empty")
        if not intervention.source.strip():
            errors.append("intervention source cannot be empty")
        if intervention.intervention_type not in WORLD_INTERVENTION_TYPES:
            errors.append(
                f"unsupported intervention type: {intervention.intervention_type}"
            )
        if intervention.scheduled_tick < 0:
            errors.append("scheduled tick cannot be negative")
        if intervention.duration < 1:
            errors.append("intervention duration must be at least one tick")

        mode = str(intervention.visibility.get("mode", "none"))
        if mode not in INTERVENTION_VISIBILITY_MODES:
            errors.append(f"unsupported visibility mode: {mode}")
        max_recipients = int(intervention.visibility.get("max_recipients", 64) or 64)
        if max_recipients < 1 or max_recipients > 256:
            errors.append("visibility max_recipients must be between 1 and 256")

        requested_operations = {
            str(item)
            for item in _list(intervention.constraints.get("requested_operations"))
            if str(item)
        }
        requested_operations.update(
            operation
            for operation in FORBIDDEN_INTERVENTION_OPERATIONS
            if intervention.constraints.get(operation) is True
        )
        forbidden_operations = sorted(
            requested_operations & FORBIDDEN_INTERVENTION_OPERATIONS
        )
        if forbidden_operations:
            errors.append(
                f"forbidden intervention operations: {', '.join(forbidden_operations)}"
            )

        for index, effect in enumerate(intervention.effects):
            effect_type = str(effect.get("type", ""))
            if effect_type in FORBIDDEN_INTERVENTION_EFFECT_TYPES:
                errors.append(
                    f"effect {index} directly controls character internals: {effect_type}"
                )
            elif effect_type not in ALLOWED_INTERVENTION_EFFECT_TYPES:
                errors.append(
                    f"effect {index} is not allowed for structured interventions: {effect_type}"
                )
        return InterventionValidationReport(not errors, tuple(errors))

    def require_valid(self, intervention: WorldIntervention) -> None:
        report = self.validate(intervention)
        if not report.valid:
            raise ValueError("; ".join(report.errors))


class InterventionVisibilityResolver:
    def resolve(self, world: World, intervention: WorldIntervention) -> list[str]:
        visibility = intervention.visibility
        mode = str(visibility.get("mode", "none"))
        max_recipients = max(
            min(int(visibility.get("max_recipients", 64) or 64), 256), 1
        )
        if mode == "none":
            return []
        if mode in {"direct", "public"}:
            requested = [
                *_string_list(visibility.get("publisher_node_ids")),
                *_string_list(visibility.get("recipient_node_ids")),
            ]
            return _existing_nodes(world, requested, max_recipients)
        if mode == "relationship":
            return self._relationship_recipients(world, visibility, max_recipients)
        if mode == "location":
            return self._location_recipients(world, visibility, max_recipients)
        if mode == "organization":
            return self._organization_recipients(world, visibility, max_recipients)
        return []

    def _relationship_recipients(
        self, world: World, visibility: JsonDict, limit: int
    ) -> list[str]:
        seeds = _existing_nodes(
            world,
            [
                *_string_list(visibility.get("seed_node_ids")),
                *_string_list(visibility.get("recipient_node_ids")),
            ],
            limit,
        )
        allowed_types = set(_string_list(visibility.get("relationship_types")))
        max_hops = max(min(int(visibility.get("max_hops", 1) or 1), 4), 0)
        result = list(seeds)
        seen = set(result)
        frontier = list(seeds)
        for _ in range(max_hops):
            next_frontier: list[str] = []
            for edge in sorted(world.relationships.values(), key=lambda item: item.key):
                if allowed_types and edge.type not in allowed_types:
                    continue
                pairs = ((edge.source, edge.target), (edge.target, edge.source))
                for source, target in pairs:
                    if (
                        source not in frontier
                        or target in seen
                        or not world.has_node(target)
                    ):
                        continue
                    seen.add(target)
                    result.append(target)
                    next_frontier.append(target)
                    if len(result) >= limit:
                        return result
            frontier = next_frontier
            if not frontier:
                break
        return result

    def _location_recipients(
        self, world: World, visibility: JsonDict, limit: int
    ) -> list[str]:
        locations = set(_string_list(visibility.get("location_node_ids")))
        requested = _string_list(visibility.get("recipient_node_ids"))
        for node in sorted(world.nodes.values(), key=lambda item: item.id):
            attributes = node.attributes
            node_locations = {
                str(attributes.get(key, ""))
                for key in (
                    "location",
                    "location_id",
                    "current_location",
                    "home_location",
                )
                if attributes.get(key)
            }
            if node.id in locations or node_locations & locations:
                requested.append(node.id)
        return _existing_nodes(world, requested, limit)

    def _organization_recipients(
        self, world: World, visibility: JsonDict, limit: int
    ) -> list[str]:
        organizations = set(_string_list(visibility.get("organization_node_ids")))
        requested = [
            *_string_list(visibility.get("recipient_node_ids")),
            *sorted(organizations),
        ]
        membership_types = {"member_of", "leads", "works_for", "belongs_to"}
        for edge in sorted(world.relationships.values(), key=lambda item: item.key):
            if edge.type in membership_types and edge.target in organizations:
                requested.append(edge.source)
        for node in sorted(world.nodes.values(), key=lambda item: item.id):
            attributes = node.attributes
            memberships = {
                str(attributes.get(key, ""))
                for key in ("organization", "organization_id", "faction", "faction_id")
                if attributes.get(key)
            }
            memberships.update(_string_list(attributes.get("organizations")))
            if memberships & organizations:
                requested.append(node.id)
        return _existing_nodes(world, requested, limit)


def compile_world_intervention(
    world: World,
    intervention: WorldIntervention,
    *,
    validator: InterventionValidator | None = None,
    resolver: InterventionVisibilityResolver | None = None,
) -> CompiledWorldIntervention:
    active_validator = validator or InterventionValidator()
    active_validator.require_valid(intervention)
    recipients = (resolver or InterventionVisibilityResolver()).resolve(
        world, intervention
    )
    visibility_mode = str(intervention.visibility.get("mode", "none"))
    receipt = {
        "schema": WORLD_INTERVENTION_SCHEMA,
        "id": intervention.id,
        "source": intervention.source,
        "intervention_type": intervention.intervention_type,
        "scheduled_tick": intervention.scheduled_tick,
        "scope": json_copy(intervention.scope),
        "visibility_mode": visibility_mode,
        "recipient_node_ids": list(recipients),
        "duration": intervention.duration,
        "constraints": json_copy(intervention.constraints),
    }
    effects = [
        WorldEffect(
            "world_state",
            {
                "field": f"world_intervention_{_safe_id(intervention.id)}",
                "value": receipt,
            },
        )
    ]
    memory_text = str(
        intervention.payload.get(
            "memory_text", intervention.payload.get("text", intervention.summary)
        )
    ).strip()
    importance = float(intervention.payload.get("importance", 0.72) or 0.72)
    for node_id in recipients:
        effects.append(
            WorldEffect(
                "memory_add",
                {
                    "target": f"node:{node_id}",
                    "text": memory_text,
                    "source": intervention.source,
                    "importance": importance,
                    "metadata": {
                        "schema": WORLD_INTERVENTION_SCHEMA,
                        "intervention_id": intervention.id,
                        "intervention_type": intervention.intervention_type,
                        "visibility_mode": visibility_mode,
                        "duration": intervention.duration,
                    },
                },
            )
        )
    effects.extend(
        WorldEffect(
            str(effect.get("type", "")),
            {key: json_copy(value) for key, value in effect.items() if key != "type"},
        )
        for effect in intervention.effects
    )
    return CompiledWorldIntervention(intervention, tuple(recipients), tuple(effects))


def is_structured_world_intervention(value: JsonDict) -> bool:
    return str(value.get("schema", "")) == WORLD_INTERVENTION_SCHEMA


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value)).strip("_")
    return normalized or "intervention"


def _existing_nodes(world: World, values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        node_id = str(value).removeprefix("node:")
        if not node_id or node_id in seen or not world.has_node(node_id):
            continue
        seen.add(node_id)
        result.append(node_id)
        if len(result) >= limit:
            break
    return result


def _string_list(value: Any) -> list[str]:
    return [
        str(item).removeprefix("node:") for item in _list(value) if str(item).strip()
    ]


def _dict(value: Any) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[JsonDict]:
    return [json_copy(item) for item in _list(value) if isinstance(item, dict)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
