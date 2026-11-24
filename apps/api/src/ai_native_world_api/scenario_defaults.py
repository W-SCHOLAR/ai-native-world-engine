"""Product scenario catalog defaults."""

from __future__ import annotations

from typing import Any

from ai_native_world_engine.core import WORLD_ECOSYSTEM_RULES
from ai_native_world_engine.core.action_grounding import ENTERPRISE_AGENT_RULES

from .models import ScenarioRecord


JsonDict = dict[str, Any]

EXPANDED_DOMAIN_RULES = list(WORLD_ECOSYSTEM_RULES)

COMPOUND_CRISIS_REQUIRED_ACTIONS = [
    "infection_progress",
    "infection_spread",
    "quarantine_policy",
    "logistics_transfer",
    "combat_attack",
    "organization_decision",
    "social_spread",
    "science_publish",
    "migration",
    "collaboration",
    "production",
    "economic_exchange",
]

TRIBE_SURVIVAL_REQUIRED_ACTIONS = [
    "combat_attack",
    "move",
    "food_assess",
    "defense_inspect",
    "injury_assess",
    "duty_patrol",
]

def default_scenarios() -> dict[str, ScenarioRecord]:
    return {
        "seed": ScenarioRecord(
            id="seed",
            name="Seed World",
            description="Deterministic baseline world for smoke runs.",
            defaults={"ticks": 3, "rules": ["movement"], "demo_priority": 10},
        ),
        "enterprise_earth": ScenarioRecord(
            id="enterprise_earth",
            name="星球文明",
            description="Governed enterprise earth scenario with relationship-network agents.",
            defaults={"ticks": 7, "rules": list(ENTERPRISE_AGENT_RULES), "demo_priority": 120},
        ),
        "tribe_survival": ScenarioRecord(
            id="tribe_survival",
            name="蛮荒世界",
            description="Engine-backed open-world survival RPG vertical slice.",
            defaults={
                "ticks": 8,
                "rules": ["movement", "combat", "speak"],
                "evaluation_goals": {"required_actions": TRIBE_SURVIVAL_REQUIRED_ACTIONS},
                "demo_priority": 200,
            },
        ),
        "compound_crisis": ScenarioRecord(
            id="compound_crisis",
            name="Compound Crisis",
            description="Deterministic multi-rule crisis world for causal-chain demos.",
            defaults={
                "ticks": 1,
                "rules": EXPANDED_DOMAIN_RULES,
                "evaluation_goals": {"required_actions": COMPOUND_CRISIS_REQUIRED_ACTIONS},
                "demo_priority": 100,
            },
        ),
    }


def scenario_defaults(scenario_id: str) -> JsonDict:
    scenario = default_scenarios().get(str(scenario_id))
    return dict(scenario.defaults) if scenario else {}
