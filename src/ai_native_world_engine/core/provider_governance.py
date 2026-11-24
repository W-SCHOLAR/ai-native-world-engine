"""Provider registration, allowlists, and audit wrappers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import json_copy
from .provider_boundary import ProviderOutputBoundary
from .providers import AgentProvider, ProviderContext, ProviderOutput


JsonDict = dict[str, Any]


@dataclass(slots=True)
class ProviderPolicyProfile:
    id: str
    label: str = ""
    allowed_rule_names: list[str] = field(default_factory=list)
    allowed_relationship_types: list[str] = field(default_factory=list)
    budget: JsonDict = field(default_factory=dict)
    context_strategy: JsonDict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: JsonDict) -> "ProviderPolicyProfile":
        profile_id = str(value.get("id", value.get("provider_id", ""))).strip()
        if not profile_id:
            raise ValueError("provider policy profile id cannot be empty")
        return cls(
            id=profile_id,
            label=str(value.get("label", profile_id)),
            allowed_rule_names=[str(item) for item in _list(value.get("allowed_rule_names"))],
            allowed_relationship_types=[str(item) for item in _list(value.get("allowed_relationship_types"))],
            budget=_dict(value.get("budget")),
            context_strategy=_dict(value.get("context_strategy")),
            tags=[str(item) for item in _list(value.get("tags"))],
            metadata=_dict(value.get("metadata")),
        )

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "label": self.label or self.id,
            "allowed_rule_names": json_copy(self.allowed_rule_names),
            "allowed_relationship_types": json_copy(self.allowed_relationship_types),
            "budget": json_copy(self.budget),
            "context_strategy": json_copy(self.context_strategy),
            "tags": json_copy(self.tags),
            "metadata": json_copy(self.metadata),
        }


@dataclass(slots=True)
class ProviderRegistration:
    id: str
    provider: AgentProvider
    allowed_rule_names: set[str] = field(default_factory=set)
    allowed_relationship_types: set[str] = field(default_factory=set)
    policy_profile: ProviderPolicyProfile | None = None

    def to_dict(self) -> JsonDict:
        result: JsonDict = {
            "id": self.id,
            "provider": self.provider.name,
            "allowed_rule_names": sorted(self.allowed_rule_names),
            "allowed_relationship_types": sorted(self.allowed_relationship_types),
        }
        if self.policy_profile:
            result["policy_profile"] = self.policy_profile.to_dict()
        return result


@dataclass(slots=True)
class ProviderAuditEntry:
    provider_id: str
    provider_name: str
    accepted: bool
    raw_effect_count: int = 0
    accepted_effect_count: int = 0
    error: str = ""
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "accepted": self.accepted,
            "raw_effect_count": self.raw_effect_count,
            "accepted_effect_count": self.accepted_effect_count,
            "error": self.error,
            "metadata": json_copy(self.metadata),
        }


@dataclass(slots=True)
class GovernedProviderResult:
    output: ProviderOutput | None
    audit: ProviderAuditEntry

    def to_dict(self) -> JsonDict:
        return {
            "output": self.output.to_dict() if self.output else None,
            "audit": self.audit.to_dict(),
        }


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}

    def register(
        self,
        provider_id: str,
        provider: AgentProvider,
        allowed_rule_names: set[str] | None = None,
        allowed_relationship_types: set[str] | None = None,
        policy_profile: ProviderPolicyProfile | JsonDict | None = None,
    ) -> ProviderRegistration:
        if not provider_id:
            raise ValueError("provider_id cannot be empty")
        profile = _profile(policy_profile)
        registration = ProviderRegistration(
            id=provider_id,
            provider=provider,
            allowed_rule_names=set(allowed_rule_names or (profile.allowed_rule_names if profile else set())),
            allowed_relationship_types=set(
                allowed_relationship_types or (profile.allowed_relationship_types if profile else set())
            ),
            policy_profile=profile,
        )
        self._providers[provider_id] = registration
        return registration

    def get(self, provider_id: str) -> ProviderRegistration:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"provider is not registered: {provider_id}") from exc

    def to_dict(self) -> JsonDict:
        return {"providers": [item.to_dict() for item in self._providers.values()]}


class GovernedProviderRunner:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def observe(self, provider_id: str, context: ProviderContext) -> GovernedProviderResult:
        registration = self.registry.get(provider_id)
        try:
            raw_output = registration.provider.observe(context)
            budget_error = _budget_error(raw_output, registration.policy_profile)
            if budget_error:
                raise ValueError(budget_error)
            raw = {
                "source": raw_output.source,
                "summary": raw_output.summary,
                "effects": [effect.to_dict() for effect in raw_output.effects],
                "metadata": json_copy(raw_output.metadata),
            }
            output = ProviderOutputBoundary(
                source=registration.provider.name,
                allowed_rule_names=set(registration.allowed_rule_names),
                allowed_relationship_types=set(registration.allowed_relationship_types),
            ).parse(context.world, raw)
        except Exception as exc:  # noqa: BLE001 - provider governance must audit all failures.
            return GovernedProviderResult(
                output=None,
                audit=ProviderAuditEntry(
                    provider_id=registration.id,
                    provider_name=registration.provider.name,
                    accepted=False,
                    error=str(exc),
                    metadata=registration.to_dict(),
                ),
            )
        boundary_meta = output.metadata.get("provider_output_boundary", {})
        audit = ProviderAuditEntry(
            provider_id=registration.id,
            provider_name=registration.provider.name,
            accepted=True,
            raw_effect_count=int(boundary_meta.get("raw_effect_count", len(output.effects)) or 0),
            accepted_effect_count=int(boundary_meta.get("accepted_effect_count", len(output.effects)) or 0),
            metadata=registration.to_dict(),
        )
        return GovernedProviderResult(output=output, audit=audit)


def _profile(value: ProviderPolicyProfile | JsonDict | None) -> ProviderPolicyProfile | None:
    if value is None:
        return None
    if isinstance(value, ProviderPolicyProfile):
        return value
    if isinstance(value, dict) and value:
        return ProviderPolicyProfile.from_dict(value)
    return None


def _budget_error(output: ProviderOutput, profile: ProviderPolicyProfile | None) -> str:
    if profile is None:
        return ""
    budget = profile.budget
    if not budget:
        return ""
    runtime = output.metadata.get("provider_runtime", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    attempts = int(runtime.get("attempts", 0) or 0)
    estimated_cost = float(runtime.get("estimated_cost", 0.0) or 0.0)
    max_attempts = budget.get("max_attempts")
    if isinstance(max_attempts, (int, float)) and attempts > int(max_attempts):
        return f"provider budget exceeded: attempts {attempts} > {int(max_attempts)}"
    max_cost = budget.get("max_estimated_cost")
    if isinstance(max_cost, (int, float)) and estimated_cost > float(max_cost):
        return f"provider budget exceeded: estimated_cost {estimated_cost} > {float(max_cost)}"
    return ""


def _dict(value: object) -> JsonDict:
    return json_copy(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
