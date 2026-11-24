"""Public compatibility facade for rule contracts and built-in packages."""

from .action_contracts import (
    ACTION_CHANNELS,
    ACTION_RUNTIME_VERSION,
    ACTIVE_ACTION_STATUSES,
    TERMINAL_ACTION_STATUSES,
    ActionInstance,
    ActionRulePackageV2,
    ActionTransition,
)
from .action_runtime import ActionRuntime, LegacyRulePackageAdapter
from .rule_contracts import (
    MOVEMENT_CORE_RULES,
    RESOURCE_CORE_RULES,
    RULE_BUNDLES,
    WORLD_ECOSYSTEM_RULES,
    JsonDict,
    RuleCandidate,
    RulePackage,
    RulePressureDeriver,
)
from .rule_engine import RuleEngineSet
from .rule_packages import (
    CollaborationRulePackage,
    CombatRulePackage,
    EconomicExchangeRulePackage,
    InfectionRulePackage,
    LogisticsRulePackage,
    MigrationRulePackage,
    MovementRulePackage,
    OrganizationDecisionRulePackage,
    ProductionRulePackage,
    QuarantineRulePackage,
    ResourceTransferRulePackage,
    SciencePublishRulePackage,
    SocialSpreadRulePackage,
)
from .rule_registry import expand_rule_names
from .speech import SPEECH_INTENTS, SPEECH_VISIBILITY, SpeakRulePackage

__all__ = [
    "ACTION_CHANNELS",
    "ACTION_RUNTIME_VERSION",
    "ACTIVE_ACTION_STATUSES",
    "TERMINAL_ACTION_STATUSES",
    "ActionInstance",
    "ActionRulePackageV2",
    "ActionRuntime",
    "ActionTransition",
    "LegacyRulePackageAdapter",
    "MOVEMENT_CORE_RULES",
    "RESOURCE_CORE_RULES",
    "RULE_BUNDLES",
    "WORLD_ECOSYSTEM_RULES",
    "JsonDict",
    "RuleCandidate",
    "RulePackage",
    "RulePressureDeriver",
    "RuleEngineSet",
    "MovementRulePackage",
    "ResourceTransferRulePackage",
    "ProductionRulePackage",
    "EconomicExchangeRulePackage",
    "CombatRulePackage",
    "InfectionRulePackage",
    "QuarantineRulePackage",
    "LogisticsRulePackage",
    "OrganizationDecisionRulePackage",
    "SocialSpreadRulePackage",
    "SciencePublishRulePackage",
    "SPEECH_INTENTS",
    "SPEECH_VISIBILITY",
    "SpeakRulePackage",
    "MigrationRulePackage",
    "CollaborationRulePackage",
    "expand_rule_names",
]
