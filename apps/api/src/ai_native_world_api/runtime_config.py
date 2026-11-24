"""Shared product runtime configuration helpers."""

from __future__ import annotations

from ai_native_world_engine.core import (
    SCHEDULED_AGENT_SCENARIOS,
    AgentSchedulerConfig,
    default_agent_scheduler_config,
)


def scenario_scheduler_config(scenario: str, ticks: int) -> AgentSchedulerConfig | None:
    if scenario not in SCHEDULED_AGENT_SCENARIOS or int(ticks) <= 0:
        return None
    return default_agent_scheduler_config(scenario, ticks)


def enterprise_scheduler_config(scenario: str, ticks: int) -> AgentSchedulerConfig | None:
    """Compatibility alias for callers using the original helper name."""

    return scenario_scheduler_config(scenario, ticks)
