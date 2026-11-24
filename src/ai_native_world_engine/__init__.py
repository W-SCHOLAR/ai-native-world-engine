"""AI 原生世界引擎。"""

from .core import (
    ScenarioRegistry,
    World,
    register_scenario,
    scenario_names,
    unregister_scenario,
)

__version__ = "0.1.0"

__all__ = [
    "ScenarioRegistry",
    "World",
    "__version__",
    "register_scenario",
    "scenario_names",
    "unregister_scenario",
]
