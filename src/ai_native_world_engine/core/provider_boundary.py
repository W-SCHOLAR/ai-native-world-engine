"""Boundary for normalizing external provider JSON output."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from .action_grounding import (
    materialize_action_option,
    option_by_id,
    resolve_node_bound_action_option,
)
from .events import json_copy
from .feedback import WorldEffect
from .providers import ProviderOutput
from .pressure_grounding import rule_pressure_is_groundable
from .relationship_round import RelationshipRoundApplier
from .rule_registry import canonical_rule_name
from .world import World


JsonDict = dict[str, Any]

PROVIDER_OUTPUT_BOUNDARY_SCHEMA = "provider_output_boundary_v2"
RELATIONSHIP_REASON_MAX_CHARS = 8
RELATIONSHIP_EDGE_UPDATE_LIMIT = 12

ALLOWED_EXTERNAL_EFFECT_TYPES = frozenset(
    {
        "rule_pressure_add",
        "relationship_delta",
        "memory_add",
        "thought_bubble_add",
        "action_bullet_add",
        "key_character_state",
    }
)

REJECTED_DIRECT_MUTATION_EFFECT_TYPES = frozenset(
    {
        "node_position",
        "node_state",
        "world_state",
        "resource_transfer",
    }
)


@dataclass(slots=True)
class ProviderOutputBoundary:
    source: str = "external-provider"
    allowed_rule_names: set[str] = field(default_factory=set)
    allowed_relationship_types: set[str] = field(default_factory=set)
    required_active_node_count: int | None = None
    expected_node_ids: set[str] = field(default_factory=set)
    propagation_node_ids: set[str] = field(default_factory=set)
    allowed_effect_node_ids: set[str] = field(default_factory=set)
    groundable_action_options: list[JsonDict] = field(default_factory=list)
    provider_job_id: str = ""
    source_tick: int = 0

    def parse(self, world: World, raw: JsonDict) -> ProviderOutput:
        if not isinstance(raw, dict):
            raise ValueError("provider output must be a JSON object")
        raw_effects = raw.get("effects", [])
        if not isinstance(raw_effects, list):
            raise ValueError("provider output effects must be a list")

        effects = [
            self._parse_effect(world, raw_effect, index)
            for index, raw_effect in enumerate(raw_effects)
        ]
        relationship_round = self.required_active_node_count is not None
        node_updates = [
            _normalize_node_update(item, relationship_round=relationship_round)
            for item in _dict_list(raw.get("node_updates"))
        ]
        if relationship_round:
            returned_node_ids = [
                str(item.get("node_id", item.get("id", ""))) for item in node_updates
            ]
            valid_distinct_node_ids = {
                node_id
                for node_id in returned_node_ids
                if node_id and node_id in self.expected_node_ids
            }
            if (
                len(node_updates) != self.required_active_node_count
                or len(valid_distinct_node_ids) != self.required_active_node_count
            ):
                raise ValueError(
                    "relationship_round requires exactly "
                    f"{self.required_active_node_count} valid distinct active node updates; "
                    f"got {len(valid_distinct_node_ids)}"
                )
            option_node_ids = {
                str(item.get("node_id", ""))
                for item in self.groundable_action_options
                if str(item.get("node_id", "")) in self.expected_node_ids
            }
            if len(option_node_ids) < int(self.required_active_node_count or 0):
                raise ValueError(
                    "relationship_round requires at least "
                    f"{self.required_active_node_count} option-bearing active candidates; "
                    f"got {len(option_node_ids)}"
                )
            resolved_updates: list[JsonDict] = []
            action_option_repairs: list[JsonDict] = []
            for item in node_updates:
                resolved, repair = self._resolve_action_option(item)
                resolved_updates.append(resolved)
                if repair is not None:
                    action_option_repairs.append(repair)
            node_updates = resolved_updates
            missing_action_node_ids = [
                str(item.get("node_id", item.get("id", "")))
                for item in node_updates
                if not _dict_list(item.get("action_tendencies"))
            ]
            if missing_action_node_ids:
                raise ValueError(
                    "relationship_round requires one selected action for every active node; "
                    f"missing actions for {missing_action_node_ids}"
                )
        edge_updates = [
            _normalize_edge_update(item)
            for item in _dict_list(raw.get("edge_updates"))[
                :RELATIONSHIP_EDGE_UPDATE_LIMIT
            ]
        ]
        if node_updates or edge_updates:
            round_result = RelationshipRoundApplier().build_effects(
                world,
                node_updates,
                edge_updates=edge_updates,
                source=str(raw.get("source", self.source)) or self.source,
                memory_prefix=str(raw.get("memory_prefix", "relationship thought")),
                expected_node_ids=sorted(self.expected_node_ids) or None,
                propagation_node_ids=sorted(self.propagation_node_ids) or None,
            )
            for generated in round_result.effects:
                self._validate_generated_effect(generated)
            effects.extend(round_result.effects)
        else:
            round_result = None
        if self.required_active_node_count is not None:
            active_node_count = (
                len(round_result.active_node_ids) if round_result is not None else 0
            )
            if active_node_count != self.required_active_node_count:
                raise ValueError(
                    "relationship_round requires exactly "
                    f"{self.required_active_node_count} valid distinct active node updates; "
                    f"got {active_node_count}"
                )
        summary = str(raw.get("summary", "")).strip()[:80] or "external provider output"
        metadata = _metadata(raw.get("metadata", {}))
        metadata["provider_output_boundary"] = {
            "schema": PROVIDER_OUTPUT_BOUNDARY_SCHEMA,
            "raw_effect_count": len(raw_effects),
            "accepted_effect_count": len(effects),
        }
        if node_updates or edge_updates:
            metadata["provider_output_boundary"]["node_update_count"] = len(
                node_updates
            )
            metadata["provider_output_boundary"]["edge_update_count"] = len(
                edge_updates
            )
            if relationship_round:
                metadata["provider_output_boundary"]["relationship_text_limits"] = {
                    "reason_max_chars": RELATIONSHIP_REASON_MAX_CHARS,
                    "edge_update_limit": RELATIONSHIP_EDGE_UPDATE_LIMIT,
                    "action_tendency_limit_per_node": 1,
                    "rule_mod_limit_per_node": 1,
                }
                metadata["provider_output_boundary"]["required_action_node_count"] = (
                    self.required_active_node_count
                )
                metadata["provider_output_boundary"]["accepted_action_node_count"] = (
                    sum(
                        1
                        for item in node_updates
                        if _dict_list(item.get("action_tendencies"))
                    )
                )
                metadata["provider_output_boundary"]["action_option_repair_count"] = (
                    len(action_option_repairs)
                )
                if action_option_repairs:
                    metadata["provider_output_boundary"]["action_option_repairs"] = (
                        json_copy(action_option_repairs)
                    )
        if round_result is not None:
            metadata["relationship_round"] = round_result.to_metadata()
        return ProviderOutput(
            source=str(raw.get("source", self.source)) or self.source,
            summary=summary,
            effects=effects,
            metadata=metadata,
        )

    def _resolve_action_option(
        self, update: JsonDict
    ) -> tuple[JsonDict, JsonDict | None]:
        node_id = str(update.get("node_id", update.get("id", "")))
        option_id = str(update.get("selected_action_option_id", ""))
        legacy = _dict_list(update.get("action_tendencies"))
        legacy_pressure = legacy[0] if legacy else {}
        if option_id:
            missing_fields = []
            if "action_weight" not in update and "weight" not in legacy_pressure:
                missing_fields.append("action_weight")
            if "action_ttl" not in update and "ttl" not in legacy_pressure:
                missing_fields.append("action_ttl")
            if not str(
                update.get("action_reason") or legacy_pressure.get("reason") or ""
            ).strip():
                missing_fields.append("action_reason")
            if missing_fields:
                raise ValueError(
                    f"node {node_id} selected an action option without required fields: "
                    f"{missing_fields}"
                )
        selected, repair = resolve_node_bound_action_option(
            self.groundable_action_options,
            option_id,
            node_id,
            source_tick=self.source_tick,
            intent_text=" ".join(
                str(value)
                for value in (
                    update.get("action_reason", ""),
                    legacy_pressure.get("reason", ""),
                    update.get("thought", ""),
                )
                if value
            ),
            preferred_rule=str(legacy_pressure.get("rule", "")),
        )
        if not selected:
            if option_id or legacy:
                raise ValueError(
                    f"node {node_id} selected an unavailable groundable action option"
                )
            return update, None
        option_id = str(selected.get("option_id", ""))
        reason = str(
            update.get("action_reason")
            or legacy_pressure.get("reason")
            or update.get("thought")
            or "model action choice"
        )
        reason = " ".join(reason.split())[:RELATIONSHIP_REASON_MAX_CHARS]
        pressure = materialize_action_option(
            selected,
            weight=float(
                update.get("action_weight", legacy_pressure.get("weight", 0.5)) or 0.5
            ),
            ttl=int(update.get("action_ttl", legacy_pressure.get("ttl", 3)) or 3),
            reason=reason,
        )
        pressure_seed = f"{self.provider_job_id}:{self.source_tick}:{option_id}"
        pressure["pressure_id"] = (
            f"pressure-{sha256(pressure_seed.encode('utf-8')).hexdigest()[:20]}"
        )
        pressure["provider_job_id"] = self.provider_job_id
        pressure["source_tick"] = self.source_tick
        pressure["observation_deadline_tick"] = self.source_tick + max(
            int(pressure.get("ttl", 3) or 3), 2
        )
        resolved = json_copy(update)
        resolved["selected_action_option_id"] = option_id
        resolved["action_tendencies"] = [pressure]
        resolved["rule_mods"] = []
        return resolved, repair

    def _parse_effect(self, world: World, raw_effect: Any, index: int) -> WorldEffect:
        if not isinstance(raw_effect, dict):
            raise ValueError(f"provider output effect[{index}] must be an object")
        kind = str(raw_effect.get("type", "")).strip()
        if not kind:
            raise ValueError(f"provider output effect[{index}] missing type")
        if kind in REJECTED_DIRECT_MUTATION_EFFECT_TYPES:
            raise ValueError(
                f"external provider cannot output direct mutation effect: {kind}"
            )
        if kind not in ALLOWED_EXTERNAL_EFFECT_TYPES:
            raise ValueError(f"external provider effect type is not allowed: {kind}")
        if kind == "rule_pressure_add" and self.groundable_action_options:
            raise ValueError(
                "relationship provider must select a node-bound action option instead of raw rule pressure"
            )

        effect = json_copy(raw_effect)
        if kind == "rule_pressure_add":
            effect["rule"] = canonical_rule_name(str(effect.get("rule", "")))
            node_id = _node_ref(effect.get("target", effect.get("node_id", "")))
            rule = str(effect.get("rule", ""))
            pressure_seed = (
                f"{self.provider_job_id}:{self.source_tick}:{index}:{node_id}:{rule}"
            )
            effect.setdefault(
                "pressure_id",
                f"pressure-{sha256(pressure_seed.encode('utf-8')).hexdigest()[:20]}",
            )
            effect.setdefault("provider_job_id", self.provider_job_id)
            effect.setdefault("source_tick", self.source_tick)
            effect.setdefault(
                "observation_deadline_tick",
                self.source_tick + max(int(effect.get("ttl", 3) or 3), 2),
            )
        self._validate_node_references(world, effect)
        self._validate_registered_names(effect)
        if kind == "rule_pressure_add":
            node_id = _node_ref(effect.get("target", effect.get("node_id", "")))
            if not rule_pressure_is_groundable(
                world,
                node_id,
                str(effect.get("rule", "")),
                effect,
            ):
                raise ValueError(
                    f"provider pressure cannot produce a grounded candidate: "
                    f"{node_id}:{effect.get('rule', '')}"
                )
        return WorldEffect(
            kind, {key: value for key, value in effect.items() if key != "type"}
        )

    def _validate_node_references(self, world: World, effect: JsonDict) -> None:
        for field_name in ("target", "source", "from", "to"):
            if field_name not in effect:
                continue
            value = str(effect[field_name])
            if not value.startswith("node:"):
                continue
            node_id = value.split(":", 1)[1]
            if not world.has_node(node_id):
                raise ValueError(f"external provider referenced missing node: {value}")
            if (
                self.allowed_effect_node_ids
                and node_id not in self.allowed_effect_node_ids
            ):
                raise ValueError(
                    f"external provider referenced node outside current graph: {value}"
                )

    def _validate_registered_names(self, effect: JsonDict) -> None:
        if effect.get("type") == "rule_pressure_add" and self.allowed_rule_names:
            rule = canonical_rule_name(str(effect.get("rule", "")))
            allowed_rules = {
                canonical_rule_name(name) for name in self.allowed_rule_names
            }
            if rule not in allowed_rules:
                raise ValueError(
                    f"external provider referenced unregistered rule: {rule}"
                )
        if (
            effect.get("type") == "relationship_delta"
            and self.allowed_relationship_types
        ):
            relation = str(effect.get("relation", effect.get("edge_type", "")))
            if relation not in self.allowed_relationship_types:
                raise ValueError(
                    f"external provider referenced unregistered relationship type: {relation}"
                )

    def _validate_generated_effect(self, effect: WorldEffect) -> None:
        payload = {"type": effect.type, **effect.fields}
        if (
            effect.type == "rule_pressure_add"
            and self._is_materialized_groundable_option(payload)
        ):
            return
        self._validate_registered_names(payload)

    def _is_materialized_groundable_option(self, payload: JsonDict) -> bool:
        node_id = _node_ref(payload.get("target", payload.get("node_id", "")))
        option_id = str(payload.get("option_id", ""))
        option = option_by_id(self.groundable_action_options, option_id, node_id)
        if not option:
            return False
        return canonical_rule_name(str(payload.get("rule", ""))) == canonical_rule_name(
            str(option.get("rule", ""))
        ) and str(payload.get("expected_action", payload.get("action", ""))) == str(
            option.get("action", "")
        )


def _metadata(value: Any) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[JsonDict]:
    return (
        [json_copy(item) for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _node_ref(value: Any) -> str:
    text = str(value)
    return text.split(":", 1)[1] if ":" in text else text


def _normalize_node_update(
    value: JsonDict, relationship_round: bool = False
) -> JsonDict:
    update = json_copy(value)
    if (
        not str(update.get("thought", "")).strip()
        and str(update.get("visible_thought", "")).strip()
    ):
        update["thought"] = str(update["visible_thought"])
    thought = " ".join(str(update.get("thought", "")).split())
    if relationship_round and not thought:
        raise ValueError("relationship node_update requires one visible core thought")
    if thought:
        update["thought"] = thought
    update["action_tendencies"] = [
        _normalize_rule_pressure(item)
        for item in _dict_list(update.get("action_tendencies"))[:1]
    ]
    update["rule_mods"] = [
        _normalize_rule_pressure(item)
        for item in _dict_list(update.get("rule_mods"))[:1]
    ]
    if relationship_round:
        update.pop("thought_bubbles", None)
        update.pop("bubble_interval", None)
        update.pop("delay", None)
        observe_only_reason = " ".join(
            str(update.get("observe_only_reason", "")).split()
        )
        if (
            not update["action_tendencies"]
            and not str(update.get("selected_action_option_id", "")).strip()
            and not observe_only_reason
        ):
            raise ValueError(
                "relationship node_update without action_tendencies requires observe_only_reason"
            )
        if observe_only_reason:
            update["observe_only_reason"] = observe_only_reason[
                :RELATIONSHIP_REASON_MAX_CHARS
            ]
    return update


def _normalize_rule_pressure(value: JsonDict) -> JsonDict:
    normalized = json_copy(value)
    normalized["rule"] = canonical_rule_name(str(value.get("rule", "")))
    normalized["weight"] = max(0.0, min(float(value.get("weight", 0.0) or 0.0), 1.0))
    normalized["ttl"] = max(2, min(int(value.get("ttl", 2) or 2), 7))
    reason = " ".join(str(value.get("reason", "")).split())
    if reason:
        normalized["reason"] = reason[:RELATIONSHIP_REASON_MAX_CHARS]
    return normalized


def _normalize_edge_update(value: JsonDict) -> JsonDict:
    normalized = json_copy(value)
    reason = " ".join(str(value.get("reason", "")).split())
    if reason:
        normalized["reason"] = reason[:RELATIONSHIP_REASON_MAX_CHARS]
    return normalized
