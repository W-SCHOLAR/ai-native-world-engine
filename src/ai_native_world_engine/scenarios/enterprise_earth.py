"""Enterprise-scale Earth scenario foundation."""

from __future__ import annotations

from math import cos, pi, sin
from random import Random

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    FeedbackIngestor,
    World,
    effect,
    target,
)


COUNTRIES = [
    ("country-us", "United States", "north_america"),
    ("country-cn", "China", "asia"),
    ("country-de", "Germany", "europe"),
    ("country-in", "India", "asia"),
    ("country-br", "Brazil", "south_america"),
    ("country-za", "South Africa", "africa"),
    ("country-jp", "Japan", "asia"),
    ("country-fr", "France", "europe"),
]

ORGANIZATIONS = [
    {
        "id": "org-global-health-network",
        "name": "Global Health Network",
        "kind": "public_health",
        "scope": "transnational",
        "anchor": "country-de",
        "members": [
            ("epidemiology-cell", "epidemiology"),
            ("hospital-capacity-cell", "hospital_capacity"),
            ("policy-liaison-cell", "policy_liaison"),
        ],
    },
    {
        "id": "org-science-council",
        "name": "Global Science Council",
        "kind": "science",
        "scope": "transnational",
        "anchor": "country-us",
        "members": [
            ("theory-group", "theory"),
            ("laboratory-network", "laboratory"),
            ("publication-board", "publication"),
        ],
    },
    {
        "id": "org-civic-alliance",
        "name": "Civic Alliance",
        "kind": "political_party_network",
        "scope": "multi_city",
        "anchor": "country-fr",
        "members": [
            ("platform-committee", "platform"),
            ("local-organizers", "organizing"),
            ("public-communications", "communications"),
        ],
    },
    {
        "id": "org-logistics-grid",
        "name": "Transnational Logistics Grid",
        "kind": "logistics",
        "scope": "transnational",
        "anchor": "country-cn",
        "members": [
            ("routing-hub", "routing"),
            ("port-ops", "port_operations"),
            ("fleet-coordination", "fleet_coordination"),
        ],
    },
    {
        "id": "org-media-signal-network",
        "name": "Media Signal Network",
        "kind": "media",
        "scope": "global_information",
        "anchor": "country-jp",
        "members": [
            ("editorial-desk", "editorial"),
            ("fact-check-cell", "fact_check"),
            ("distribution-team", "distribution"),
        ],
    },
    {
        "id": "org-climate-resilience-forum",
        "name": "Climate Resilience Forum",
        "kind": "climate",
        "scope": "transnational",
        "anchor": "country-br",
        "members": [
            ("risk-modeling", "risk_modeling"),
            ("adaptation-policy", "adaptation_policy"),
            ("field-observation", "field_observation"),
        ],
    },
    {
        "id": "org-energy-transition-board",
        "name": "Energy Transition Board",
        "kind": "energy_transition",
        "scope": "transnational",
        "anchor": "country-za",
        "members": [
            ("grid-modernization-cell", "grid_modernization"),
            ("storage-planning-cell", "storage_planning"),
            ("market-transition-cell", "market_transition"),
        ],
    },
    {
        "id": "org-education-access-network",
        "name": "Education Access Network",
        "kind": "education",
        "scope": "multi_region",
        "anchor": "country-in",
        "members": [
            ("curriculum-team", "curriculum"),
            ("teacher-training-cell", "teacher_training"),
            ("digital-access-team", "digital_access"),
        ],
    },
    {
        "id": "org-cyber-resilience-center",
        "name": "Cyber Resilience Center",
        "kind": "cyber_resilience",
        "scope": "global_infrastructure",
        "anchor": "country-us",
        "members": [
            ("incident-response-cell", "incident_response"),
            ("threat-analysis-cell", "threat_analysis"),
            ("standards-liaison-cell", "standards_liaison"),
        ],
    },
    {
        "id": "org-humanitarian-response-hub",
        "name": "Humanitarian Response Hub",
        "kind": "humanitarian_response",
        "scope": "transnational",
        "anchor": "country-br",
        "members": [
            ("needs-assessment-cell", "needs_assessment"),
            ("supply-distribution-cell", "supply_distribution"),
            ("field-coordination-cell", "field_coordination"),
        ],
    },
]

KEY_CHARACTERS = [
    {
        "id": "key-albert-einstein",
        "name": "Albert Einstein",
        "identity": "scientist",
        "anchor": "country-de",
        "thought": "If the rules are consistent, the world line can be explained.",
        "action": "publishes a theoretical note",
    },
    {
        "id": "key-marie-curie",
        "name": "Marie Curie",
        "identity": "scientist",
        "anchor": "country-fr",
        "thought": "Evidence must remain stronger than reputation.",
        "action": "coordinates laboratory work",
    },
    {
        "id": "key-ada-lovelace",
        "name": "Ada Lovelace",
        "identity": "computing_pioneer",
        "anchor": "country-us",
        "thought": "A symbolic machine changes what a society can coordinate.",
        "action": "maps an analytical procedure",
    },
    {
        "id": "key-wangari-maathai",
        "name": "Wangari Maathai",
        "identity": "environmental_organizer",
        "anchor": "country-za",
        "thought": "Restoring land also restores civic agency.",
        "action": "organizes a resilience coalition",
    },
    {
        "id": "key-satyendra-nath-bose",
        "name": "Satyendra Nath Bose",
        "identity": "physicist",
        "anchor": "country-in",
        "thought": "A distribution can reveal order inside a crowd.",
        "action": "shares a statistical model",
    },
]

COHORT_IDENTITIES = [
    ("doctors", "doctor", "healthcare"),
    ("scientists", "scientist", "research"),
    ("engineers", "engineer", "infrastructure"),
]

NETWORK_ROLE_POOL = [
    "policy",
    "research",
    "operations",
    "logistics",
    "field",
    "analysis",
    "communications",
    "finance",
    "security",
    "ethics",
    "planning",
    "data",
    "coordination",
    "training",
]

PERSONA_GIVEN_NAMES = [
    "Mira",
    "Lina",
    "Vera",
    "Noor",
    "Iris",
    "Sana",
    "Rhea",
    "Yara",
    "Niko",
    "Ezra",
    "Tao",
    "Omar",
    "Jun",
    "Milo",
    "Ari",
    "Leon",
]

PERSONA_FAMILY_NAMES = [
    "Voss",
    "Sable",
    "Rook",
    "Vale",
    "Cross",
    "Nadir",
    "Kade",
    "Storm",
    "Lin",
    "Moreau",
    "Bose",
    "Klein",
    "Okafor",
    "Marin",
    "Ishikawa",
    "Santos",
]

PERSONA_TITLES = [
    "黑手党的小公主",
    "边境线上的情报经纪",
    "沉默的实验室继承人",
    "地下物流的白手套",
    "旧城媒体线人",
    "危机谈判桌上的影子顾问",
    "港口路线的年轻掌舵人",
    "公共卫生网络的夜班哨兵",
    "科学委员会的异端记录员",
    "能源转型局的灰色协调者",
    "人道响应链路里的现场耳目",
    "教育网络中的流动组织者",
]

MEMBERS_PER_NETWORK = 56


def create_enterprise_earth_world(seed: int = 7) -> World:
    rng = Random(seed)
    world = World(
        "enterprise-earth",
        {
            "seed": seed,
            "scenario": "enterprise_earth",
            "scene_title": "星球文明",
            "viewer_title": "星球文明",
            "planet_activity_stage": 0,
            "planet_activity_cycle": 0,
            "coverage": {
                "mode": "foundation_sample",
                "target": "all countries, organizations, and people through governed import pipelines",
                "current_country_count": len(COUNTRIES),
                "current_organization_count": len(ORGANIZATIONS),
                "ordinary_people_model": "anonymous_population_cohorts",
            },
            "governance": {
                "public_entities": "countries, public organizations, and public historical demonstration figures",
                "private_individuals": "not directly simulated",
                "ordinary_people": "anonymous aggregate or synthetic cohort only",
                "prediction_policy": "scenario simulation and hypothesis exploration, not deterministic real-world prediction",
            },
        },
    )
    _add_countries(world)
    _add_organizations(world, rng)
    _add_key_characters(world)
    _add_population_cohorts(world, rng)
    _seed_display_payloads(world)
    return world


def _add_countries(world: World) -> None:
    radius = 12.0
    for index, (country_id, name, region) in enumerate(COUNTRIES):
        angle = (2 * pi * index) / len(COUNTRIES)
        world.add_node(
            country_id,
            "country",
            name,
            (round(cos(angle) * radius, 3), round(sin(angle) * radius, 3)),
            {
                "region": region,
                "agent_layer": "sovereign_context",
                "governance_class": "public_entity",
            },
        )


def _add_organizations(world: World, rng: Random) -> None:
    for index, org in enumerate(ORGANIZATIONS):
        anchor = world.node(org["anchor"])
        org_node = world.add_node(
            org["id"],
            "organization",
            org["name"],
            (anchor.position.x + 1.4 + index, anchor.position.y + 1.2),
            {
                "agent_layer": "relationship_network",
                "organization_kind": org["kind"],
                "scope": org["scope"],
                "members": [member_id for member_id, _ in _expanded_members(org)],
                "governance_class": "public_or_synthetic_network",
            },
        )
        world.add_relationship(org_node.id, anchor.id, "operates_in", 0.75, {"source": "enterprise_earth"})
        member_ids: list[str] = []
        for member_index, (member_id, role) in enumerate(_expanded_members(org)):
            node_id = f"{org['id']}:{member_id}"
            member_ids.append(node_id)
            angle = (2 * pi * member_index) / MEMBERS_PER_NETWORK
            ring = 0.72 + (member_index % 7) * 0.07
            persona = _persona_for_member(str(org["id"]), role, member_index)
            world.add_node(
                node_id,
                "organization_member",
                persona["name"],
                (
                    org_node.position.x + cos(angle) * ring + rng.random() * 0.04,
                    org_node.position.y + sin(angle) * ring + rng.random() * 0.04,
                ),
                {
                    "role": role,
                    "persona_title": persona["title"],
                    "persona_archetype": persona["archetype"],
                    "display_role": f"{persona['title']} / {role.replace('_', ' ')}",
                    "agent_layer": "relationship_network_member",
                    "parent_network": org["id"],
                    "synthetic": True,
                },
            )
            world.add_relationship(node_id, org["id"], "member_of", 0.9, {"source": "enterprise_earth"})
        _add_internal_network_relationships(world, member_ids)


def _expanded_members(org: dict[str, object]) -> list[tuple[str, str]]:
    base = list(org["members"])  # type: ignore[index]
    members: list[tuple[str, str]] = [(str(member_id), str(role)) for member_id, role in base]
    index = 0
    while len(members) < MEMBERS_PER_NETWORK:
        role = NETWORK_ROLE_POOL[index % len(NETWORK_ROLE_POOL)]
        members.append((f"{role}-node-{index + 1:02d}", role))
        index += 1
    return members[:MEMBERS_PER_NETWORK]


def _persona_for_member(org_id: str, role: str, index: int) -> dict[str, str]:
    seed = sum(ord(char) for char in f"{org_id}:{role}:{index}")
    given = PERSONA_GIVEN_NAMES[seed % len(PERSONA_GIVEN_NAMES)]
    family = PERSONA_FAMILY_NAMES[(seed // 7) % len(PERSONA_FAMILY_NAMES)]
    title = PERSONA_TITLES[(seed // 13) % len(PERSONA_TITLES)]
    return {
        "name": f"{given} {family}",
        "title": title,
        "archetype": f"{title}，负责{role.replace('_', ' ')}",
    }


def _add_internal_network_relationships(world: World, member_ids: list[str]) -> None:
    for source_id, target_id in zip(member_ids, member_ids[1:] + member_ids[:1], strict=True):
        world.add_relationship(source_id, target_id, "coordination", 0.52, {"source": "enterprise_earth"})
    hub_ids = member_ids[:4]
    for index, member_id in enumerate(member_ids[4:], start=4):
        hub_id = hub_ids[index % len(hub_ids)]
        world.add_relationship(hub_id, member_id, "influence", 0.34, {"source": "enterprise_earth"})
        if index % 5 == 0:
            dependency_target = member_ids[(index + 11) % len(member_ids)]
            world.add_relationship(member_id, dependency_target, "dependency", 0.28, {"source": "enterprise_earth"})


def _add_key_characters(world: World) -> None:
    for character in KEY_CHARACTERS:
        anchor = world.node(character["anchor"])
        node = world.add_node(
            character["id"],
            "key_character",
            character["name"],
            (anchor.position.x + 0.8, anchor.position.y - 1.1),
            {
                "identity": character["identity"],
                "agent_layer": "key_character",
                "governance_class": "public_historical_demonstration",
            },
        )
        node.key_character = {
            "agent_layer": "key_character",
            "public_figure": True,
            "identity": character["identity"],
            "memory_policy": "public_or_scenario_memory_only",
            "thought_seed": character["thought"],
        }
        node.memories.append(
            {
                "kind": "public_context",
                "summary": f"{character['name']} participates as a public demonstration key character.",
            }
        )
        world.add_relationship(node.id, anchor.id, "public_context", 0.4, {"source": "enterprise_earth"})
        world.set_movement_target(node.id, (anchor.position.x + 1.6, anchor.position.y - 0.4), 0.35)


def _add_population_cohorts(world: World, rng: Random) -> None:
    selected_countries = COUNTRIES[:4]
    for country_index, (country_id, _, _) in enumerate(selected_countries):
        anchor = world.node(country_id)
        for identity_index, (suffix, identity, domain) in enumerate(COHORT_IDENTITIES):
            node_id = f"cohort-{country_id.removeprefix('country-')}-{suffix}"
            world.add_node(
                node_id,
                "population_cohort",
                f"{identity.title()} Cohort",
                (
                    anchor.position.x + (identity_index - 1) * 0.45,
                    anchor.position.y - 1.5 - country_index * 0.08,
                ),
                {
                    "identity": identity,
                    "domain": domain,
                    "agent_layer": "population_cohort",
                    "synthetic": True,
                    "privacy": "anonymous_aggregate",
                    "population_scale": 1000 + rng.randint(0, 500),
                },
            )
            world.add_relationship(node_id, country_id, "located_in", 0.8, {"source": "enterprise_earth"})


def _seed_display_payloads(world: World) -> None:
    ingestor = FeedbackIngestor()
    effects = [
        effect(
            "thought_bubble_add",
            target="node:key-albert-einstein",
            text="If the rules are consistent, the world line can be explained.",
            source="enterprise_earth",
            salience=0.8,
        ),
        effect(
            "action_bullet_add",
            target="node:key-albert-einstein",
            text="publishes a theoretical note",
            source="enterprise_earth",
            salience=0.7,
        ),
        effect(
            "thought_bubble_add",
            target="node:org-science-council",
            text="The science network is turning observations into structured pressure.",
            source="enterprise_earth",
            salience=0.65,
        ),
        effect(
            "action_bullet_add",
            target="node:cohort-us-doctors",
            text="coordinates hospital capacity signals",
            source="enterprise_earth",
            salience=0.55,
        ),
    ]
    ingestor.ingest(
        world,
        ActionFeedback(
            source="enterprise_earth",
            actor_type="system",
            actor_id="enterprise_earth_seed",
            action="seed_enterprise_display_payloads",
            summary="Seed enterprise Earth thoughts and action bullets.",
            targets=[target("world", world.id)],
            effects=effects,
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )
