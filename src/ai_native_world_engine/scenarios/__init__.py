"""内置场景。"""

from .compound_crisis import create_compound_crisis_world
from .planet_actions import (
    PlanetCommunicationPackage,
    PlanetStageRulePackage,
    planet_rule_packages,
)
from .seed_scenarios import create_seed_world
from .tribe_survival import TribeSurvivalRulePackage, create_tribe_survival_world
from .tribe_activities import TribeActivityRulePackage
from ai_native_world_engine.core.scenario_registry import (
    ScenarioRegistry,
    register_scenario,
    scenario_names,
    unregister_scenario,
)

__all__ = [
    "TribeSurvivalRulePackage",
    "PlanetCommunicationPackage",
    "PlanetStageRulePackage",
    "ScenarioRegistry",
    "create_compound_crisis_world",
    "create_seed_world",
    "create_tribe_survival_world",
    "TribeActivityRulePackage",
    "planet_rule_packages",
    "register_scenario",
    "scenario_names",
    "unregister_scenario",
]
