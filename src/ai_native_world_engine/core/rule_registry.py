"""Rule bundle expansion and package registry helpers."""

from .rule_contracts import RULE_BUNDLES
from .rule_names import canonical_rule_name


def expand_rule_names(rule_names: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for raw_name in rule_names:
        name = canonical_rule_name(str(raw_name))
        names = RULE_BUNDLES.get(name, [name])
        for expanded_name in names:
            expanded_name = canonical_rule_name(expanded_name)
            if expanded_name in seen:
                continue
            expanded.append(expanded_name)
            seen.add(expanded_name)
    return expanded
