"""Shared precondition checks for structured rule pressure."""

from __future__ import annotations

from .action_grounding import pressure_is_groundable
from .world import World


def rule_pressure_is_groundable(
    world: World,
    node_id: str,
    rule: str,
    pressure: dict[str, object] | None = None,
) -> bool:
    """Return whether a rule pressure can produce a candidate from current state."""
    if not world.has_node(node_id):
        return False
    grounded = pressure_is_groundable(world, node_id, rule, pressure)
    return True if grounded is None else grounded
