import json
from pathlib import Path

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    FeedbackIngestor,
    ProviderContext,
    ProviderOutput,
    ResourceTransferRulePackage,
    RuleEngineSet,
    RunConfig,
    World,
    effect,
    run,
)


def test_resource_transfer_feedback_moves_inventory_between_nodes() -> None:
    world = World("resources")
    world.add_node("giver", "person", "Giver", (0, 0), {"resources": {"food": 5}})
    world.add_node("receiver", "person", "Receiver", (1, 0), {"resources": {"food": 1}})

    FeedbackIngestor().ingest(
        world,
        ActionFeedback(
            source="test",
            actor_type="system",
            actor_id="test",
            action="resource_transfer",
            summary="transfer food",
            effects=[
                effect(
                    "resource_transfer",
                    **{
                        "from": "node:giver",
                        "to": "node:receiver",
                        "resource": "food",
                        "amount": 2,
                    },
                )
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )

    assert world.node("giver").attributes["resources"]["food"] == 3
    assert world.node("receiver").attributes["resources"]["food"] == 3
    assert world.errors == []
    json.dumps(world.snapshot(), ensure_ascii=False)


def test_resource_transfer_rule_obeys_inventory_hard_constraint() -> None:
    world = World("resources")
    world.add_node("giver", "person", "Giver", (0, 0), {"alive": True, "resources": {"food": 1}})
    world.add_node("receiver", "person", "Receiver", (1, 0), {"resources": {}})
    world.node("giver").rule_pressures.append(
        {
            "rule": "resource_transfer",
            "weight": 1.0,
            "ttl": 1,
            "to": "node:receiver",
            "resource": "food",
            "amount": 2,
        }
    )

    engine = RuleEngineSet([ResourceTransferRulePackage()])

    assert engine.decide(world, world.node("giver")) is None

    engine.step(world)
    assert world.node("giver").attributes["resources"]["food"] == 1
    assert world.node("receiver").attributes["resources"] == {}


def test_resource_transfer_rule_transfers_when_pressure_is_grounded() -> None:
    world = World("resources")
    world.add_node("giver", "person", "Giver", (0, 0), {"alive": True, "resources": {"food": 5}})
    world.add_node("receiver", "person", "Receiver", (1, 0), {"resources": {}})
    world.node("giver").rule_pressures.append(
        {
            "rule": "resource_transfer",
            "weight": 1.0,
            "ttl": 1,
            "to": "node:receiver",
            "resource": "food",
            "amount": 2,
        }
    )

    engine = RuleEngineSet.from_scenario(["resource_transfer"])
    world.step(engine)

    assert world.node("giver").attributes["resources"]["food"] == 3
    assert world.node("receiver").attributes["resources"]["food"] == 2
    assert any(
        event["payload"].get("action") == "resource_transfer"
        for event in world.events.recent()
    )
    assert any(trace["kind"] == "resource_transfer" for trace in world.traces.recent())


class StaticTransferProvider:
    name = "static-transfer"

    def observe(self, context: ProviderContext) -> ProviderOutput:
        return ProviderOutput(
            source=self.name,
            summary="request resource transfer",
            effects=[
                effect(
                    "rule_pressure_add",
                    target="node:giver",
                    rule="resource_transfer",
                    weight=1.0,
                    ttl=2,
                    source=self.name,
                    reason="receiver needs food",
                    to="node:receiver",
                    resource="food",
                    amount=2,
                )
            ],
            metadata={"provider_tick": context.tick},
        )


def test_run_harness_matches_resource_transfer_pressure(tmp_path: Path) -> None:
    catalog_path = tmp_path / "resource-world.json"
    catalog_path.write_text(
        json.dumps(
            {
                "world": {"id": "resource-world"},
                "nodes": [
                    {
                        "id": "giver",
                        "type": "person",
                        "name": "Giver",
                        "position": {"x": 0, "y": 0},
                        "attributes": {"synthetic": True, "resources": {"food": 5}},
                    },
                    {
                        "id": "receiver",
                        "type": "person",
                        "name": "Receiver",
                        "position": {"x": 1, "y": 0},
                        "attributes": {"synthetic": True, "resources": {}},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run(
        RunConfig(
            scenario="catalog",
            scenario_path=str(catalog_path),
            ticks=1,
            rules=["resource_transfer"],
            provider=StaticTransferProvider(),
        )
    ).to_dict()

    nodes = {node["id"]: node for node in result["snapshot"]["nodes"]}
    assert nodes["giver"]["attributes"]["resources"]["food"] == 3
    assert nodes["receiver"]["attributes"]["resources"]["food"] == 2
    assert result["pressure_action_report"]["totals"]["pressures"] == 1
    assert result["pressure_action_report"]["totals"]["matched"] == 1
    assert result["scorecard"]["score"] == 100.0
