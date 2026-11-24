from __future__ import annotations

import pytest

from ai_native_world_engine.core import (
    AgentContextPacketBuilder,
    JsonLlmProviderAdapter,
    ProviderContext,
    World,
    enterprise_agent_jobs,
)
from ai_native_world_engine.core.action_grounding import (
    ENTERPRISE_AGENT_RULES,
    groundable_action_options,
)
from ai_native_world_engine.core.providers import ProviderAttemptBudget, ProviderBudgetExhausted


def test_shared_attempt_budget_reserves_prompt_completion_and_cost_before_send() -> None:
    budget = ProviderAttemptBudget(
        limit=2,
        max_prompt_tokens=100,
        max_completion_tokens=40,
        max_estimated_cost=1.0,
    )
    budget.reserve(max_prompt_tokens=60, max_completion_tokens=20, estimated_cost=0.4)
    with pytest.raises(ProviderBudgetExhausted, match="prompt-token"):
        budget.reserve(max_prompt_tokens=41, max_completion_tokens=20, estimated_cost=0.4)

    budget.record_usage(
        prompt_tokens=50,
        completion_tokens=12,
        estimated_cost=0.3,
        reserved_prompt_tokens=60,
        reserved_completion_tokens=20,
        reserved_estimated_cost=0.4,
    )
    assert budget.snapshot() == {
        "limit": 2,
        "used": 1,
        "prompt_tokens": 50,
        "completion_tokens": 12,
        "estimated_cost": 0.3,
    }


class _ReferenceCapableClient:
    supports_context_references = True


def test_context_reference_delta_is_capability_gated_and_starts_full() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = next(job for job in enterprise_agent_jobs(world, include_static_lenses=False) if job.kind == "relationship_round")
    packet = AgentContextPacketBuilder().build(world, job)
    packet["groundable_action_options"] = groundable_action_options(
        world,
        [str(item["id"]) for item in packet["active_candidates"]],
        ENTERPRISE_AGENT_RULES,
    )
    adapter = JsonLlmProviderAdapter(client=_ReferenceCapableClient())
    context = ProviderContext(world=world, tick=world.tick, snapshot=world.snapshot())

    first = adapter.build_envelope(context, packet)
    assert first["_context_delivery"]["mode"] == "full"
    adapter._remember_context_base(first)
    second = adapter.build_envelope(context, packet)

    assert second["_context_delivery"]["mode"] == "delta"
    assert second["context_packet"]["schema"] == "agent_model_context_delta_v1"
    assert second["context_packet"]["changed_sections"] == {}


def test_default_provider_without_reference_capability_always_receives_full_context() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = next(job for job in enterprise_agent_jobs(world, include_static_lenses=False) if job.kind == "relationship_round")
    packet = AgentContextPacketBuilder().build(world, job)
    adapter = JsonLlmProviderAdapter(client=object())
    envelope = adapter.build_envelope(
        ProviderContext(world=world, tick=world.tick, snapshot=world.snapshot()), packet
    )
    assert envelope["_context_delivery"]["mode"] == "full"
    assert envelope["context_packet"]["projection"] == "relationship_model_context_v2"
