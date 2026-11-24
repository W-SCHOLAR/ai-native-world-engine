"""Deterministic compound crisis scenario."""

from __future__ import annotations

from random import Random

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    FeedbackIngestor,
    ThoughtBubble,
    World,
    effect,
    target,
)


def create_compound_crisis_world(seed: int = 7) -> World:
    rng = Random(seed)
    world = World(
        "compound-crisis-world",
        {
            "seed": seed,
            "scenario": "compound_crisis",
            "governance": {
                "mode": "scenario_simulation",
                "ordinary_people": "anonymous aggregate cohorts",
                "private_individuals": "not directly simulated",
            },
            "domains": [
                "infection",
                "logistics",
                "social",
                "combat",
                "migration",
                "science",
                "production",
                "economy",
            ],
        },
    )

    world.add_node(
        "authority",
        "organization",
        "Crisis Coordination Authority",
        (0, 0),
        {"synthetic": True, "organization_kind": "coordination", "agent_layer": "relationship_network"},
    )
    world.add_node(
        "operations-board",
        "organization",
        "Joint Operations Board",
        (0, -0.5),
        {"synthetic": True, "organization_kind": "operations", "agent_layer": "relationship_network"},
    )
    world.add_node(
        "depot",
        "organization",
        "Medical Logistics Depot",
        (-1, -1),
        {
            "synthetic": True,
            "resources": {"medical_supplies": 6 + rng.randint(0, 2), "food": 3},
            "logistics_capacity": 4,
        },
    )
    world.add_node(
        "clinic",
        "organization",
        "Field Clinic",
        (1, -1),
        {"synthetic": True, "resources": {}, "health": 9, "max_health": 10},
    )
    world.add_node(
        "patient",
        "population_cohort",
        "Patient Cohort",
        (1, -2),
        {"privacy": "anonymous_aggregate", "health": 4, "max_health": 10, "resources": {}},
    )
    world.add_node(
        "carrier",
        "population_cohort",
        "Infectious Cohort",
        (-1, 1),
        {
            "privacy": "anonymous_aggregate",
            "health": 8,
            "max_health": 10,
            "infection": {
                "pathogen": "scenario-fever",
                "status": "infectious",
                "severity": 0.7,
                "age": 1,
                "incubation_ticks": 0,
                "infectious_ticks": 5,
                "damage_per_tick": 0.5,
                "spread_limit": 3,
            },
        },
    )
    world.add_node(
        "susceptible",
        "population_cohort",
        "Susceptible District Cohort",
        (0, 1),
        {"privacy": "anonymous_aggregate", "health": 7, "max_health": 10},
    )
    world.add_node(
        "contact-vector",
        "population_cohort",
        "Contact Vector Cohort",
        (-0.5, 1.5),
        {"privacy": "anonymous_aggregate", "health": 8, "max_health": 10},
    )
    world.add_node(
        "isolated",
        "population_cohort",
        "Isolated District Cohort",
        (1, 1),
        {
            "privacy": "anonymous_aggregate",
            "health": 7,
            "max_health": 10,
            "policies": {"quarantine": {"status": "active", "remaining_ticks": 2}},
        },
    )
    world.add_node(
        "evacuee",
        "population_cohort",
        "Evacuation Cohort",
        (-2, 1),
        {"privacy": "anonymous_aggregate", "health": 6, "max_health": 10},
    )
    world.add_node(
        "response-unit",
        "organization_member",
        "Response Unit",
        (-1, 0),
        {"synthetic": True, "health": 10, "max_health": 10, "morale": 0.9, "resources": {"ammo": 2}},
    )
    world.add_node(
        "raider",
        "organization_member",
        "Scenario Raider Cell",
        (-0.5, 0),
        {"synthetic": True, "health": 5, "max_health": 5, "morale": 0.6},
    )
    world.add_node(
        "influencer",
        "person",
        "Synthetic Civic Influencer",
        (0, 2),
        {"synthetic": True, "governance_class": "synthetic_persona"},
    )
    world.add_node(
        "audience",
        "population_cohort",
        "Civic Audience Cohort",
        (1, 2),
        {"privacy": "anonymous_aggregate", "signal:trust": 0},
    )
    world.add_node(
        "scientist",
        "key_character",
        "Synthetic Field Scientist",
        (2, 0),
        {"synthetic": True, "agent_layer": "key_character", "identity": "field_scientist"},
    )
    world.add_node(
        "coordinator",
        "person",
        "Synthetic Response Coordinator",
        (2, 1),
        {"synthetic": True, "governance_class": "synthetic_persona"},
    )
    world.add_node(
        "volunteer",
        "person",
        "Synthetic Volunteer Lead",
        (2, 2),
        {"synthetic": True, "governance_class": "synthetic_persona"},
    )
    world.add_node(
        "workshop",
        "organization",
        "Emergency Repair Workshop",
        (-2, -1),
        {
            "synthetic": True,
            "resources": {"raw_material": 5},
            "production": {
                "capacity": 3,
                "output_resource": "repair_kits",
                "amount": 2,
                "input_costs": {"raw_material": 2},
                "project": "field equipment repair kits",
            },
        },
    )
    world.add_node(
        "market-seller",
        "organization",
        "Mutual Aid Market Seller",
        (-2, -2),
        {
            "synthetic": True,
            "budget": 1,
            "resources": {"repair_kits": 4},
            "market_offer": {"resource": "repair_kits", "amount": 3, "unit_price": 2},
        },
    )
    world.add_node(
        "market-buyer",
        "organization",
        "Clinic Procurement Desk",
        (-1, -2),
        {
            "synthetic": True,
            "budget": 10,
            "resources": {},
            "market_need": {"resource": "repair_kits", "amount": 2, "max_unit_price": 3},
        },
    )

    world.add_relationship("carrier", "susceptible", "contact", 1.0, {"source": "compound_crisis"})
    world.add_relationship("carrier", "isolated", "contact", 1.0, {"source": "compound_crisis"})
    world.add_relationship("contact-vector", "susceptible", "contact", 0.9, {"source": "compound_crisis"})
    world.add_relationship("depot", "patient", "supply_route", 0.9, {"status": "open"})
    world.add_relationship("influencer", "audience", "trust", 0.8, {"source": "compound_crisis"})
    world.add_relationship("coordinator", "volunteer", "collaboration", 0.6, {"source": "compound_crisis"})
    world.add_relationship("authority", "depot", "coordination", 0.7, {"source": "compound_crisis"})
    world.add_relationship("authority", "clinic", "coordination", 0.7, {"source": "compound_crisis"})
    world.add_relationship("workshop", "clinic", "support_route", 0.8, {"source": "compound_crisis"})
    world.add_relationship("market-seller", "market-buyer", "market_route", 0.8, {"source": "compound_crisis"})

    world.node("authority").rule_pressures.append(
        {
            "rule": "quarantine",
            "policy": "district_lockdown",
            "level": "active",
            "duration_ticks": 2,
            "reason": "contain scenario fever spread",
            "ttl": 1,
        }
    )
    world.node("operations-board").rule_pressures.append(
        {
            "rule": "organization_decision",
            "decision": "prioritize clinic repair, patient logistics, and transparent public updates",
            "reason": "coordinate cross-domain response",
            "ttl": 1,
        }
    )
    world.node("contact-vector").rule_pressures.append(
        {
            "rule": "infection",
            "to": "node:susceptible",
            "pathogen": "scenario-fever",
            "severity": 0.6,
            "reason": "simulate contact-driven exposure",
            "ttl": 1,
        }
    )
    world.node("depot").rule_pressures.append(
        {
            "rule": "logistics",
            "to": "node:patient",
            "resource": "medical_supplies",
            "amount": 3,
            "heal_amount": 4,
            "require_route": True,
            "reason": "stabilize patient cohort",
            "ttl": 1,
        }
    )
    world.node("response-unit").rule_pressures.append(
        {
            "rule": "combat",
            "to": "node:raider",
            "damage": 4,
            "max_range": 2,
            "resource": "ammo",
            "resource_cost": 1,
            "reason": "protect field clinic route",
            "ttl": 1,
        }
    )
    world.node("influencer").rule_pressures.append(
        {
            "rule": "social_spread",
            "to": "node:audience",
            "signal": "trust",
            "require_relationship": True,
            "reason": "publish calm public guidance",
            "ttl": 1,
        }
    )
    world.node("scientist").rule_pressures.append(
        {
            "rule": "science_publish",
            "title": "Scenario Fever Field Note",
            "topic": "compound crisis response",
            "reason": "make findings auditable",
            "ttl": 1,
        }
    )
    world.node("evacuee").rule_pressures.append(
        {
            "rule": "migration",
            "destination": "field_clinic_zone",
            "position": {"x": 0, "y": -2},
            "speed": 1,
            "reason": "move vulnerable cohort toward care",
            "ttl": 1,
        }
    )
    world.node("coordinator").rule_pressures.append(
        {
            "rule": "collaboration",
            "with": "node:volunteer",
            "project": "door-to-door supply and isolation support",
            "reason": "coordinate response capacity",
            "ttl": 1,
        }
    )
    world.node("workshop").rule_pressures.append(
        {
            "rule": "production",
            "output_resource": "repair_kits",
            "amount": 2,
            "input_costs": {"raw_material": 2},
            "capacity": 3,
            "project": "field equipment repair kits",
            "reason": "replace damaged response gear",
            "ttl": 1,
        }
    )
    world.node("market-buyer").rule_pressures.append(
        {
            "rule": "economic_exchange",
            "from": "node:market-seller",
            "resource": "repair_kits",
            "amount": 2,
            "unit_price": 2,
            "reason": "buy repair kits for field clinic operations",
            "ttl": 1,
        }
    )

    _seed_display_payloads(world)
    return world


def _seed_display_payloads(world: World) -> None:
    ingestor = FeedbackIngestor()
    ingestor.ingest(
        world,
        ActionFeedback(
            source="compound_crisis_scenario",
            actor_type="system",
            actor_id="compound_crisis_seed",
            action="seed_crisis_context",
            summary="Seed initial crisis display context",
            targets=[target("node", "authority")],
            effects=[
                effect(
                    "thought_bubble_add",
                    target="node:authority",
                    text="The first useful world is one whose causal chain can be audited.",
                    source="compound_crisis_scenario",
                    salience=0.72,
                ),
                effect(
                    "action_bullet_add",
                    target="node:depot",
                    text="medical convoy ready",
                    source="compound_crisis_scenario",
                    salience=0.62,
                ),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        )
    )
    world.emit_thought_bubble(
        ThoughtBubble(
            "scientist",
            "A compact scenario can still expose a full causal loop.",
            "compound_crisis_scenario",
            salience=0.65,
        )
    )
