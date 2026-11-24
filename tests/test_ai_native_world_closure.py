from ai_native_world_engine.core import (
    MemoryQuery,
    Position,
    ProviderContext,
    RuleEngineSet,
    RunConfig,
    World,
    WorldDomainStateInspector,
    WorldMemoryConsolidator,
    WorldMemoryRetriever,
    DeterministicWorldDirectorProvider,
    WORLD_DIRECTOR_SOURCE,
    WORLD_ECOSYSTEM_RULES,
    evaluate_run,
    expand_rule_names,
    project_run_for_viewer,
    run,
)


EXPANDED_RULES = list(WORLD_ECOSYSTEM_RULES)


def test_expanded_rule_packages_ground_readme_action_classes() -> None:
    world = World("expanded-rules")
    world.add_node("attacker", "unit", "Attacker", (0, 0), {"alive": True})
    world.add_node("victim", "unit", "Victim", (1, 0), {"health": 5})
    world.add_node("carrier", "person", "Carrier", (0, 1))
    world.add_node("exposed", "person", "Exposed", (1, 1))
    world.add_node("authority", "organization", "Authority", (0, 2))
    world.add_node("depot", "organization", "Depot", (0, 3), {"resources": {"supplies": 5}})
    world.add_node("clinic", "organization", "Clinic", (1, 3), {"resources": {}})
    world.add_node("org", "organization", "Org", (0, 4))
    world.add_node("influencer", "person", "Influencer", (0, 5))
    world.add_node("audience", "person", "Audience", (1, 5))
    world.add_node("scientist", "key_character", "Scientist", (0, 6))
    world.add_node("migrant", "population_cohort", "Migrant", (0, 7))
    world.add_node("collaborator", "person", "Collaborator", (0, 8))
    world.add_node("partner", "person", "Partner", (1, 8))
    world.add_node("factory", "organization", "Factory", (0, 9), {"resources": {"ore": 5}, "production_capacity": 4})
    world.add_node("buyer", "organization", "Buyer", (0, 10), {"budget": 10, "resources": {}})
    world.add_node("seller", "organization", "Seller", (1, 10), {"budget": 2, "resources": {"tools": 4}})

    world.node("attacker").rule_pressures.append({"rule": "combat", "to": "node:victim", "damage": 2})
    world.node("carrier").rule_pressures.append({"rule": "infection", "to": "node:exposed", "pathogen": "demo"})
    world.node("authority").rule_pressures.append({"rule": "quarantine", "policy": "district_lockdown"})
    world.node("depot").rule_pressures.append({"rule": "logistics", "to": "node:clinic", "resource": "supplies", "amount": 3})
    world.node("org").rule_pressures.append({"rule": "organization_decision", "decision": "shift resources"})
    world.node("influencer").rule_pressures.append({"rule": "social_spread", "to": "node:audience", "signal": "trust"})
    world.node("scientist").rule_pressures.append({"rule": "science_publish", "title": "Grounded Note", "topic": "rules"})
    world.node("migrant").rule_pressures.append({"rule": "migration", "destination": "safe_zone"})
    world.node("collaborator").rule_pressures.append(
        {"rule": "collaboration", "with": "node:partner", "project": "shared response"}
    )
    world.node("factory").rule_pressures.append(
        {"rule": "production", "output_resource": "tools", "amount": 2, "input_costs": {"ore": 1}}
    )
    world.node("buyer").rule_pressures.append(
        {"rule": "economic_exchange", "from": "node:seller", "resource": "tools", "amount": 2, "unit_price": 3}
    )

    world.step(RuleEngineSet.from_scenario(EXPANDED_RULES))

    assert world.node("victim").attributes["health"] == 3
    assert world.node("exposed").attributes["infection"]["pathogen"] == "demo"
    assert world.node("authority").attributes["policies"]["district_lockdown"]["status"] == "active"
    assert world.node("depot").attributes["resources"]["supplies"] == 2
    assert world.node("clinic").attributes["resources"]["supplies"] == 3
    assert world.node("org").attributes["policies"]["organization_decision"]["status"] == "shift resources"
    assert world.node("audience").attributes["signal:trust"] == 1
    assert world.node("scientist").attributes["publications"][0]["title"] == "Grounded Note"
    assert world.node("migrant").attributes["migration"]["destination"] == "safe_zone"
    assert world.node("collaborator").attributes["collaborations"][0]["project"] == "shared response"
    assert world.node("factory").attributes["resources"]["tools"] == 2
    assert world.node("buyer").attributes["resources"]["tools"] == 2
    assert world.node("seller").attributes["budget"] == 8
    actions = {event["payload"].get("action") for event in world.events.recent() if event["kind"] == "action_feedback"}
    assert {
        "combat_attack",
        "infection_spread",
        "quarantine_policy",
        "logistics_transfer",
        "organization_decision",
        "social_spread",
        "science_publish",
        "migration",
        "collaboration",
        "production",
        "economic_exchange",
    }.issubset(actions)


def test_compound_crisis_scenario_is_reproducible() -> None:
    first = World.scenario("compound_crisis", seed=31).snapshot()
    second = World.scenario("compound_crisis", seed=31).snapshot()

    assert first == second
    assert first["attributes"]["scenario"] == "compound_crisis"
    assert first["attributes"]["governance"]["mode"] == "scenario_simulation"
    assert {node["id"] for node in first["nodes"]} >= {
        "authority",
        "operations-board",
        "carrier",
        "contact-vector",
        "susceptible",
        "depot",
        "patient",
        "scientist",
        "workshop",
        "market-buyer",
        "market-seller",
    }


def test_compound_crisis_run_produces_multi_rule_causal_chain() -> None:
    result = run(
        RunConfig(
            scenario="compound_crisis",
            seed=31,
            ticks=1,
            rules=EXPANDED_RULES,
            capture_timeline=True,
        )
    ).to_dict()
    nodes = {node["id"]: node for node in result["snapshot"]["nodes"]}
    actions = {event["payload"].get("action") for event in result["events"] if event["kind"] == "action_feedback"}

    assert {
        "infection_progress",
        "infection_spread",
        "quarantine_policy",
        "logistics_transfer",
        "combat_attack",
        "organization_decision",
        "social_spread",
        "science_publish",
        "migration",
        "collaboration",
        "production",
        "economic_exchange",
    }.issubset(actions)
    assert nodes["susceptible"]["attributes"]["infection"]["status"] == "exposed"
    assert "infection" not in nodes["isolated"]["attributes"]
    assert nodes["operations-board"]["attributes"]["policies"]["organization_decision"]["status"]
    assert nodes["patient"]["attributes"]["health"] == 8
    assert nodes["patient"]["attributes"]["resources"]["medical_supplies"] == 3
    assert nodes["raider"]["attributes"]["health"] < 5
    assert nodes["audience"]["attributes"]["signal:trust"] == 1
    assert nodes["scientist"]["attributes"]["publications"][0]["title"] == "Scenario Fever Field Note"
    assert nodes["evacuee"]["attributes"]["migration"]["status"] == "migrating"
    assert nodes["coordinator"]["attributes"]["collaborations"][0]["project"] == "door-to-door supply and isolation support"
    assert nodes["workshop"]["attributes"]["resources"]["raw_material"] == 3
    assert nodes["workshop"]["attributes"]["resources"]["repair_kits"] == 2
    assert nodes["workshop"]["attributes"]["production"]["last_project"] == "field equipment repair kits"
    assert nodes["market-buyer"]["attributes"]["resources"]["repair_kits"] == 2
    assert nodes["market-buyer"]["attributes"]["budget"] == 6
    assert nodes["market-seller"]["attributes"]["resources"]["repair_kits"] == 2
    assert nodes["market-seller"]["attributes"]["budget"] == 5
    assert result["scorecard"]["metrics"]["domain_active_infections"] >= 2
    assert result["timeline"][0]["projection"]["summary"]["domain_summary"]["infection"]["active_count"] >= 2
    assert any(trace["kind"] == "domain_lifecycle" for trace in result["traces"])
    assert any(trace["kind"] == "rule_decision" for trace in result["traces"])


def test_core_compound_crisis_run_uses_scenario_default_rule_ecosystem() -> None:
    result = run(RunConfig(scenario="compound_crisis", seed=31, ticks=1)).to_dict()
    actions = {event["payload"].get("action") for event in result["events"] if event["kind"] == "action_feedback"}

    assert result["config"]["rules"] == WORLD_ECOSYSTEM_RULES
    assert {
        "infection_progress",
        "infection_spread",
        "quarantine_policy",
        "logistics_transfer",
        "combat_attack",
        "organization_decision",
        "social_spread",
        "science_publish",
        "migration",
        "collaboration",
        "production",
        "economic_exchange",
    }.issubset(actions)
    assert result["scorecard"]["metrics"]["world_ecosystem_enabled"] is True


def test_core_compound_crisis_explicit_rule_override_is_preserved() -> None:
    result = run(RunConfig(scenario="compound_crisis", seed=31, ticks=1, rules=["movement"])).to_dict()
    actions = {event["payload"].get("action") for event in result["events"] if event["kind"] == "action_feedback"}

    assert result["config"]["rules"] == ["movement"]
    assert "logistics_transfer" not in actions
    assert result["scorecard"]["metrics"]["world_ecosystem_enabled"] is False


def test_rule_bundle_expands_to_registered_rule_packages() -> None:
    engine = RuleEngineSet.from_scenario(["world_ecosystem"])

    assert expand_rule_names(["world_ecosystem"]) == WORLD_ECOSYSTEM_RULES
    assert [package.name for package in engine.packages] == WORLD_ECOSYSTEM_RULES


def test_production_rule_consumes_inputs_and_creates_output() -> None:
    world = World("production")
    world.add_node(
        "factory",
        "organization",
        "Factory",
        (0, 0),
        {"resources": {"ore": 5}, "production": {"capacity": 4}},
    )
    world.node("factory").rule_pressures.append(
        {
            "rule": "production",
            "output_resource": "tools",
            "amount": 3,
            "input_costs": {"ore": 2},
            "project": "toolmaking",
            "ttl": 1,
        }
    )

    world.step(RuleEngineSet.from_scenario(["production"]))

    node = world.node("factory")
    assert node.attributes["resources"]["ore"] == 3
    assert node.attributes["resources"]["tools"] == 3
    assert node.attributes["production"]["last_output_resource"] == "tools"
    assert node.attributes["production"]["last_project"] == "toolmaking"
    assert any(event["payload"].get("action") == "production" for event in world.events.recent())


def test_production_rule_obeys_capacity_and_input_constraints() -> None:
    world = World("production-constraints")
    world.add_node("factory", "organization", "Factory", (0, 0), {"resources": {"ore": 1}, "production_capacity": 2})
    world.node("factory").rule_pressures.extend(
        [
            {"rule": "production", "output_resource": "tools", "amount": 3, "input_costs": {"ore": 1}, "ttl": 1},
            {"rule": "production", "output_resource": "tools", "amount": 1, "input_costs": {"ore": 2}, "ttl": 1},
        ]
    )

    engine = RuleEngineSet.from_scenario(["production"])

    assert engine.decide(world, world.node("factory")) is None
    world.step(engine)
    assert world.node("factory").attributes["resources"] == {"ore": 1}


def test_economic_exchange_rule_transfers_resource_and_budget() -> None:
    world = World("economy")
    world.add_node("buyer", "organization", "Buyer", (0, 0), {"budget": 10, "resources": {}})
    world.add_node("seller", "organization", "Seller", (1, 0), {"budget": 2, "resources": {"tools": 4}})
    world.node("buyer").rule_pressures.append(
        {
            "rule": "economic_exchange",
            "from": "node:seller",
            "resource": "tools",
            "amount": 2,
            "unit_price": 3,
            "ttl": 1,
        }
    )

    world.step(RuleEngineSet.from_scenario(["economic_exchange"]))

    assert world.node("buyer").attributes["resources"]["tools"] == 2
    assert world.node("seller").attributes["resources"]["tools"] == 2
    assert world.node("buyer").attributes["budget"] == 4
    assert world.node("seller").attributes["budget"] == 8
    assert any(event["payload"].get("action") == "economic_exchange" for event in world.events.recent())


def test_economic_exchange_rule_obeys_budget_and_inventory_constraints() -> None:
    world = World("economy-constraints")
    world.add_node("buyer", "organization", "Buyer", (0, 0), {"budget": 2, "resources": {}})
    world.add_node("seller", "organization", "Seller", (1, 0), {"budget": 0, "resources": {"tools": 1}})
    world.node("buyer").rule_pressures.extend(
        [
            {"rule": "economic_exchange", "from": "node:seller", "resource": "tools", "amount": 1, "unit_price": 3},
            {"rule": "economic_exchange", "from": "node:seller", "resource": "tools", "amount": 2, "unit_price": 1},
        ]
    )

    engine = RuleEngineSet.from_scenario(["economic_exchange"])

    assert engine.decide(world, world.node("buyer")) is None
    world.step(engine)
    assert world.node("buyer").attributes["budget"] == 2
    assert world.node("buyer").attributes["resources"] == {}
    assert world.node("seller").attributes["resources"]["tools"] == 1


def test_world_director_generates_pressure_from_causal_facts() -> None:
    world = World("director")
    world.add_node("depot", "organization", "Depot", (0, 0), {"resources": {"medical_supplies": 3}})
    world.add_node("patient", "population_cohort", "Patient", (1, 0), {"health": 3, "max_health": 10})
    world.add_node("guard", "unit", "Guard", (0, 1), {"health": 5})
    world.add_node("threat", "unit", "Threat", (1, 1), {"health": 4})
    world.add_node("speaker", "person", "Speaker", (0, 2))
    world.add_node("audience", "population_cohort", "Audience", (1, 2), {"signal:trust": 1})
    world.add_node("scientist", "key_character", "Scientist", (0, 3), {"identity": "field_scientist"})
    world.add_node(
        "infected",
        "population_cohort",
        "Infected",
        (1, 3),
        {"infection": {"pathogen": "demo", "status": "infectious"}},
    )
    world.add_node("coordinator", "organization", "Coordinator", (0, 4))
    world.add_node("volunteer", "organization", "Volunteer", (1, 4))
    world.add_node(
        "factory",
        "organization",
        "Factory",
        (0, 5),
        {
            "resources": {"ore": 4},
            "production": {
                "output_resource": "tools",
                "amount": 2,
                "capacity": 3,
                "input_costs": {"ore": 1},
            },
        },
    )
    world.add_node(
        "buyer",
        "organization",
        "Buyer",
        (0, 6),
        {"budget": 10, "market_need": {"resource": "tools", "amount": 1, "max_unit_price": 4}},
    )
    world.add_node(
        "seller",
        "organization",
        "Seller",
        (1, 6),
        {"resources": {"tools": 3}, "market_offer": {"resource": "tools", "amount": 2, "unit_price": 3}},
    )
    world.add_relationship("depot", "patient", "supply_route", 0.9, {"status": "open"})
    world.add_relationship("guard", "threat", "hostility", 0.7)
    world.add_relationship("speaker", "audience", "trust", 0.8)
    world.add_relationship("coordinator", "volunteer", "coordination", 0.7)

    output = DeterministicWorldDirectorProvider().observe(
        ProviderContext(world=world, tick=0, snapshot=world.snapshot())
    )
    effects = [item.to_dict() for item in output.effects]
    rules = {effect["rule"] for effect in effects if effect["type"] == "rule_pressure_add"}

    assert output.source == WORLD_DIRECTOR_SOURCE
    assert {
        "logistics",
        "combat",
        "social_spread",
        "science_publish",
        "collaboration",
        "production",
        "economic_exchange",
    }.issubset(rules)
    assert output.metadata["world_director"]["effect_count"] == len(effects)


def test_world_director_does_not_invent_economy_without_valid_cues() -> None:
    world = World("director-no-economy")
    world.add_node("idle", "organization", "Idle", (0, 0), {"resources": {"ore": 4}})
    world.add_node(
        "bad-factory",
        "organization",
        "Bad Factory",
        (1, 0),
        {
            "resources": {"ore": 0},
            "production": {"output_resource": "tools", "amount": 2, "input_costs": {"ore": 1}},
        },
    )
    world.add_node(
        "buyer",
        "organization",
        "Buyer",
        (0, 1),
        {"budget": 1, "market_need": {"resource": "tools", "amount": 1, "max_unit_price": 4}},
    )
    world.add_node(
        "seller",
        "organization",
        "Seller",
        (1, 1),
        {"resources": {"tools": 3}, "market_offer": {"resource": "tools", "amount": 2, "unit_price": 3}},
    )

    output = DeterministicWorldDirectorProvider().observe(
        ProviderContext(world=world, tick=0, snapshot=world.snapshot())
    )
    rules = {item.to_dict()["rule"] for item in output.effects if item.to_dict()["type"] == "rule_pressure_add"}

    assert "production" not in rules
    assert "economic_exchange" not in rules


def test_world_director_dispatch_defaults_and_disable_flag() -> None:
    enabled = run(RunConfig(scenario="compound_crisis", seed=31, ticks=1)).to_dict()
    disabled = run(
        RunConfig(
            scenario="compound_crisis",
            seed=31,
            ticks=1,
            world_director={"enabled": False},
        )
    ).to_dict()

    assert enabled["config"]["world_director"]["enabled"] is True
    assert disabled["config"]["world_director"]["enabled"] is False
    assert enabled["scorecard"]["metrics"]["world_director_outputs"] == 1
    assert disabled["scorecard"]["metrics"]["world_director_outputs"] == 0
    assert any(output["source"] == WORLD_DIRECTOR_SOURCE for output in enabled["provider_outputs"])
    assert all(output["source"] != WORLD_DIRECTOR_SOURCE for output in disabled["provider_outputs"])


def test_semantic_memory_retrieval_ranks_query_matches() -> None:
    world = World("memory")
    node = world.add_node("node-a", "person", "Node A", (0, 0))
    node.memories.extend(
        [
            {"text": "ordinary logistics note", "source": "test"},
            {"text": "urgent infection response plan", "source": "test"},
        ]
    )

    result = WorldMemoryRetriever().retrieve(world, MemoryQuery("node-a", text="infection response", limit=4))

    assert result.ranked_records
    assert result.ranked_records[0]["kind"] == "memory"
    assert "infection response" in result.ranked_records[0]["text"]
    assert result.to_dict()["ranked_records"][0]["score"] >= 2


def test_memory_ranking_uses_importance_and_credibility_tiebreaks() -> None:
    world = World("memory-quality")
    node = world.add_node("node-a", "person", "Node A", (0, 0))
    node.memories.extend(
        [
            {
                "text": "infection logistics response",
                "source": "rumor",
                "importance": 0.1,
                "credibility": 0.1,
            },
            {
                "text": "infection logistics response",
                "source": "field-report",
                "importance": 0.9,
                "credibility": 0.95,
            },
        ]
    )

    result = WorldMemoryRetriever().retrieve(world, MemoryQuery("node-a", text="infection logistics", limit=2))

    assert result.ranked_records[0]["payload"]["source"] == "field-report"
    assert result.ranked_records[0]["score"] > result.ranked_records[1]["score"]


def test_memory_consolidation_creates_long_term_summary_with_provenance() -> None:
    world = World("memory-consolidation")
    node = world.add_node("node-a", "person", "Node A", (0, 0))
    for index in range(10):
        node.memories.append(
            {
                "tick": index,
                "text": f"infection logistics response note {index}",
                "source": "field" if index % 2 == 0 else "agent",
                "importance": 0.1 + index / 10,
            }
        )

    result = WorldMemoryConsolidator().consolidate_node(world, "node-a", max_memories=6, recent_keep=3)
    retrieved = WorldMemoryRetriever().retrieve(world, MemoryQuery("node-a", text="infection logistics", limit=4))

    assert result.original_count == 10
    assert result.retained_count == 4
    assert node.memories[0]["kind"] == "memory_summary"
    assert node.memories[0]["memory_count"] == 7
    assert node.memories[0]["sources"] == ["agent", "field"]
    assert "infection" in node.memories[0]["keywords"]
    assert retrieved.ranked_records[0]["payload"]["kind"] == "memory_summary"


def test_memory_consolidation_records_credibility_contradictions_and_forgetting() -> None:
    world = World("memory-quality-consolidation")
    node = world.add_node("node-a", "person", "Node A", (0, 0))
    node.memories.extend(
        [
            {
                "tick": 1,
                "text": "official infection status contained",
                "source": "official",
                "importance": 0.8,
                "claim_key": "infection_status",
                "claim_value": "contained",
            },
            {
                "tick": 2,
                "text": "rumor infection status spreading",
                "source": "rumor",
                "importance": 0.7,
                "claim_key": "infection_status",
                "claim_value": "spreading",
            },
            {"tick": 3, "text": "low value duplicate note", "source": "rumor", "importance": 0.1},
            {"tick": 4, "text": "stale low value note", "source": "sensor", "importance": 0.2},
            {"tick": 5, "text": "recent operational note", "source": "field", "importance": 0.4},
            {"tick": 6, "text": "recent logistics note", "source": "field", "importance": 0.4},
        ]
    )

    result = WorldMemoryConsolidator().consolidate_node(
        world,
        "node-a",
        max_memories=4,
        recent_keep=2,
        source_credibility={"official": 0.95, "rumor": 0.2, "sensor": 0.7},
        retention_importance_floor=0.5,
    )
    summary = result.summary

    assert summary["memory_count"] == 2
    assert summary["forgotten_count"] == 2
    assert summary["source_credibility"] == {"official": 0.95, "rumor": 0.2}
    assert summary["average_credibility"] == 0.575
    assert summary["contradictions"] == [
        {
            "claim_key": "infection_status",
            "values": [
                {"value": "contained", "count": 1, "sources": ["official"]},
                {"value": "spreading", "count": 1, "sources": ["rumor"]},
            ],
        }
    ]
    assert [memory["text"] for memory in node.memories[1:]] == ["recent operational note", "recent logistics note"]


def test_run_harness_can_maintain_memory_during_ticks() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            capture_timeline=True,
            interventions=[
                {
                    "id": "seed-memories",
                    "tick": 0,
                    "effects": [
                        {
                            "type": "memory_add",
                            "target": "node:mira",
                            "text": f"infection response memory {index}",
                            "source": "field" if index % 2 == 0 else "rumor",
                            "importance": importance,
                        }
                        for index, importance in enumerate([0.1, 0.2, 0.9, 0.8, 0.7, 0.4, 0.6, 0.5])
                    ],
                }
            ],
            memory_consolidation={
                "enabled": True,
                "interval": 1,
                "max_memories": 5,
                "recent_keep": 2,
                "source_credibility": {"field": 0.9, "rumor": 0.2},
                "retention_importance_floor": 0.5,
            },
        )
    ).to_dict()

    report = result["memory_consolidation_report"]
    node = next(item for item in result["snapshot"]["nodes"] if item["id"] == "mira")
    metrics = result["scorecard"]["metrics"]

    assert len(report) == 1
    assert report[0]["node_id"] == "mira"
    assert report[0]["summary"]["kind"] == "memory_summary"
    assert report[0]["summary"]["memory_count"] == 3
    assert report[0]["summary"]["forgotten_count"] == 3
    assert node["memories"][0]["kind"] == "memory_summary"
    assert len(node["memories"]) == 3
    assert any(trace["kind"] == "memory_consolidation" for trace in result["traces"])
    assert any(event["payload"].get("kind") == "memory_consolidation" for event in result["snapshot"]["deltas"])
    assert "snapshot" not in result["timeline"][0]
    assert any(trace["kind"] == "memory_consolidation" for trace in result["timeline"][0]["traces"])
    assert metrics["memory_consolidated_nodes"] == 1
    assert metrics["memory_summary_count"] == 1
    assert metrics["memory_forgotten_count"] == 3


def test_provider_runtime_metadata_and_timeline_capture() -> None:
    result = run(RunConfig(scenario="seed", seed=7, ticks=2, capture_timeline=True)).to_dict()

    assert len(result["timeline"]) == 2
    assert [frame["sequence"] for frame in result["timeline"]] == [1, 2]
    assert result["timeline"][0]["tick"] == 1
    assert result["timeline"][0]["projection"]["summary"]["tick"] == 1
    assert "snapshot" not in result["timeline"][0]
    first_event_sequences = {event["sequence"] for event in result["timeline"][0]["events"]}
    second_event_sequences = {event["sequence"] for event in result["timeline"][1]["events"]}
    assert first_event_sequences.isdisjoint(second_event_sequences)
    assert result["provider_outputs"][0]["provider_runtime"]["attempts"] == 1
    assert result["provider_outputs"][0]["provider_runtime"]["estimated_cost"] == 0.0


def test_rule_pressures_decay_after_tick_and_do_not_repeat_forever() -> None:
    world = World("pressure-decay")
    world.add_node("attacker", "unit", "Attacker", (0, 0))
    world.add_node("victim", "unit", "Victim", (1, 0), {"health": 5})
    world.node("attacker").rule_pressures.append(
        {"rule": "combat", "to": "node:victim", "damage": 1, "ttl": 1}
    )
    engine = RuleEngineSet.from_scenario(["combat"])

    world.step(engine)
    world.step(engine)

    assert world.node("victim").attributes["health"] == 4
    assert world.node("attacker").rule_pressures == []
    assert any(trace["kind"] == "pressure_decay" for trace in world.traces.recent())


def test_domain_state_profile_and_validation_report() -> None:
    world = World("domain-state")
    world.add_node(
        "node-a",
        "person",
        "Node A",
        (0, 0),
        {
            "health": 8,
            "alive": True,
            "resources": {"food": 2},
            "infection": {"pathogen": "demo", "status": "exposed", "severity": 0.4},
            "policies": {"quarantine": {"status": "active"}},
            "publications": [{"title": "Note"}],
            "migration": {"destination": "safe_zone"},
            "collaborations": [{"project": "response"}],
            "signal:trust": 3,
            "agent_layer": "relationship_network_member",
        },
    )
    world.add_node(
        "bad",
        "organization",
        "Bad",
        (1, 0),
        {
            "health": -1,
            "resources": {"food": -2},
            "policies": "invalid",
            "signal:panic": "high",
        },
    )

    inspector = WorldDomainStateInspector()
    profile = inspector.inspect_node(world, "node-a").to_dict()
    report = inspector.validate_world(world, include_profiles=True).to_dict()

    assert profile["health"] == {"value": 8, "alive": True}
    assert profile["resources"] == {"food": 2}
    assert profile["infection"]["pathogen"] == "demo"
    assert profile["signals"] == {"trust": 3}
    assert profile["organization"]["agent_layer"] == "relationship_network_member"
    assert report["issue_count"] == 4
    assert {issue["field"] for issue in report["issues"]} == {
        "health",
        "resources.food",
        "signal:panic",
    } | {"policies"}


def test_richer_domain_state_profile_summary_and_scorecard_metrics() -> None:
    world = World("rich-domain", {"scenario": "rich-domain"})
    world.add_node(
        "node-a",
        "organization",
        "Node A",
        (0, 0),
        {
            "economy": {"budget": 12, "currency": "credits"},
            "belief:trust": 2,
            "military": {"force_strength": 5, "readiness": 0.8},
            "production": {"capacity": 3, "output": 2, "research_progress": 0.4},
            "terrain": {"terrain_type": "urban", "hazard": "smoke"},
            "supply_chain": {"bottlenecks": ["bridge"]},
            "organization_structure": {"authority": "council", "teams": ["field"]},
        },
    )

    inspector = WorldDomainStateInspector()
    profile = inspector.inspect_node(world, "node-a").to_dict()
    summary = inspector.summarize_world(world).to_dict()
    metrics = evaluate_run(
        {
            "snapshot": world.snapshot(),
            "events": [],
            "timeline": [],
            "provider_outputs": [],
            "provider_audits": [],
            "intervention_audits": [],
            "pressure_action_report": {"totals": {}},
            "provider_outcome_report": {"totals": {}},
            "provider_execution_report": {"totals": {}},
            "config": {"ticks": 0, "rules": WORLD_ECOSYSTEM_RULES},
            "scorecard": {"score": 100.0},
        }
    ).to_dict()["metrics"]

    assert profile["economy"] == {"budget": 12, "currency": "credits"}
    assert profile["beliefs"] == {"trust": 2}
    assert profile["military"] == {"force_strength": 5, "readiness": 0.8}
    assert profile["production"]["research_progress"] == 0.4
    assert summary["domain_model_coverage"]["by_domain"]["economy"] == 1
    assert summary["beliefs"]["totals"] == {"trust": 2}
    assert metrics["enabled_rule_count"] == len(WORLD_ECOSYSTEM_RULES)
    assert metrics["world_ecosystem_rule_coverage"] == 1.0
    assert metrics["domain_model_coverage"]["economy"] == 1


def test_world_domain_state_summary_feeds_scorecard_and_projection() -> None:
    world = World("domain-summary", {"scenario": "domain-summary"})
    world.add_node(
        "north",
        "population_cohort",
        "North Cohort",
        (0, 0),
        {
            "health": 1,
            "alive": True,
            "resources": {"food": 0, "medicine": 2},
            "infection": {"pathogen": "demo", "status": "infectious", "severity": 0.8},
            "policies": {"quarantine": {"status": "active"}},
            "migration": {"status": "migrating", "destination": "clinic", "blocked_by_policy": True},
            "publications": [{"title": "Field Note"}],
            "collaborations": [{"project": "response"}],
            "signal:panic": 2,
        },
    )
    world.add_node(
        "south",
        "population_cohort",
        "South Cohort",
        (1, 0),
        {
            "health": 5,
            "alive": False,
            "resources": {"water": 3},
            "infection": {"pathogen": "demo", "status": "exposed"},
            "policies": {"isolation": {"status": "active", "blocks_contact": True}},
            "migration": {"status": "arrived"},
            "signal:trust": 4,
        },
    )

    snapshot = world.snapshot()
    summary = WorldDomainStateInspector().summarize_snapshot(snapshot).to_dict()
    result = {
        "snapshot": snapshot,
        "events": [],
        "timeline": [],
        "provider_outputs": [],
        "provider_audits": [],
        "intervention_audits": [],
        "pressure_action_report": {"totals": {}},
        "provider_outcome_report": {"totals": {}},
        "config": {"ticks": 0},
        "scorecard": {"score": 100.0},
    }

    assert summary["health"] == {
        "tracked_count": 2,
        "average": 3.0,
        "critical_count": 1,
        "dead_count": 1,
    }
    assert summary["infection"]["active_count"] == 2
    assert summary["infection"]["by_status"] == {"exposed": 1, "infectious": 1}
    assert summary["infection"]["pathogens"] == {"demo": 2}
    assert summary["resources"] == {
        "totals": {"food": 0, "medicine": 2, "water": 3},
        "scarcity_nodes": 1,
    }
    assert summary["policies"]["active_count"] == 2
    assert summary["migration"] == {"by_status": {"arrived": 1, "migrating": 1}, "blocked_count": 1}
    assert summary["publications"] == {"count": 1}
    assert summary["collaborations"] == {"count": 1}
    assert summary["signals"] == {"totals": {"panic": 2, "trust": 4}}
    assert summary["risk"] == {"score": 15, "level": "critical"}

    metrics = evaluate_run(result).to_dict()["metrics"]
    projection = project_run_for_viewer(result).to_dict()

    assert metrics["domain_state_issues"] == 0
    assert metrics["domain_risk_score"] == 15
    assert metrics["domain_risk_level"] == "critical"
    assert metrics["domain_active_infections"] == 2
    assert metrics["domain_scarcity_nodes"] == 1
    assert projection["summary"]["domain_risk"] == {"score": 15, "level": "critical"}
    assert projection["summary"]["domain_summary"]["resources"]["scarcity_nodes"] == 1


def test_scorecard_includes_runtime_governance_timeline_and_domain_metrics() -> None:
    from ai_native_world_engine.core import DeterministicPressureProvider

    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=2,
            capture_timeline=True,
            provider=DeterministicPressureProvider(rule="attack"),
            govern_provider_output=True,
            provider_id="bad-rule",
            allowed_rule_names=["move"],
        )
    ).to_dict()

    metrics = result["scorecard"]["metrics"]

    assert metrics["timeline_frames"] == 2
    assert metrics["provider_governance_rejections"] == 2
    assert metrics["provider_attempts"] == 0
    assert metrics["provider_estimated_cost"] == 0.0
    assert metrics["domain_state_issues"] == 0
    assert any(item["kind"] == "provider_governance_rejection" for item in result["scorecard"]["penalties"])


def test_domain_lifecycle_progresses_infection_policy_and_migration_across_ticks() -> None:
    world = World("domain-lifecycle")
    world.add_node(
        "patient",
        "person",
        "Patient",
        (0, 0),
        {
            "health": 10,
            "infection": {
                "pathogen": "demo",
                "status": "exposed",
                "severity": 1.0,
                "age": 0,
                "incubation_ticks": 1,
                "infectious_ticks": 2,
                "damage_per_tick": 1,
            },
        },
    )
    world.add_node(
        "authority",
        "organization",
        "Authority",
        (0, 1),
        {"policies": {"quarantine": {"status": "active", "remaining_ticks": 2}}},
    )
    world.add_node(
        "migrant",
        "population_cohort",
        "Migrant",
        (0, 2),
        {
            "migration": {
                "destination": "safe_zone",
                "status": "migrating",
                "destination_position": {"x": 3, "y": 2},
                "speed": 1,
                "progress": 0,
            }
        },
    )
    engine = RuleEngineSet.from_scenario(["movement"])

    world.step(engine)
    assert world.node("patient").attributes["infection"]["status"] == "infectious"
    assert world.node("patient").attributes["health"] == 9
    assert world.node("authority").attributes["policies"]["quarantine"]["remaining_ticks"] == 1
    assert world.node("authority").attributes["policies"]["quarantine"]["status"] == "active"
    assert world.node("migrant").position.to_dict() == {"x": 1.0, "y": 2.0}
    assert world.node("migrant").attributes["migration"]["status"] == "migrating"

    world.step(engine)
    assert world.node("patient").attributes["infection"]["status"] == "infectious"
    assert world.node("patient").attributes["health"] == 8
    assert world.node("authority").attributes["policies"]["quarantine"]["remaining_ticks"] == 0
    assert world.node("authority").attributes["policies"]["quarantine"]["status"] == "expired"
    assert world.node("migrant").position.to_dict() == {"x": 2.0, "y": 2.0}

    world.step(engine)
    assert world.node("patient").attributes["infection"]["status"] == "recovered"
    assert world.node("patient").attributes["health"] == 8
    assert world.node("migrant").position.to_dict() == {"x": 3.0, "y": 2.0}
    assert world.node("migrant").attributes["migration"]["status"] == "arrived"
    assert any(event["payload"].get("action") == "infection_progress" for event in world.events.recent())
    assert any(event["payload"].get("action") == "migration_progress" for event in world.events.recent())
    assert any(trace["kind"] == "domain_lifecycle" for trace in world.traces.recent())


def test_cross_rule_constraints_link_infection_quarantine_migration_and_logistics() -> None:
    world = World("cross-rule")
    world.add_node(
        "carrier",
        "person",
        "Carrier",
        (0, 0),
        {
            "infection": {
                "pathogen": "demo",
                "status": "infectious",
                "severity": 1.0,
                "age": 1,
                "incubation_ticks": 0,
                "infectious_ticks": 5,
                "damage_per_tick": 0,
            }
        },
    )
    world.add_node("contact", "person", "Contact", (1, 0))
    world.add_node("isolated", "person", "Isolated", (2, 0), {"policies": {"quarantine": {"status": "active"}}})
    world.add_relationship("carrier", "contact", "contact", 1.0)
    world.add_relationship("carrier", "isolated", "contact", 1.0)

    world.add_node(
        "migrant",
        "population_cohort",
        "Migrant",
        (0, 2),
        {
            "policies": {"quarantine": {"status": "active", "remaining_ticks": 1}},
            "migration": {
                "destination": "safe_zone",
                "status": "migrating",
                "destination_position": {"x": 2, "y": 2},
                "speed": 1,
                "progress": 0,
            },
        },
    )
    world.add_node("depot", "organization", "Depot", (0, 3), {"resources": {"medical_supplies": 2}})
    world.add_node("patient", "person", "Patient", (1, 3), {"health": 5, "max_health": 10, "resources": {}})
    world.node("depot").rule_pressures.append(
        {
            "rule": "logistics",
            "to": "node:patient",
            "resource": "medical_supplies",
            "amount": 2,
            "heal_amount": 3,
            "ttl": 1,
        }
    )
    engine = RuleEngineSet.from_scenario(["infection", "logistics"])

    world.step(engine)

    assert world.node("contact").attributes["infection"]["status"] == "exposed"
    assert "infection" not in world.node("isolated").attributes
    assert world.node("migrant").position.to_dict() == {"x": 0.0, "y": 2.0}
    assert world.node("migrant").attributes["migration"]["blocked_ticks"] == 1
    assert world.node("migrant").attributes["policies"]["quarantine"]["status"] == "expired"
    assert world.node("patient").attributes["health"] == 8
    assert world.node("patient").attributes["resources"]["medical_supplies"] == 2
    assert world.node("depot").attributes["resources"]["medical_supplies"] == 0


def test_combat_viability_uses_range_resources_health_and_morale() -> None:
    world = World("combat-viability")
    world.add_node(
        "attacker",
        "unit",
        "Attacker",
        (0, 0),
        {"health": 5, "max_health": 10, "morale": 0.5, "resources": {"ammo": 2}},
    )
    world.add_node("victim", "unit", "Victim", (5, 0), {"health": 10})
    engine = RuleEngineSet.from_scenario(["combat"])

    world.node("attacker").rule_pressures.append(
        {"rule": "combat", "to": "node:victim", "damage": 8, "max_range": 2, "resource": "ammo", "resource_cost": 1}
    )
    world.step(engine)

    assert world.node("victim").attributes["health"] == 10
    assert world.node("attacker").attributes["resources"]["ammo"] == 2

    world.node("victim").position = Position.from_value((1, 0))
    world.node("attacker").rule_pressures.append(
        {"rule": "combat", "to": "node:victim", "damage": 8, "max_range": 2, "resource": "ammo", "resource_cost": 1}
    )
    world.step(engine)

    assert world.node("victim").attributes["health"] == 8
    assert world.node("attacker").attributes["resources"]["ammo"] == 1
    decision = next(trace for trace in reversed(world.traces.recent()) if trace["kind"] == "rule_decision")
    metadata = decision["selected"]["metadata"]
    assert metadata["health_factor"] == 0.5
    assert metadata["morale_factor"] == 0.5


def test_logistics_viability_uses_route_and_capacity() -> None:
    world = World("logistics-viability")
    world.add_node("depot", "organization", "Depot", (0, 0), {"resources": {"supplies": 10}, "logistics_capacity": 3})
    world.add_node("clinic", "organization", "Clinic", (1, 0), {"resources": {}})
    engine = RuleEngineSet.from_scenario(["logistics"])

    world.node("depot").rule_pressures.append(
        {"rule": "logistics", "to": "node:clinic", "resource": "supplies", "amount": 4, "require_route": True}
    )
    world.step(engine)
    assert world.node("clinic").attributes["resources"] == {}

    world.node("depot").rule_pressures.append(
        {"rule": "logistics", "to": "node:clinic", "resource": "supplies", "amount": 3, "require_route": True}
    )
    world.step(engine)
    assert world.node("clinic").attributes["resources"] == {}

    world.add_relationship("depot", "clinic", "logistics_route", 0.8, {"status": "open"})
    world.node("depot").rule_pressures.append(
        {"rule": "logistics", "to": "node:clinic", "resource": "supplies", "amount": 3, "require_route": True}
    )
    world.step(engine)

    assert world.node("clinic").attributes["resources"]["supplies"] == 3
    assert world.node("depot").attributes["resources"]["supplies"] == 7
    decision = next(trace for trace in reversed(world.traces.recent()) if trace["kind"] == "rule_decision")
    assert decision["selected"]["metadata"]["capacity"] == 3
    assert decision["selected"]["metadata"]["route"]["type"] == "logistics_route"


def test_policy_dampens_contact_and_movement_without_hard_quarantine() -> None:
    world = World("policy-dampening")
    world.add_node(
        "carrier",
        "person",
        "Carrier",
        (0, 0),
        {
            "policies": {"masking": {"status": "active", "contact_reduction": 0.5}},
            "infection": {
                "pathogen": "demo",
                "status": "infectious",
                "severity": 1,
                "age": 1,
                "incubation_ticks": 0,
                "infectious_ticks": 5,
                "spread_limit": 2,
            },
        },
    )
    world.add_node("contact-a", "person", "Contact A", (1, 0))
    world.add_node("contact-b", "person", "Contact B", (2, 0))
    world.add_relationship("carrier", "contact-a", "contact", 1)
    world.add_relationship("carrier", "contact-b", "contact", 1)
    world.add_node(
        "migrant",
        "population_cohort",
        "Migrant",
        (0, 2),
        {
            "policies": {"travel_advisory": {"status": "active", "movement_multiplier": 0.5}},
            "migration": {
                "destination": "safe_zone",
                "status": "migrating",
                "destination_position": {"x": 2, "y": 2},
                "speed": 1,
                "base_speed": 1,
            },
        },
    )

    world.step(RuleEngineSet.from_scenario(["infection"]))

    exposed = [
        node_id
        for node_id in ("contact-a", "contact-b")
        if world.node(node_id).attributes.get("infection", {}).get("status") == "exposed"
    ]
    assert exposed == ["contact-a"]
    assert world.node("migrant").position.to_dict() == {"x": 0.5, "y": 2.0}
    assert world.node("migrant").attributes["migration"]["effective_speed"] == 0.5


def test_social_spread_prefers_stronger_relationship_path() -> None:
    world = World("social-relationship")
    world.add_node("influencer", "person", "Influencer", (0, 0))
    world.add_node("weak", "person", "Weak Tie", (1, 0))
    world.add_node("strong", "person", "Strong Tie", (2, 0))
    world.add_relationship("influencer", "weak", "trust", 0.1)
    world.add_relationship("influencer", "strong", "trust", 0.9)
    world.node("influencer").rule_pressures.extend(
        [
            {"rule": "social_spread", "to": "node:weak", "signal": "trust", "ttl": 1},
            {"rule": "social_spread", "to": "node:strong", "signal": "trust", "ttl": 1},
        ]
    )

    world.step(RuleEngineSet.from_scenario(["social_spread"]))

    assert "signal:trust" not in world.node("weak").attributes
    assert world.node("strong").attributes["signal:trust"] == 1
    decision = next(trace for trace in reversed(world.traces.recent()) if trace["kind"] == "rule_decision")
    assert decision["selected"]["metadata"]["target_id"] == "strong"
    assert decision["selected"]["metadata"]["relationship_weight"] == 0.9
