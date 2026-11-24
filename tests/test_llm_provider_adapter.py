import json
from time import perf_counter, sleep

import pytest

from ai_native_world_engine.core import (
    ACTIVE_NODE_LIMIT,
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    AgentContextPacketBuilder,
    AgentJob,
    AgentScheduler,
    AgentSchedulerConfig,
    CancellationToken,
    CONTEXT_PACKET_SCHEMA,
    DeterministicRelationshipRoundProvider,
    FeedbackIngestor,
    JsonLlmProviderAdapter,
    LLM_PROMPT_ENVELOPE_SCHEMA,
    LLM_PROMPT_TEMPLATE_VERSION,
    ProviderDeadlineExceeded,
    ProviderCancelled,
    ProviderContext,
    ProviderOutput,
    OpenAICompatibleJsonClient,
    RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT,
    REQUIRED_RIPPLE_NODE_COUNT,
    RIPPLE_TARGETS_PER_ACTIVE,
    World,
    compile_agent_model_context,
    enterprise_agent_jobs,
    extract_json_provider_output,
)
from ai_native_world_engine.core.action_grounding import (
    ENTERPRISE_AGENT_RULES,
    groundable_action_options,
)


def relationship_node_updates(
    envelope: dict, count: int = ACTIVE_NODE_LIMIT
) -> list[dict]:
    decision_context = envelope["context_packet"]["decision_context"]
    candidates = decision_context["active_candidates"]
    options_by_node = {
        group["node_id"]: group["options"]
        for group in decision_context["action_options_by_node"]
    }
    return [
        {
            "id": candidate["id"],
            "visible_thought": f"Live relationship thought for {candidate['name']}.",
            "selected_action_option_id": options_by_node[candidate["id"]][0][
                "option_id"
            ],
            "action_weight": 0.5,
            "action_ttl": 3,
            "action_reason": "推进目标",
        }
        for candidate in candidates
        if candidate["id"] in options_by_node
    ][:count]


def relationship_context_packet(world: World, job: AgentJob) -> dict:
    packet = AgentContextPacketBuilder().build(world, job)
    candidate_ids = [item["id"] for item in packet["active_candidates"]]
    packet["groundable_action_options"] = groundable_action_options(
        world,
        candidate_ids,
        ENTERPRISE_AGENT_RULES,
    )
    return packet


def key_character_context_packet(
    world: World,
    target_node_id: str = "key-albert-einstein",
) -> tuple[AgentJob, dict]:
    job = next(
        item
        for item in enterprise_agent_jobs(world, include_static_lenses=False)
        if item.kind == "key_character_continuity"
        and item.metadata["target_node_id"] == target_node_id
    )
    packet = AgentContextPacketBuilder().build(world, job)
    packet["groundable_action_options"] = groundable_action_options(
        world,
        [target_node_id],
        ENTERPRISE_AGENT_RULES,
    )
    return job, packet


def key_character_response(
    envelope: dict,
    *,
    progress_delta: str = "Published a falsifiable comparison for institutional review.",
) -> dict:
    context = envelope["context_packet"]
    target = context["job"]["target_node_id"]
    influence_target = context["decision_context"]["influence_nodes"][0]["id"]
    action_option = context["decision_context"]["action_options_by_node"][0]["options"][
        0
    ]
    return {
        "summary": "The protagonist launched a grounded initiative.",
        "character_id": target,
        "insight": "I can turn this evidence into a public test that institutions must answer.",
        "self_narrative": "I make difficult patterns testable and public.",
        "personality_profile": {
            "values": ["clarity"],
            "fears": ["unexamined certainty"],
            "desires": ["shared understanding"],
            "boundaries": ["respect evidence"],
            "bonds": ["scientific community"],
        },
        "goal_status": "continue",
        "goal": "Make a testable idea reshape institutional coordination.",
        "previous_action_assessment": {
            "status": "partial",
            "evidence": "The prior comparison reached nearby institutions but lacks a public test.",
            "consequence": "Publish a falsifiable proposal and invite coordinated review.",
        },
        "progress_delta": progress_delta,
        "plan_reason": "A public test lets the relationship network carry or challenge the idea.",
        "plan_steps": ["publish the test", "invite review", "respond to evidence"],
        "current_step": "Publish the test and invite institutional review.",
        "grounded_rule": action_option["rule"],
        "selected_action_option_id": action_option["option_id"],
        "rule_weight": 0.8,
        "rule_ttl": 5,
        "rule_reason": "发布可验证倡议",
        "initiative": {
            "action": "Publish a falsifiable proposal and convene an evidence review.",
            "target_node_ids": [influence_target],
            "expected_change": "Create an auditable coordination signal in nearby institutions.",
            "propagation_goal": "Have relationship networks test, carry, resist, or refine the proposal.",
            "impact_scale": 0.9,
        },
        "peer_interactions": [],
        "commitments": [],
    }


class CaptureProvider:
    name = "capture-provider"

    def __init__(self) -> None:
        self.params = {}

    def observe(self, context: ProviderContext) -> ProviderOutput:
        self.params = context.params
        return ProviderOutput(source=self.name, summary="captured")


class FakeJsonClient:
    def __init__(self) -> None:
        self.envelope = {}

    def complete(self, envelope: dict) -> dict:
        self.envelope = envelope
        active = envelope["context_packet"]["decision_context"]["active_candidates"][0]
        return {
            "summary": "LLM emitted structured pressure.",
            "node_updates": relationship_node_updates(envelope),
            "effects": [
                {
                    "type": "thought_bubble_add",
                    "target": f"node:{active['id']}",
                    "text": "I can only influence the pressure layer.",
                    "source": "json-llm-provider",
                }
            ],
            "metadata": {"model": "fake-json-client"},
        }


def test_scheduler_passes_full_context_packet_to_provider_params() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    provider = CaptureProvider()
    scheduler = AgentScheduler(
        AgentSchedulerConfig(
            enabled=True, max_concurrent=1, dispatch_slots=["relationship"]
        )
    )
    scheduler.enqueue(
        AgentJob("capture", "relationship_round", provider, slot="relationship")
    )

    outputs = scheduler.dispatch_tick(world, tick=0)

    assert len(outputs) == 1
    assert provider.params["agent_context_packet"]["schema"] == CONTEXT_PACKET_SCHEMA
    assert provider.params["agent_context_packet"]["job"]["id"] == "capture"
    assert (
        len(provider.params["agent_context_packet"]["active_candidates"])
        == RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    )
    assert (
        outputs[0].metadata["context_packet"]["active_candidate_count"]
        == RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    )


def test_json_llm_provider_adapter_builds_envelope_and_parses_boundary_output() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    base_job = AgentJob(
        "llm-relationship",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    context_packet = relationship_context_packet(world, base_job)
    first_active_id = context_packet["active_candidates"][0]["id"]
    first_active = world.node(first_active_id)
    world.set_movement_target(
        first_active_id,
        (first_active.position.x + 1, first_active.position.y),
        0.5,
    )
    client = FakeJsonClient()
    provider = JsonLlmProviderAdapter(
        client=client,
        allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
        allowed_relationship_types={"coordination"},
    )

    output = provider.observe(
        ProviderContext(
            world=world,
            tick=0,
            snapshot=world.snapshot(),
            params={"agent_context_packet": context_packet},
        )
    )

    assert client.envelope["schema"] == LLM_PROMPT_ENVELOPE_SCHEMA
    assert client.envelope["context_packet"]["schema"] == "agent_model_context_v2"
    assert client.envelope["context_packet"]["audit_schema"] == CONTEXT_PACKET_SCHEMA
    assert "80 characters" in client.envelope["expected_output"]["summary"]
    assert (
        client.envelope["expected_output"]["required_active_node_count"]
        == ACTIVE_NODE_LIMIT
    )
    assert client.envelope["expected_output"]["allowed_rule_names"] == sorted(
        ENTERPRISE_AGENT_RULES
    )
    thought_contract = client.envelope["expected_output"]["node_updates"][0]["thought"]
    assert "hard generation budget" in thought_contract
    assert "exactly 10 valid, distinct node ids" in client.envelope["instructions"]
    assert "All six fields are mandatory" in client.envelope["instructions"]
    assert (
        "All ten returned active nodes must select a complete action intention"
        in client.envelope["instructions"]
    )
    assert output.summary == "LLM emitted structured pressure."
    assert output.effects[0].type == "thought_bubble_add"
    assert (
        len([effect for effect in output.effects if effect.type == "rule_pressure_add"])
        == 10
    )
    assert output.metadata["provider_output_boundary"]["raw_effect_count"] == 1
    assert output.metadata["provider_output_boundary"]["accepted_effect_count"] > 1
    assert (
        output.metadata["provider_output_boundary"]["accepted_action_node_count"] == 10
    )
    assert (
        output.metadata["relationship_round"]["active_node_count"] == ACTIVE_NODE_LIMIT
    )
    assert (
        output.metadata["relationship_round"]["ripple_node_count"]
        == REQUIRED_RIPPLE_NODE_COUNT
    )
    assert all(
        len(targets) == RIPPLE_TARGETS_PER_ACTIVE
        for targets in output.metadata["relationship_round"][
            "ripple_targets_by_active"
        ].values()
    )
    adapter_metadata = output.metadata["llm_provider_adapter"]
    assert adapter_metadata["schema"] == LLM_PROMPT_ENVELOPE_SCHEMA
    assert adapter_metadata["provider"] == "json-llm-provider"
    assert adapter_metadata["context_packet_schema"] == CONTEXT_PACKET_SCHEMA
    assert (
        adapter_metadata["active_candidate_count"]
        == RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    )
    assert adapter_metadata["required_active_node_count"] == ACTIVE_NODE_LIMIT
    assert adapter_metadata["attempts"] == 1
    assert adapter_metadata["repair_attempts"] == 0
    assert adapter_metadata["repair_errors"] == []
    assert adapter_metadata["prompt_template_version"] == LLM_PROMPT_TEMPLATE_VERSION
    assert (
        adapter_metadata["model_context"]["projection"]
        == "relationship_model_context_v2"
    )
    assert adapter_metadata["model_context"]["section_bytes"]["l0_decision"] > 0


def test_live_key_character_action_seeds_grounded_relationship_influence() -> None:
    class ProactiveClient:
        def complete(self, envelope: dict) -> dict:
            return key_character_response(envelope)

    world = World.scenario("enterprise_earth", seed=7)
    job, packet = key_character_context_packet(world)
    target_id = job.metadata["target_node_id"]
    before_positions = {
        node_id: (node.position.x, node.position.y)
        for node_id, node in world.nodes.items()
    }
    output = JsonLlmProviderAdapter(
        client=ProactiveClient(),
        allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
    ).observe(
        ProviderContext(
            world=world,
            tick=world.tick,
            snapshot=world.snapshot(),
            params={"agent_context_packet": packet},
        )
    )

    influence_pressures = [
        item.to_dict()
        for item in output.effects
        if item.type == "rule_pressure_add"
        and item.fields.get("origin") == "key_character_influence"
    ]
    influence_memories = [
        item.to_dict()
        for item in output.effects
        if item.type == "memory_add"
        and item.fields.get("metadata", {}).get("origin") == "key_character_influence"
    ]
    state_effect = next(
        item for item in output.effects if item.type == "key_character_state"
    )
    initiative = state_effect.fields["value"]["current_initiative"]

    assert influence_pressures
    assert influence_memories
    assert all(item["influenced_by"] == target_id for item in influence_pressures)
    assert all(
        item["initiative_id"] == initiative["initiative_id"]
        and item["propagation_depth"] == 1
        and item["pressure_id"].startswith("pressure-")
        and item["weight"] > 0.15
        for item in influence_pressures
    )
    assert not any(
        item.type in {"node_position", "resource_delta", "fact_set"}
        for item in output.effects
    )

    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source=output.source,
            actor_type="agent",
            actor_id="proactive-key-character-test",
            action="key_character_continuity",
            summary=output.summary,
            effects=output.effects,
            apply_mode=APPLY_AUTHORITATIVE,
            metadata=output.metadata,
        ),
    )

    stored = world.node(target_id).key_character
    assert stored["current_initiative"]["initiative_id"] == initiative["initiative_id"]
    assert stored["last_progress_delta"]
    assert {
        node_id: (node.position.x, node.position.y)
        for node_id, node in world.nodes.items()
    } == before_positions

    influenced_ids = {
        item["target"].removeprefix("node:") for item in influence_pressures
    }
    relationship_job = next(
        item
        for item in enterprise_agent_jobs(world, include_static_lenses=False)
        if item.kind == "relationship_round"
        and influenced_ids.intersection(item.metadata["candidate_node_ids"])
    )
    relationship_packet = AgentContextPacketBuilder().build(world, relationship_job)
    relationship_context, _ = compile_agent_model_context(relationship_packet)
    visible_pressures = [
        pressure
        for row in relationship_context["decision_context"]["current_pressures_by_node"]
        for pressure in row["pressures"]
        if pressure["origin"] == "key_character_influence"
    ]

    assert visible_pressures
    assert all(
        pressure["influenced_by"] == target_id
        and pressure["initiative_id"] == initiative["initiative_id"]
        and pressure["propagation_depth"] == 1
        and pressure["propagation_goal"]
        for pressure in visible_pressures
    )


def test_key_character_continuity_keeps_bounded_previous_and_current_initiatives() -> (
    None
):
    class ProactiveClient:
        def __init__(self, progress_delta: str) -> None:
            self.progress_delta = progress_delta

        def complete(self, envelope: dict) -> dict:
            response = key_character_response(
                envelope,
                progress_delta=self.progress_delta,
            )
            response["initiative"]["action"] = self.progress_delta
            return response

    world = World.scenario("enterprise_earth", seed=7)
    target_id = "key-albert-einstein"
    initiative_ids: list[str] = []
    for progress_delta in (
        "Published the first falsifiable comparison.",
        "Secured a second institution's independent review.",
    ):
        _, packet = key_character_context_packet(world, target_id)
        output = JsonLlmProviderAdapter(
            client=ProactiveClient(progress_delta),
            allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
        ).observe(
            ProviderContext(
                world=world,
                tick=world.tick,
                snapshot=world.snapshot(),
                params={"agent_context_packet": packet},
            )
        )
        state_effect = next(
            item for item in output.effects if item.type == "key_character_state"
        )
        initiative_ids.append(
            state_effect.fields["value"]["current_initiative"]["initiative_id"]
        )
        FeedbackIngestor().ingest(
            world,
            ActionFeedback(
                source=output.source,
                actor_type="agent",
                actor_id="bounded-continuity-test",
                action="key_character_continuity",
                summary=output.summary,
                effects=output.effects,
                apply_mode=APPLY_AUTHORITATIVE,
                metadata=output.metadata,
            ),
        )

    state = world.node(target_id).key_character
    assert initiative_ids[0] != initiative_ids[1]
    assert state["initiative_generation"] == 2
    assert state["previous_initiative"]["initiative_id"] == initiative_ids[0]
    assert state["current_initiative"]["initiative_id"] == initiative_ids[1]
    assert state["last_progress_delta"] == (
        "Secured a second institution's independent review."
    )
    assert "initiative_history" not in state


@pytest.mark.parametrize(
    ("path", "replacement", "error"),
    [
        (("progress_delta",), None, "non-empty agency fields"),
        (
            ("previous_action_assessment",),
            None,
            "previous_action_assessment",
        ),
        (("initiative",), None, "requires initiative"),
        (
            ("selected_action_option_id",),
            None,
            "complete grounded action fields",
        ),
        (
            ("initiative", "target_node_ids"),
            ["node-outside-current-context"],
            "must come from current influence nodes or peers",
        ),
        (
            ("initiative", "impact_scale"),
            1.1,
            "impact_scale must be between 0 and 1",
        ),
        (
            ("progress_delta",),
            "Already advanced this exact test.",
            "must advance beyond the prior heartbeat",
        ),
    ],
)
def test_key_character_boundary_rejects_incomplete_or_repeated_agency(
    path: tuple[str, ...],
    replacement: object,
    error: str,
) -> None:
    class InvalidAgencyClient:
        def complete(self, envelope: dict) -> dict:
            response = key_character_response(envelope)
            current = response
            for key in path[:-1]:
                current = current[key]
            if replacement is None:
                current.pop(path[-1])
            else:
                current[path[-1]] = replacement
            return response

    world = World.scenario("enterprise_earth", seed=7)
    world.node("key-albert-einstein").key_character["last_progress_delta"] = (
        "Already advanced this exact test."
    )
    _, packet = key_character_context_packet(world)

    with pytest.raises(ValueError, match=error):
        JsonLlmProviderAdapter(
            client=InvalidAgencyClient(),
            allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
        ).observe(
            ProviderContext(
                world=world,
                tick=world.tick,
                snapshot=world.snapshot(),
                params={"agent_context_packet": packet},
            )
        )


def test_enterprise_relationship_http_payload_is_compact_and_complete() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = enterprise_agent_jobs(world, include_static_lenses=False)[0]
    before = world.snapshot()
    packet = AgentContextPacketBuilder().build(world, job)
    packet["groundable_action_options"] = groundable_action_options(
        world,
        [item["id"] for item in packet["active_candidates"]],
        ENTERPRISE_AGENT_RULES,
    )
    client = OpenAICompatibleJsonClient(
        api_key="secret-token",
        base_url="https://example.test/v1",
        model="test-model",
        max_tokens=1400,
    )
    envelope = JsonLlmProviderAdapter(client=client).build_envelope(
        ProviderContext(world=world, tick=0, snapshot=before, params={}),
        packet,
    )
    model_packet = envelope["context_packet"]
    raw_payload = json.dumps(client.build_payload(envelope), ensure_ascii=False).encode(
        "utf-8"
    )

    assert len(raw_payload) <= 25 * 1024
    assert model_packet["projection"] == "relationship_model_context_v2"
    decision_context = model_packet["decision_context"]
    assert [item["id"] for item in decision_context["coverage_nodes"]] == [
        item["id"] for item in packet["coverage_nodes"]
    ]
    assert [item["id"] for item in decision_context["active_candidates"]] == [
        item["id"] for item in packet["active_candidates"]
    ]
    assert model_packet["episodic_evidence"]
    assert model_packet["continuity_context"]["domain_summary"]
    assert decision_context["graph"]["edges"]
    assert "groundable_action_options" not in model_packet
    assert decision_context["action_options_by_node"]
    assert all(
        set(option) <= {"option_id", "rule", "target"}
        for group in decision_context["action_options_by_node"]
        for option in group["options"]
    )
    assert "decision_context.action_options_by_node" in envelope["instructions"]
    payload = client.build_payload(envelope)
    assert "instructions" not in json.loads(payload["messages"][1]["content"])
    assert "expected_output" not in json.loads(payload["messages"][1]["content"])
    assert client.build_payload(envelope)["max_tokens"] == 1400
    assert world.snapshot() == before


def test_relationship_http_payload_keeps_stable_contract_before_dynamic_context() -> (
    None
):
    world = World.scenario("enterprise_earth", seed=7)
    first_job = AgentJob(
        "relationship-prefix-a",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    second_job = AgentJob(
        "relationship-prefix-b",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    first_packet = relationship_context_packet(world, first_job)
    second_packet = relationship_context_packet(world, second_job)
    client = OpenAICompatibleJsonClient(
        api_key="secret-token",
        base_url="https://example.test/v1",
        model="test-model",
    )
    adapter = JsonLlmProviderAdapter(
        client=client,
        allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
    )

    first_payload = client.build_payload(
        adapter.build_envelope(
            ProviderContext(world=world, tick=0, snapshot=world.snapshot(), params={}),
            first_packet,
        )
    )
    second_payload = client.build_payload(
        adapter.build_envelope(
            ProviderContext(world=world, tick=53, snapshot=world.snapshot(), params={}),
            second_packet,
        )
    )

    assert (
        first_payload["messages"][0]["content"]
        == second_payload["messages"][0]["content"]
    )
    assert (
        first_payload["messages"][1]["content"]
        != second_payload["messages"][1]["content"]
    )
    stable = json.loads(first_payload["messages"][0]["content"])
    dynamic = json.loads(first_payload["messages"][1]["content"])
    assert stable["prompt_template_version"] == LLM_PROMPT_TEMPLATE_VERSION
    assert "expected_output" in stable
    assert "instructions" in stable
    assert "expected_output" not in dynamic
    assert "instructions" not in dynamic
    assert dynamic["context_packet"]["projection"] == "relationship_model_context_v2"


def test_json_llm_provider_adapter_rejects_missing_context_packet() -> None:
    world = World.scenario("enterprise_earth", seed=7)

    with pytest.raises(ValueError, match="agent_context_packet"):
        JsonLlmProviderAdapter(client=FakeJsonClient()).observe(
            ProviderContext(world=world, tick=0, snapshot=world.snapshot(), params={})
        )


def test_provider_json_parser_repairs_one_premature_root_close_before_remaining_fields() -> (
    None
):
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"character_id":"key-a","plan_steps":["inspect","act"]},'
                        '"rule_reason":"continue","summary":"valid after local syntax recovery"}'
                    )
                }
            }
        ]
    }

    parsed = extract_json_provider_output(response)

    assert parsed == {
        "character_id": "key-a",
        "plan_steps": ["inspect", "act"],
        "rule_reason": "continue",
        "summary": "valid after local syntax recovery",
    }


def test_json_llm_provider_adapter_accepts_visible_thought_alias() -> None:
    class VisibleThoughtClient:
        def complete(self, envelope: dict) -> dict:
            updates = relationship_node_updates(envelope)
            updates[0]["visible_thought"] = (
                "This sentence came from the live model response."
            )
            return {
                "summary": "Visible model thought.",
                "node_updates": updates,
            }

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "visible-thought",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
    )
    context_packet = relationship_context_packet(world, job)

    output = JsonLlmProviderAdapter(client=VisibleThoughtClient()).observe(
        ProviderContext(
            world=world,
            tick=0,
            snapshot=world.snapshot(),
            params={"agent_context_packet": context_packet},
        )
    )

    thought_text = " ".join(
        str(effect.fields.get("text", ""))
        for effect in output.effects
        if effect.type in {"thought_bubble_add", "thought_schedule_add"}
    )
    assert "live model response" in thought_text


def test_json_llm_provider_adapter_preserves_out_of_budget_thoughts_without_repair() -> (
    None
):
    short_thought = "太短。"
    long_thought = "这段思考故意明显超过四十八个字符，用来证明生成完成后边界不会截断内容，也不会为无法节省的令牌发起修复请求。"

    class OutOfBudgetThoughtClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, envelope: dict) -> dict:
            self.calls += 1
            updates = relationship_node_updates(envelope)
            updates[0]["visible_thought"] = short_thought
            updates[1]["visible_thought"] = long_thought
            return {"summary": "Preserve generated thoughts.", "node_updates": updates}

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "thought-budget", "relationship_round", DeterministicRelationshipRoundProvider()
    )
    context_packet = relationship_context_packet(world, job)
    client = OutOfBudgetThoughtClient()

    output = JsonLlmProviderAdapter(client=client, max_attempts=2).observe(
        ProviderContext(
            world=world,
            tick=0,
            snapshot=world.snapshot(),
            params={"agent_context_packet": context_packet},
        )
    )

    memory_texts = [
        str(effect.fields.get("text", ""))
        for effect in output.effects
        if effect.type == "memory_add"
    ]
    assert any(text.endswith(short_thought) for text in memory_texts)
    assert any(text.endswith(long_thought) for text in memory_texts)
    assert client.calls == 1
    assert output.metadata["llm_provider_adapter"]["repair_attempts"] == 0


def test_key_character_boundary_repairs_invented_option_to_target_node() -> None:
    class InventedOptionClient:
        def complete(self, envelope: dict) -> dict:
            response = key_character_response(envelope)
            response["selected_action_option_id"] = "publish_public_test"
            return response

    world = World.scenario("enterprise_earth", seed=7)
    target_id = "key-albert-einstein"
    _, packet = key_character_context_packet(world, target_id)
    valid_ids = {
        item["option_id"]
        for item in packet["groundable_action_options"]
        if item["node_id"] == target_id
    }

    output = JsonLlmProviderAdapter(
        client=InventedOptionClient(),
        allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
    ).observe(
        ProviderContext(
            world=world,
            tick=world.tick,
            snapshot=world.snapshot(),
            params={"agent_context_packet": packet},
        )
    )

    boundary = output.metadata["provider_output_boundary"]
    repair = boundary["action_option_repairs"][0]
    state_effect = next(
        item for item in output.effects if item.type == "key_character_state"
    )
    assert boundary["action_option_repair_count"] == 1
    assert repair["node_id"] == target_id
    assert repair["original_option_id"] == "publish_public_test"
    assert repair["repaired_option_id"] in valid_ids
    assert (
        state_effect.fields["value"]["selected_action_option_id"]
        == repair["repaired_option_id"]
    )


def test_json_llm_provider_adapter_rejects_client_direct_mutation_output() -> None:
    class DirectMutationClient:
        def complete(self, envelope: dict) -> dict:
            active = envelope["context_packet"]["decision_context"][
                "active_candidates"
            ][0]
            return {
                "summary": "Bad mutation.",
                "effects": [
                    {
                        "type": "node_position",
                        "target": f"node:{active['id']}",
                        "position": {"x": 100, "y": 100},
                    }
                ],
            }

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "bad-llm",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    context_packet = relationship_context_packet(world, job)

    with pytest.raises(ValueError, match="direct mutation"):
        JsonLlmProviderAdapter(client=DirectMutationClient()).observe(
            ProviderContext(
                world=world,
                tick=0,
                snapshot=world.snapshot(),
                params={"agent_context_packet": context_packet},
            )
        )


def test_json_llm_provider_adapter_repairs_boundary_error_with_feedback() -> None:
    class RepairingClient:
        def __init__(self) -> None:
            self.envelopes: list[dict] = []

        def complete(self, envelope: dict) -> dict:
            self.envelopes.append(envelope)
            if len(self.envelopes) == 1:
                return {
                    "summary": "Incomplete relationship round.",
                    "node_updates": relationship_node_updates(
                        envelope, ACTIVE_NODE_LIMIT - 1
                    ),
                }
            return {
                "summary": "Repaired pressure.",
                "node_updates": relationship_node_updates(envelope),
            }

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "repair-llm",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    context_packet = relationship_context_packet(world, job)
    active_id = context_packet["active_candidates"][0]["id"]
    active_node = world.node(active_id)
    world.set_movement_target(
        active_id,
        (active_node.position.x + 1, active_node.position.y),
        0.5,
    )
    client = RepairingClient()

    output = JsonLlmProviderAdapter(
        client=client,
        allowed_rule_names=set(ENTERPRISE_AGENT_RULES),
        max_attempts=2,
    ).observe(
        ProviderContext(
            world=world,
            tick=0,
            snapshot=world.snapshot(),
            params={"agent_context_packet": context_packet},
        )
    )

    assert output.summary == "Repaired pressure."
    assert len(client.envelopes) == 2
    assert "repair_feedback" not in client.envelopes[0]
    assert client.envelopes[1]["repair_feedback"]["previous_errors"][0]["attempt"] == 1
    assert (
        "requires exactly 10"
        in client.envelopes[1]["repair_feedback"]["previous_errors"][0]["error"]
    )
    assert (
        "got 9" in client.envelopes[1]["repair_feedback"]["previous_errors"][0]["error"]
    )
    assert (
        output.metadata["relationship_round"]["active_node_count"] == ACTIVE_NODE_LIMIT
    )
    assert output.metadata["llm_provider_adapter"]["attempts"] == 2
    assert output.metadata["llm_provider_adapter"]["repair_attempts"] == 1
    assert output.metadata["provider_runtime"]["attempts"] == 2


def test_json_llm_provider_adapter_reports_exhausted_repair_attempts() -> None:
    class AlwaysInvalidClient:
        def complete(self, envelope: dict) -> dict:
            active = envelope["context_packet"]["decision_context"][
                "active_candidates"
            ][0]
            return {
                "summary": "Still bad.",
                "effects": [
                    {
                        "type": "node_position",
                        "target": f"node:{active['id']}",
                        "position": {"x": 1, "y": 1},
                    }
                ],
            }

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "invalid-llm",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    context_packet = relationship_context_packet(world, job)

    with pytest.raises(RuntimeError, match="failed after 2 attempt"):
        JsonLlmProviderAdapter(client=AlwaysInvalidClient(), max_attempts=2).observe(
            ProviderContext(
                world=world,
                tick=0,
                snapshot=world.snapshot(),
                params={"agent_context_packet": context_packet},
            )
        )


def test_json_llm_provider_adapter_enforces_one_shared_hard_deadline() -> None:
    class SlowClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, envelope: dict) -> dict:
            self.calls += 1
            sleep(0.1)
            return {
                "summary": "too late",
                "node_updates": relationship_node_updates(envelope),
            }

        def complete_with_context(
            self,
            envelope: dict,
            *,
            cancellation,
            timeout: float | None,
        ) -> dict:
            self.calls += 1
            deadline = perf_counter() + float(timeout or 0.1)
            while perf_counter() < deadline:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                sleep(0.001)
            raise ProviderDeadlineExceeded("cooperative fake deadline exceeded")

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "deadline-llm", "relationship_round", DeterministicRelationshipRoundProvider()
    )
    context_packet = relationship_context_packet(world, job)
    client = SlowClient()
    started = perf_counter()

    output = JsonLlmProviderAdapter(
        client=client, max_attempts=2, deadline_seconds=0.02
    ).observe(
        ProviderContext(
            world=world,
            tick=0,
            snapshot=world.snapshot(),
            params={"agent_context_packet": context_packet},
        )
    )

    assert perf_counter() - started < 0.08
    assert client.calls == 1
    assert output.effects == []
    assert output.metadata["provider_timeout"]["type"] == "provider_deadline_exceeded"
    assert output.metadata["provider_runtime"]["status"] == "timed_out"
    assert output.metadata["provider_runtime"]["attempts"] == 1


def test_json_llm_provider_adapter_cancels_before_transport_call() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, envelope: dict) -> dict:
            self.calls += 1
            return {
                "summary": "unexpected",
                "node_updates": relationship_node_updates(envelope),
            }

    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        "canceled-llm",
        "relationship_round",
        DeterministicRelationshipRoundProvider(),
    )
    token = CancellationToken()
    token.cancel("operator canceled")
    client = RecordingClient()

    with pytest.raises(ProviderCancelled, match="operator canceled"):
        JsonLlmProviderAdapter(client=client).observe(
            ProviderContext(
                world=world,
                tick=0,
                snapshot=world.snapshot(),
                params={
                    "agent_context_packet": relationship_context_packet(world, job)
                },
                cancellation=token,
            )
        )

    assert client.calls == 0
