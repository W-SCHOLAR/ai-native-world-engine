import json
from pathlib import Path

import pytest

from ai_native_world_engine.core import RunConfig, World, run


CATALOG = Path("examples/catalogs/enterprise_earth_sample.json")


def test_catalog_scenario_import_is_reproducible_and_serializable() -> None:
    first = World.scenario("catalog", scenario_path=CATALOG).snapshot()
    second = World.scenario("catalog", scenario_path=CATALOG).snapshot()

    assert first == second
    assert first["id"] == "enterprise-earth-catalog-sample"
    assert first["attributes"]["scenario"] == "catalog"
    assert any(node["id"] == "org-science-council" for node in first["nodes"])
    json.dumps(first, ensure_ascii=False)


def test_catalog_import_preserves_agent_fields() -> None:
    snapshot = World.scenario("catalog", scenario_path=CATALOG).snapshot()
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    relationships = snapshot["relationships"]

    assert nodes["org-science-council"]["attributes"]["agent_layer"] == "relationship_network"
    assert nodes["key-albert-einstein"]["key_character"]["agent_layer"] == "key_character"
    assert nodes["cohort-us-doctors"]["attributes"]["privacy"] == "anonymous_aggregate"
    assert any(edge["type"] == "coordination" for edge in relationships)
    assert not any(event["kind"] == "display_payload" for event in snapshot["events"])


def test_catalog_rejects_ungoverned_person(tmp_path: Path) -> None:
    path = tmp_path / "bad-person.json"
    path.write_text(
        json.dumps(
            {
                "world": {"id": "bad"},
                "nodes": [
                    {
                        "id": "person-real-private",
                        "type": "person",
                        "name": "Private Person",
                        "position": {"x": 0, "y": 0},
                        "attributes": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be synthetic"):
        World.scenario("catalog", scenario_path=path)


def test_catalog_rejects_non_anonymous_cohort(tmp_path: Path) -> None:
    path = tmp_path / "bad-cohort.json"
    path.write_text(
        json.dumps(
            {
                "world": {"id": "bad"},
                "nodes": [
                    {
                        "id": "cohort",
                        "type": "population_cohort",
                        "name": "Cohort",
                        "position": {"x": 0, "y": 0},
                        "attributes": {"synthetic": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="anonymous_aggregate"):
        World.scenario("catalog", scenario_path=path)


def test_catalog_runs_through_harness() -> None:
    result = run(
        RunConfig(
            scenario="catalog",
            scenario_path=str(CATALOG),
            ticks=1,
        )
    ).to_dict()

    assert result["config"]["scenario"] == "catalog"
    assert result["config"]["scenario_path"] == str(CATALOG)
    assert result["snapshot"]["tick"] == 1
    assert result["scorecard"]["metrics"]["provider_outputs"] == 1
    json.dumps(result, ensure_ascii=False)
