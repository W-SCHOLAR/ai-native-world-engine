"""Shared contracts and rule bundle declarations."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .events import json_copy
from .feedback import ActionFeedback
from .world import World, WorldNode


JsonDict = dict[str, object]

MOVEMENT_CORE_RULES = ["movement"]
RESOURCE_CORE_RULES = ["movement", "resource_transfer"]
WORLD_ECOSYSTEM_RULES = [
    "combat",
    "infection",
    "quarantine",
    "logistics",
    "organization_decision",
    "social_spread",
    "science_publish",
    "migration",
    "collaboration",
    "production",
    "economic_exchange",
]
RULE_BUNDLES = {
    "movement_core": MOVEMENT_CORE_RULES,
    "resource_core": RESOURCE_CORE_RULES,
    "world_ecosystem": WORLD_ECOSYSTEM_RULES,
}


@dataclass(slots=True)
class RuleCandidate:
    node_id: str
    action: str
    score: float
    rule: str
    reason: str = ""
    metadata: JsonDict = field(default_factory=dict)
    feedback: ActionFeedback | None = None

    def to_dict(self) -> JsonDict:
        return {
            "node_id": self.node_id,
            "action": self.action,
            "score": self.score,
            "rule": self.rule,
            "reason": self.reason,
            "metadata": json_copy(self.metadata),
        }


class RulePackage(Protocol):
    name: str

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        ...


@runtime_checkable
class RulePressureDeriver(Protocol):
    """Explicit pre-arbitration world-fact to pressure producer."""

    def derive_pressures(self, world: World) -> list[ActionFeedback]:
        ...
