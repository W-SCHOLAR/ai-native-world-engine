import json

from ai_native_world_engine.core import RunConfig, World, run


def test_enterprise_earth_scenario_is_reproducible_and_serializable() -> None:
    first = World.scenario("enterprise_earth", seed=101).snapshot()
    second = World.scenario("enterprise_earth", seed=101).snapshot()

    assert first == second
    assert first["attributes"]["scenario"] == "enterprise_earth"
    assert first["attributes"]["coverage"]["ordinary_people_model"] == "anonymous_population_cohorts"
    json.dumps(first, ensure_ascii=False)


def test_enterprise_earth_contains_governed_entity_layers() -> None:
    snapshot = World.scenario("enterprise_earth", seed=7).snapshot()
    nodes = {node["id"]: node for node in snapshot["nodes"]}

    countries = [node for node in nodes.values() if node["type"] == "country"]
    organizations = [node for node in nodes.values() if node["type"] == "organization"]
    key_characters = [node for node in nodes.values() if node["type"] == "key_character"]
    cohorts = [node for node in nodes.values() if node["type"] == "population_cohort"]

    assert len(countries) >= 8
    assert len(organizations) == 10
    assert len(key_characters) == 5
    assert cohorts
    assert all(
        node["attributes"]["agent_layer"] == "relationship_network"
        for node in organizations
    )
    assert all(node["attributes"]["privacy"] == "anonymous_aggregate" for node in cohorts)
    assert all(node["attributes"]["synthetic"] is True for node in cohorts)


def test_enterprise_earth_models_organization_networks_and_key_characters() -> None:
    snapshot = World.scenario("enterprise_earth", seed=7).snapshot()
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    relationships = snapshot["relationships"]

    assert nodes["org-science-council"]["attributes"]["agent_layer"] == "relationship_network"
    assert nodes["key-albert-einstein"]["key_character"]["agent_layer"] == "key_character"
    assert nodes["key-albert-einstein"]["key_character"]["public_figure"] is True
    assert nodes["key-albert-einstein"]["attributes"]["identity"] == "scientist"
    assert any(
        edge["source"].startswith("org-science-council:")
        and edge["target"] == "org-science-council"
        and edge["type"] == "member_of"
        for edge in relationships
    )
    assert any(edge["type"] == "coordination" for edge in relationships)


def test_enterprise_earth_has_dense_relationship_network_agents() -> None:
    snapshot = World.scenario("enterprise_earth", seed=7).snapshot()
    organizations = [
        node
        for node in snapshot["nodes"]
        if node["type"] == "organization"
        and node["attributes"]["agent_layer"] == "relationship_network"
    ]
    member_counts = {node["id"]: 0 for node in organizations}

    for edge in snapshot["relationships"]:
        if edge["type"] == "member_of" and edge["target"] in member_counts:
            member_counts[edge["target"]] += 1

    assert len(organizations) == 10
    assert all(count >= 50 for count in member_counts.values())
    assert any(edge["type"] == "influence" for edge in snapshot["relationships"])
    assert any(edge["type"] == "dependency" for edge in snapshot["relationships"])


def test_enterprise_earth_runs_through_harness() -> None:
    result = run(RunConfig(scenario="enterprise_earth", seed=11, ticks=2)).to_dict()

    assert result["config"]["scenario"] == "enterprise_earth"
    assert result["snapshot"]["tick"] == 2
    assert result["scorecard"]["metrics"]["provider_outputs"] == 15
    assert result["events"]
    assert result["traces"]
    json.dumps(result, ensure_ascii=False)
