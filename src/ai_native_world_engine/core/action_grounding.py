"""Deterministic, node-bound action options for live agent output."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any

from .events import json_copy
from .rule_packages import (
    CollaborationRulePackage,
    MovementRulePackage,
    OrganizationDecisionRulePackage,
    SciencePublishRulePackage,
    SocialSpreadRulePackage,
)
from .rule_registry import canonical_rule_name
from .speech import SpeakRulePackage
from .world import World, WorldNode


JsonDict = dict[str, Any]
ACTION_OPTION_REPAIR_SCHEMA = "grounded_action_option_repair_v1"
ENTERPRISE_AGENT_RULES = [
    "movement",
    "collaboration",
    "organization_decision",
    "social_spread",
    "science_publish",
    "speak",
]

_PACKAGES = {
    "movement": MovementRulePackage,
    "collaboration": CollaborationRulePackage,
    "organization_decision": OrganizationDecisionRulePackage,
    "social_spread": SocialSpreadRulePackage,
    "science_publish": SciencePublishRulePackage,
    "speak": SpeakRulePackage,
}

_RULE_INTENT_TERMS = {
    "movement": (
        "movement",
        "move",
        "travel",
        "route",
        "scout",
        "patrol",
        "forward",
        "relocate",
        "escort",
        "return",
        "移动",
        "前往",
        "侦察",
        "巡逻",
        "路线",
        "出发",
        "返回",
        "护送",
    ),
    "collaboration": (
        "collaboration",
        "collaborate",
        "cooperate",
        "coordinate",
        "coordination",
        "assist",
        "help",
        "team",
        "joint",
        "协作",
        "协同",
        "协调",
        "合作",
        "帮助",
        "援助",
        "配合",
    ),
    "organization_decision": (
        "organization_decision",
        "decision",
        "decide",
        "command",
        "plan",
        "organize",
        "approve",
        "vote",
        "决策",
        "组织",
        "命令",
        "计划",
        "批准",
        "投票",
        "分配",
    ),
    "social_spread": (
        "social_spread",
        "spread",
        "inform",
        "communicate",
        "announce",
        "persuade",
        "warn",
        "signal",
        "告知",
        "传播",
        "通知",
        "宣布",
        "说服",
        "警告",
        "示警",
        "汇报",
    ),
    "science_publish": (
        "science_publish",
        "science",
        "publish",
        "research",
        "study",
        "validate",
        "experiment",
        "研究",
        "验证",
        "发表",
        "实验",
        "调查",
    ),
    "speak": (
        "speak",
        "speech",
        "talk",
        "tell",
        "ask",
        "warn",
        "report",
        "说话",
        "交谈",
        "告知",
        "询问",
        "警告",
        "汇报",
    ),
}


@dataclass(slots=True)
class GroundableActionOption:
    option_id: str
    node_id: str
    rule: str
    action: str
    parameters: JsonDict = field(default_factory=dict)
    target_id: str = ""
    expires_at_tick: int = 0

    def to_dict(self) -> JsonDict:
        return {
            "option_id": self.option_id,
            "node_id": self.node_id,
            "rule": self.rule,
            "action": self.action,
            "target_id": self.target_id,
            "parameters": json_copy(self.parameters),
            "expires_at_tick": self.expires_at_tick,
        }


def groundable_action_options(
    world: World,
    node_ids: list[str],
    enabled_rule_names: list[str],
    ttl: int = 3,
) -> list[JsonDict]:
    enabled = {canonical_rule_name(name) for name in enabled_rule_names}
    rows: list[JsonDict] = []
    for node_id in node_ids:
        if not world.has_node(node_id):
            continue
        node = world.node(node_id)
        for option in _active_action_options(world, node_id, ttl=max(int(ttl), 2)):
            rows.append(option.to_dict())
        for option in _node_options(world, node, enabled, ttl=max(int(ttl), 2)):
            if action_option_is_groundable(world, option.to_dict()):
                rows.append(option.to_dict())
    deduplicated: dict[str, JsonDict] = {}
    for row in rows:
        deduplicated.setdefault(str(row.get("option_id", "")), row)
    return list(deduplicated.values())


def action_option_is_groundable(world: World, raw_option: JsonDict) -> bool:
    node_id = str(raw_option.get("node_id", ""))
    parameters = (
        raw_option.get("parameters")
        if isinstance(raw_option.get("parameters"), dict)
        else {}
    )
    active_action_id = str(parameters.get("_grounded_active_action_id", ""))
    if active_action_id:
        action = world.active_actions.get(active_action_id)
        return bool(
            action is not None
            and action.active
            and action.actor_id == node_id
            and action.definition_id == str(raw_option.get("action", ""))
            and action.package_id == str(parameters.get("_grounded_package_id", ""))
        )
    rule = canonical_rule_name(str(raw_option.get("rule", "")))
    package_type = _PACKAGES.get(rule)
    if not node_id or not world.has_node(node_id) or package_type is None:
        return False
    probe = deepcopy(world.node(node_id))
    pressure = materialize_action_option(raw_option)
    probe.rule_pressures.append(pressure)
    return any(
        canonical_rule_name(candidate.rule) == rule
        and candidate.action == str(raw_option.get("action", ""))
        for candidate in package_type().candidates(world, probe)
    )


def pressure_is_groundable(
    world: World,
    node_id: str,
    rule: str,
    pressure: JsonDict | None = None,
) -> bool | None:
    canonical = canonical_rule_name(rule)
    package_type = _PACKAGES.get(canonical)
    if package_type is None:
        return None
    if not world.has_node(node_id):
        return False
    probe = deepcopy(world.node(node_id))
    normalized = json_copy(pressure or {})
    normalized["rule"] = canonical
    normalized.setdefault("weight", 0.5)
    normalized.setdefault("ttl", 3)
    probe.rule_pressures.append(normalized)
    return bool(package_type().candidates(world, probe))


def materialize_action_option(
    raw_option: JsonDict,
    *,
    weight: float = 0.5,
    ttl: int = 3,
    reason: str = "model action choice",
) -> JsonDict:
    parameters = (
        json_copy(raw_option.get("parameters", {}))
        if isinstance(raw_option.get("parameters"), dict)
        else {}
    )
    return {
        "rule": canonical_rule_name(str(raw_option.get("rule", ""))),
        "action": str(raw_option.get("action", "")),
        "option_id": str(raw_option.get("option_id", "")),
        "expected_action": str(raw_option.get("action", "")),
        "weight": max(0.0, min(float(weight), 1.0)),
        "ttl": max(2, min(int(ttl), 7)),
        "reason": str(reason)[:80],
        **parameters,
    }


def option_by_id(options: list[JsonDict], option_id: str, node_id: str) -> JsonDict:
    for option in options:
        if str(option.get("option_id", "")) == str(option_id) and str(
            option.get("node_id", "")
        ) == str(node_id):
            return json_copy(option)
    return {}


def resolve_node_bound_action_option(
    options: list[JsonDict],
    selected_option_id: str,
    node_id: str,
    *,
    source_tick: int,
    intent_text: str = "",
    preferred_rule: str = "",
) -> tuple[JsonDict, JsonDict | None]:
    """Resolve a model choice without granting authority to an invented id.

    Exact current selections pass through. An unavailable selection can only be
    replaced by an unexpired option already generated for the same node. The
    returned repair row is deliberately small and safe to expose in audit data.
    """

    selected_option_id = str(selected_option_id).strip()
    node_id = str(node_id)
    exact = (
        option_by_id(options, selected_option_id, node_id) if selected_option_id else {}
    )
    if exact and _option_is_current(exact, source_tick):
        return exact, None

    current = sorted(
        (
            json_copy(option)
            for option in options
            if str(option.get("node_id", "")) == node_id
            and _option_is_current(option, source_tick)
        ),
        key=_option_sort_key,
    )
    if not selected_option_id or not current:
        return {}, None

    canonical_preference = canonical_rule_name(preferred_rule)
    preferred = [
        option
        for option in current
        if canonical_preference
        and canonical_rule_name(str(option.get("rule", ""))) == canonical_preference
    ]
    strategy = "canonical_rule_match"
    candidates = preferred
    if not candidates:
        evidence = " ".join(
            part for part in (selected_option_id, str(intent_text)) if part
        ).casefold()
        scored = [
            (_option_intent_score(option, evidence), option) for option in current
        ]
        best_score = max((score for score, _ in scored), default=0)
        if best_score > 0:
            candidates = [option for score, option in scored if score == best_score]
            strategy = "semantic_match"
        else:
            candidates = current
            strategy = "stable_node_fallback"

    repaired = _stable_option_choice(candidates, node_id, selected_option_id)
    foreign_owners = sorted(
        {
            str(option.get("node_id", ""))
            for option in options
            if str(option.get("option_id", "")) == selected_option_id
            and str(option.get("node_id", ""))
            and str(option.get("node_id", "")) != node_id
        }
    )
    original_state = (
        "cross_node" if foreign_owners else "expired" if exact else "invented"
    )
    return repaired, {
        "schema": ACTION_OPTION_REPAIR_SCHEMA,
        "node_id": node_id,
        "original_option_id": selected_option_id,
        "repaired_option_id": str(repaired.get("option_id", "")),
        "strategy": f"{original_state}_{strategy}",
        "source_tick": int(source_tick),
        **({"foreign_option_node_ids": foreign_owners} if foreign_owners else {}),
    }


def _option_is_current(option: JsonDict, source_tick: int) -> bool:
    return int(option.get("expires_at_tick", source_tick) or source_tick) >= int(
        source_tick
    )


def _option_sort_key(option: JsonDict) -> tuple[str, str, str, str]:
    return (
        canonical_rule_name(str(option.get("rule", ""))),
        str(option.get("action", "")),
        str(option.get("target_id", "")),
        str(option.get("option_id", "")),
    )


def _option_intent_score(option: JsonDict, evidence: str) -> int:
    rule = canonical_rule_name(str(option.get("rule", "")))
    action = str(option.get("action", "")).casefold()
    terms = {rule.casefold(), action, *_RULE_INTENT_TERMS.get(rule, ())}
    return sum(max(len(term), 1) for term in terms if term and term in evidence)


def _stable_option_choice(
    candidates: list[JsonDict],
    node_id: str,
    selected_option_id: str,
) -> JsonDict:
    ordered = sorted(candidates, key=_option_sort_key)
    seed = f"{node_id}:{selected_option_id}"
    index = int(sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(ordered)
    return json_copy(ordered[index])


def _node_options(
    world: World,
    node: WorldNode,
    enabled: set[str],
    ttl: int,
) -> list[GroundableActionOption]:
    specs: list[tuple[str, str, str, JsonDict]] = []
    role = str(node.attributes.get("role", "")).lower()
    neighbors = _relationship_neighbors(world, node.id)
    if (
        "movement" in enabled
        and node.movement_target is not None
        and node.movement_speed > 0
    ):
        specs.append(("movement", "move", "", {}))
    if "collaboration" in enabled and neighbors:
        partner_id = neighbors[0]
        specs.append(
            (
                "collaboration",
                "collaboration",
                partner_id,
                {"with": partner_id, "project": "shared coordination"},
            )
        )
    if "speak" in enabled and neighbors:
        target_id = neighbors[0]
        specs.append(
            (
                "speak",
                "speak",
                target_id,
                {
                    "target_ids": [target_id],
                    "intent": "inform",
                    "topic": "当前任务与营地局势",
                    "visibility": "direct",
                },
            )
        )
    if "organization_decision" in enabled and any(
        keyword in role
        for keyword in (
            "policy",
            "planning",
            "coordination",
            "operations",
            "ethics",
            "board",
        )
    ):
        specs.append(
            (
                "organization_decision",
                "organization_decision",
                "",
                {"decision": "coordinate", "status": "proposed"},
            )
        )
    if (
        "social_spread" in enabled
        and neighbors
        and any(
            keyword in role
            for keyword in (
                "communication",
                "training",
                "editor",
                "distribution",
                "organizing",
                "liaison",
            )
        )
    ):
        target_id = neighbors[0]
        specs.append(
            (
                "social_spread",
                "social_spread",
                target_id,
                {
                    "to": target_id,
                    "signal": "current coordination signal",
                    "require_relationship": True,
                },
            )
        )
    if "science_publish" in enabled and any(
        keyword in role
        for keyword in (
            "research",
            "analysis",
            "data",
            "theory",
            "laboratory",
            "publication",
            "epidemiology",
        )
    ):
        specs.append(
            (
                "science_publish",
                "science_publish",
                "",
                {"topic": "current scenario research", "title": "Scenario finding"},
            )
        )
    options = [
        _option(world.tick, node.id, rule, action, target_id, parameters, ttl)
        for rule, action, target_id, parameters in specs[:4]
    ]
    return options


def _active_action_options(
    world: World,
    node_id: str,
    ttl: int,
) -> list[GroundableActionOption]:
    options: list[GroundableActionOption] = []
    for action in sorted(world.active_actions.values(), key=lambda item: item.id):
        if action.actor_id != node_id or not action.active:
            continue
        remaining = max(
            int(action.deadline_tick or world.tick + 2) - int(world.tick),
            2,
        )
        parameters = json_copy(action.parameters)
        parameters.update(
            {
                "_grounded_active_action_id": action.id,
                "_grounded_package_id": action.package_id,
                "channel": action.channel,
                "locks": json_copy(action.locks),
                "behavior_label": action.behavior_label,
                "duration_ticks": remaining,
                "root_causality_id": action.root_causality_id,
                "caused_by": json_copy(action.caused_by),
            }
        )
        options.append(
            _option(
                world.tick,
                node_id,
                action.definition_id,
                action.definition_id,
                action.target_ids[0] if action.target_ids else "",
                parameters,
                ttl,
            )
        )
    return options


def _option(
    tick: int,
    node_id: str,
    rule: str,
    action: str,
    target_id: str,
    parameters: JsonDict,
    ttl: int,
) -> GroundableActionOption:
    payload = {
        "tick": int(tick),
        "node_id": node_id,
        "rule": rule,
        "action": action,
        "target_id": target_id,
        "parameters": parameters,
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return GroundableActionOption(
        option_id=f"action-{digest}",
        node_id=node_id,
        rule=rule,
        action=action,
        target_id=target_id,
        parameters=json_copy(parameters),
        expires_at_tick=int(tick) + ttl,
    )


def _relationship_neighbors(world: World, node_id: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for edge in world.relationships.values():
        other_id = ""
        if edge.source == node_id:
            other_id = edge.target
        elif edge.target == node_id:
            other_id = edge.source
        if other_id and other_id != node_id and world.has_node(other_id):
            ranked.append((-abs(float(edge.weight)), other_id))
    ranked.sort()
    result: list[str] = []
    for _, other_id in ranked:
        if other_id not in result:
            result.append(other_id)
    return result
