import json

from ai_native_world_engine.core import (
    ACTIVE_NODE_LIMIT,
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    AgentContextPacketBuilder,
    AgentJob,
    AgentScheduler,
    AgentSchedulerConfig,
    CONTEXT_PACKET_SCHEMA,
    MODEL_CONTEXT_SCHEMA,
    DeterministicCommercialLensProvider,
    DeterministicKeyCharacterContinuityProvider,
    DeterministicRelationshipRoundProvider,
    FeedbackIngestor,
    RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT,
    RelationshipSubgraphBuilder,
    RuleEngineSet,
    World,
    compile_agent_model_context,
    effect,
)


def test_context_packet_builder_is_read_only() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    world.node("org-science-council").memories.append(
        {"text": "science council resource coordination note", "source": "test", "importance": 0.7}
    )
    job = AgentJob(
        id="relationship",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    before = world.snapshot()

    packet = AgentContextPacketBuilder().build(world, job)

    assert packet["schema"] == CONTEXT_PACKET_SCHEMA
    assert "domain_summary" in packet
    assert "memory_context" in packet
    assert packet["memory_context"]
    assert packet["graph_context"]["domain_profiles"]
    assert world.snapshot() == before
    json.dumps(packet, ensure_ascii=False)


def test_relationship_round_packet_uses_wide_coverage_and_sixteen_active_candidates() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        id="relationship",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )

    packet = AgentContextPacketBuilder().build(world, job)

    assert len(packet["coverage_nodes"]) > RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert len(packet["active_candidates"]) == RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert all(
        node["attributes"]["agent_layer"] == "relationship_network_member"
        for node in packet["coverage_nodes"]
    )
    assert packet["constraints"]["active_candidate_limit"] == RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert packet["constraints"]["active_node_limit"] == ACTIVE_NODE_LIMIT
    assert packet["constraints"]["required_active_node_count"] == ACTIVE_NODE_LIMIT
    assert packet["constraints"]["thought_slice_count"] == 6
    assert packet["constraints"]["ripple_targets_per_active"] == 3
    assert packet["graph_context"]["stats"]["node_count"] >= RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert packet["graph_context"]["stats"]["edge_count"] > 0
    assert packet["graph_context"]["organizations"]


def test_key_character_packet_includes_continuity_fields() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    node = world.node("key-albert-einstein")
    node.key_character.update(
        {
            "status": "awake",
            "goal": "explain the coordination pattern",
            "current_step": "compare recent traces",
            "salience_score": 0.91,
        }
    )
    job = AgentJob(
        id="key-character",
        kind="key_character_continuity",
        provider=DeterministicKeyCharacterContinuityProvider(),
        slot="key_character",
    )

    packet = AgentContextPacketBuilder().build(world, job)
    key_nodes = [item for item in packet["coverage_nodes"] if item["id"] == "key-albert-einstein"]

    assert len(packet["coverage_nodes"]) == 5
    assert key_nodes
    assert key_nodes[0]["key_character"] == {
        "status": "awake",
        "goal": "explain the coordination pattern",
        "current_step": "compare recent traces",
        "salience_score": 0.91,
        "identity": "scientist",
        "agent_layer": "key_character",
    }


def test_commercial_lens_packet_includes_lens_metadata_and_constraints() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        id="lens",
        kind="commercial_lens",
        provider=DeterministicCommercialLensProvider("resource_supply"),
        slot="lens",
        metadata={"lens_id": "resource_supply", "scenario": "enterprise_earth"},
    )

    packet = AgentContextPacketBuilder().build(world, job)

    assert packet["job"]["metadata"]["lens_id"] == "resource_supply"
    assert packet["constraints"]["lens_id"] == "resource_supply"
    assert packet["constraints"]["origin"] == "commercial_relationship_lens"
    assert packet["coverage_nodes"]
    assert len(packet["active_candidates"]) <= 12
    assert all(
        node["attributes"]["agent_layer"] == "relationship_network_member"
        for node in packet["coverage_nodes"]
    )


def test_scheduler_output_includes_context_packet_summary() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    scheduler = AgentScheduler(
        AgentSchedulerConfig(enabled=True, max_concurrent=1, dispatch_slots=["relationship"])
    )
    scheduler.enqueue(
        AgentJob(
            id="relationship",
            kind="relationship_round",
            provider=DeterministicRelationshipRoundProvider(),
            slot="relationship",
        )
    )

    outputs = scheduler.dispatch_tick(world, tick=0)

    assert len(outputs) == 1
    context_packet = outputs[0].metadata["context_packet"]
    assert context_packet["schema"] == CONTEXT_PACKET_SCHEMA
    assert context_packet["coverage_count"] > RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert context_packet["active_candidate_count"] == RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert "ai_trace_count" in context_packet
    assert context_packet["graph_node_count"] >= RELATIONSHIP_ACTIVE_CANDIDATE_LIMIT
    assert context_packet["graph_edge_count"] > 0
    assert "domain_covered_domains" in context_packet
    assert "memory_context_count" in context_packet
    assert "pressure_action_reflection_count" in context_packet
    assert "observation_reflection_count" in context_packet
    assert outputs[0].metadata["provider_boundary"] == {
        "replaceable_provider": True,
        "provider_name": "deterministic-relationship-round",
        "context_schema": CONTEXT_PACKET_SCHEMA,
        "expected_output_style": "ai_isekai_node_edge_updates_key_character_pressure_or_structured_effects",
        "world_authority": "rule_engine_feedback",
    }


def test_relationship_subgraph_builder_extracts_resources_threats_and_organizations() -> None:
    world = World("graph-context")
    world.add_node(
        "org",
        "organization",
        "Org",
        (0, 0),
        {
            "organization_kind": "research",
            "members": ["a", "b"],
            "supply_chain": {"bottlenecks": ["bridge"]},
        },
    )
    world.add_node(
        "a",
        "person",
        "A",
        (1, 0),
        {
            "parent_network": "org",
            "resources": {"food": 2},
            "terrain_type": "urban",
            "belief:trust": 1,
        },
    )
    world.add_node("b", "person", "B", (2, 0), {"parent_network": "org", "hazard": "smoke"})
    world.add_relationship("a", "org", "member_of", 0.9)
    world.add_relationship("a", "b", "threat", -0.4, {"reason": "test"})
    world.add_relationship("org", "a", "supply_route", 0.8, {"status": "open"})

    subgraph = RelationshipSubgraphBuilder().build(world, ["a"], depth=1).to_dict()

    assert {node["id"] for node in subgraph["nodes"]} == {"a", "b", "org"}
    assert len(subgraph["edges"]) == 3
    assert subgraph["resources"] == [{"node_id": "a", "resources": {"resources": {"food": 2}}}]
    assert subgraph["threats"][0]["type"] == "threat"
    assert subgraph["organizations"][0]["id"] == "org"
    assert subgraph["terrain"] == [
        {"node_id": "a", "terrain": {"terrain_type": "urban"}},
        {"node_id": "b", "terrain": {"hazard": "smoke"}},
    ]
    assert any(item["kind"] == "route" and item["type"] == "supply_route" for item in subgraph["supply_chains"])
    assert len(subgraph["domain_profiles"]) == 3
    assert subgraph["stats"]["domain_profile_count"] == 3
    json.dumps(subgraph, ensure_ascii=False)


def test_context_packet_includes_ranked_memory_and_domain_summary() -> None:
    world = World("context-rich", {"scenario": "context-rich"})
    node = world.add_node(
        "node-a",
        "person",
        "Node A",
        (0, 0),
        {"agent_layer": "relationship_network_member", "resources": {"food": 1}, "belief:trust": 1},
    )
    world.add_node("node-b", "person", "Node B", (1, 0), {"agent_layer": "relationship_network_member"})
    world.add_relationship("node-a", "node-b", "trust", 0.7)
    node.memories.extend(
        [
            {"text": "ordinary update", "source": "test", "importance": 0.1},
            {"text": "relationship_round trust response", "source": "test", "importance": 0.8},
        ]
    )
    job = AgentJob(
        id="relationship",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )

    before = world.snapshot()
    packet = AgentContextPacketBuilder().build(world, job)

    assert world.snapshot() == before
    assert packet["domain_summary"]["domain_model_coverage"]["by_domain"]["beliefs"] == 1
    assert len(packet["memory_context"]) <= 8
    memory = next(
        item
        for item in packet["memory_context"]
        if item["node_id"] == "node-a"
        and item["kind"] == "memory"
        and "relationship_round" in item["text"]
    )
    assert memory["score"] > 0


def test_context_packet_includes_pressure_action_and_ai_reflections() -> None:
    world = World("reflection-context", {"scenario": "reflection-context"})
    node = world.add_node(
        "node-a",
        "person",
        "Node A",
        (0, 0),
        {"agent_layer": "relationship_network_member"},
    )
    world.add_node("node-b", "person", "Node B", (1, 0), {"agent_layer": "relationship_network_member"})
    world.set_movement_target(node.id, (2, 0), 1)
    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="relationship-agent",
            actor_type="agent",
            actor_id="relationship-agent",
            action="node_updates",
            summary="agent pressure",
            effects=[
                effect("thought_bubble_add", target=f"node:{node.id}", text="move toward the network", source="relationship-agent"),
                effect("rule_pressure_add", target=f"node:{node.id}", rule="move", weight=1.0, ttl=3, source="relationship-agent"),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )
    RuleEngineSet.from_scenario(["movement"]).step(world)
    job = AgentJob(
        id="relationship",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )

    packet = AgentContextPacketBuilder().build(world, job)
    reflection = next(item for item in packet["observation_reflections"] if item["node_id"] == node.id)

    assert packet["pressure_action_reflections"]
    assert packet["pressure_action_reflections"][0]["matched"] is True
    assert any(
        item["node_id"] == node.id
        and item["kind"] == "pressure_action_reflection"
        and "grounded=move" in item["text"]
        for item in packet["memory_context"]
    )
    assert any(
        item["node_id"] == node.id
        and item["kind"] == "causality_reflection"
        and "rule=move" in item["text"]
        for item in packet["memory_context"]
    )
    assert reflection["pressure_action"][0]["matched"] is True
    assert reflection["ai_causality"][0]["grounded_action"] == "move"


def test_relationship_model_context_deduplicates_causal_evidence_without_mutating_audit_packet() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        id="relationship-evidence",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    packet = AgentContextPacketBuilder().build(world, job)
    node_id = packet["active_candidates"][0]["id"]
    reflection = {
        "node_id": node_id,
        "tick": 7,
        "sequence": 91,
        "rule": "collaboration",
        "matched": False,
        "status": "pending_observation",
        "expected_action": "organization_decision",
        "grounded_action": "",
        "grounded_summary": "",
    }
    packet["pressure_action_reflections"] = [reflection]
    packet["observation_reflections"] = [
        {"node_id": node_id, "pressure_action": [reflection], "ai_causality": []}
    ]
    before = json.dumps(packet, ensure_ascii=False, sort_keys=True)

    model_packet, metrics = compile_agent_model_context(packet)

    pressure_evidence = [
        item for item in model_packet["episodic_evidence"] if item["kind"] == "pressure_outcome"
    ]
    assert model_packet["schema"] == MODEL_CONTEXT_SCHEMA
    assert model_packet["projection"] == "relationship_model_context_v2"
    assert len(pressure_evidence) == 1
    assert set(pressure_evidence[0]["sources"]) == {
        "pressure_action_reflection",
        "observation_reflection",
    }
    assert metrics["evidence_duplicate_suppressed_count"] >= 1
    assert json.dumps(packet, ensure_ascii=False, sort_keys=True) == before


def test_relationship_domain_cards_do_not_grow_with_accumulated_history() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    job = AgentJob(
        id="relationship-domain",
        kind="relationship_round",
        provider=DeterministicRelationshipRoundProvider(),
        slot="relationship",
    )
    packet = AgentContextPacketBuilder().build(world, job)
    node_id = packet["active_candidates"][0]["id"]
    profile = next(
        item for item in packet["graph_context"]["domain_profiles"] if item["node_id"] == node_id
    )

    profile["publications"] = [
        {"title": f"historical publication {index}", "tick": index}
        for index in range(40)
    ]
    first, _ = compile_agent_model_context(packet)
    profile["publications"] = [
        {"title": f"discarded publication {index}", "tick": index}
        for index in range(200)
    ] + [{"title": "historical publication 39", "tick": 39}]
    second, _ = compile_agent_model_context(packet)

    first_card = next(
        item for item in first["continuity_context"]["domain_cards"] if item["node_id"] == node_id
    )
    second_card = next(
        item for item in second["continuity_context"]["domain_cards"] if item["node_id"] == node_id
    )
    assert first_card["publications"] == [{"title": "historical publication 39", "tick": 39}]
    assert second_card == first_card


def test_key_character_model_context_uses_target_continuity_and_compact_peer_cards() -> None:
    world = World.scenario("enterprise_earth", seed=7)
    target_id = "key-albert-einstein"
    target = world.node(target_id)
    target.key_character.update(
        {
            "self_narrative": "I turn evidence into explanations.",
            "personality_profile": {"values": ["clarity"], "boundaries": ["respect evidence"]},
            "goal_status": "continue",
            "plan_reason": "The current signal needs a testable account.",
            "plan_steps": ["compare evidence", "state a hypothesis"],
            "last_progress_delta": "Compared the newest coordination traces.",
            "last_action_assessment": {
                "status": "partial",
                "evidence": "One institution acknowledged the comparison.",
                "consequence": "Publish a sharper test next.",
            },
            "previous_initiative": {
                "initiative_id": "initiative-previous",
                "generation": 1,
                "action": "Compare the available evidence.",
                "target_node_ids": ["key-marie-curie"],
                "expected_change": "Expose one disputed assumption.",
                "propagation_goal": "Invite peer review.",
                "impact_scale": 0.6,
            },
            "current_initiative": {
                "initiative_id": "initiative-current",
                "generation": 2,
                "action": "Publish a testable account.",
                "target_node_ids": ["key-marie-curie"],
                "expected_change": "Create an auditable hypothesis.",
                "propagation_goal": "Let institutions test the account.",
                "impact_scale": 0.8,
            },
            "initiative_generation": 2,
            "commitments": [
                {"target": "key-marie-curie", "status": "pending", "summary": "share evidence"}
            ],
        }
    )
    peer = world.node("key-marie-curie")
    peer.memories.append(
        {"text": "A very long peer history that must become one recent change.", "source": "test"}
    )
    peer.key_character.update(
        {
            "personality_profile": {"values": ["full peer personality must not be copied"]},
            "peer_interactions": [
                {
                    "target": target_id,
                    "status": "acknowledged",
                    "stance": "supportive",
                    "summary": "compare data",
                }
            ],
        }
    )
    job = AgentJob(
        id="key-character-layered",
        kind="key_character_continuity",
        provider=DeterministicKeyCharacterContinuityProvider(),
        slot="key_character",
        metadata={
            "target_node_id": target_id,
            "candidate_node_ids": [target_id],
            "coverage_node_ids": [target_id],
        },
    )
    packet = AgentContextPacketBuilder().build(world, job)

    model_packet, metrics = compile_agent_model_context(packet)

    assert model_packet["projection"] == "key_character_model_context_v2"
    assert (
        model_packet["continuity_context"]["target"]["self_narrative"]
        == target.key_character["self_narrative"]
    )
    continuity = model_packet["continuity_context"]["target"]
    assert continuity["last_progress_delta"] == target.key_character["last_progress_delta"]
    assert continuity["last_action_assessment"]["status"] == "partial"
    assert continuity["previous_initiative"]["initiative_id"] == "initiative-previous"
    assert continuity["current_initiative"]["initiative_id"] == "initiative-current"
    assert continuity["initiative_generation"] == 2
    peer_card = next(
        item for item in model_packet["continuity_context"]["peers"] if item["id"] == peer.id
    )
    assert peer_card["direct_interaction"]["stance"] == "supportive"
    assert peer_card["recent_meaningful_change"].startswith("A very long peer history")
    assert "personality_profile" not in peer_card
    assert "recent_memories" not in peer_card
    assert metrics["section_bytes"]["l2_continuity"] > 0
