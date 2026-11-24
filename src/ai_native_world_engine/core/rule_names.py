"""Dependency-light canonical rule-name aliases."""

RULE_ALIASES = {
    "move": "movement",
    "movement": "movement",
    "collaborate": "collaboration",
    "cooperate": "collaboration",
    "decision": "organization_decision",
    "policy_decision": "organization_decision",
    "influence": "social_spread",
    "belief_spread": "social_spread",
    "publish": "science_publish",
    "publication": "science_publish",
}


def canonical_rule_name(raw_name: str) -> str:
    name = str(raw_name).strip().lower()
    return RULE_ALIASES.get(name, name)
