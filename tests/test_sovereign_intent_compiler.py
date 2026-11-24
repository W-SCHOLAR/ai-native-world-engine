from __future__ import annotations

from ai_native_world_engine.core import (
    FeedbackIngestor,
    RuleEngineSet,
    RunConfig,
    SOVEREIGN_INTENT_ENVELOPE_SCHEMA,
    SOVEREIGN_INTENT_SCHEMA,
    SovereignDynamicRulePackage,
    SovereignIntentCompiler,
    SovereignIntentPlan,
    World,
    apply_sovereign_intent_plan,
    run,
)


class FakeSovereignClient:
    def __init__(self) -> None:
        self.envelope = {}

    def complete(self, envelope: dict) -> dict:
        self.envelope = envelope
        return {
            "id": "red_moon_dream",
            "title": "红月入梦",
            "summary": "天下今夜梦见红月。",
            "impact_level": "omen",
            "initial_effects": [
                {
                    "type": "world_state",
                    "field": "red_moon_night",
                    "value": True,
                },
                {
                    "type": "thought_bubble_add",
                    "target": "node:mira",
                    "text": "王命像红月一样压进梦里。",
                    "source": "sovereign_intent",
                },
            ],
            "dynamic_rules": [
                {
                    "id": "red_moon_dream_spread",
                    "action": "dream_vision",
                    "summary": "{node.name} 梦见红月。",
                    "trigger": {
                        "node_types": ["person"],
                        "world_flag": "red_moon_night",
                    },
                    "score": 9,
                    "ttl": 3,
                    "effects": [
                        {
                            "type": "memory_add",
                            "target": "node:{node.id}",
                            "text": "{node.name} 梦见红月压过城墙。",
                            "source": "sovereign_intent",
                            "importance": 0.72,
                        },
                        {
                            "type": "action_bullet_add",
                            "target": "node:{node.id}",
                            "text": "梦见红月",
                            "source": "sovereign_intent",
                            "salience": 0.8,
                        },
                    ],
                }
            ],
        }


def test_sovereign_intent_compiler_builds_envelope_and_normalizes_plan() -> None:
    world = World.scenario("seed", seed=7)
    client = FakeSovereignClient()

    plan = SovereignIntentCompiler(client=client).compile(world, "让天下所有人今晚梦见红月")

    assert client.envelope["schema"] == SOVEREIGN_INTENT_ENVELOPE_SCHEMA
    assert client.envelope["user_input"] == "让天下所有人今晚梦见红月"
    assert client.envelope["expected_output"]["dynamic_rules"][0]["effects"][0]["type"] == "memory_add"
    assert plan.to_dict()["schema"] == SOVEREIGN_INTENT_SCHEMA
    assert plan.id == "red_moon_dream"
    assert plan.impact_level == "omen"
    assert plan.initial_effects[0].type == "world_state"
    assert plan.dynamic_rules[0].id == "red_moon_dream_spread"
    assert plan.metadata["sovereign_intent_compiler"]["schema"] == SOVEREIGN_INTENT_ENVELOPE_SCHEMA


def test_dynamic_rule_package_executes_declarative_rule_effects() -> None:
    world = World.scenario("seed", seed=7)
    plan = SovereignIntentCompiler(client=FakeSovereignClient()).compile(world, "红月入梦")

    apply_sovereign_intent_plan(world, FeedbackIngestor(), plan)
    world.step(RuleEngineSet([SovereignDynamicRulePackage(plan)]))

    mira = world.node("mira")
    assert world.attributes["red_moon_night"] is True
    assert any(memory["text"] == "米拉 梦见红月压过城墙。" for memory in mira.memories)
    assert any(event["payload"].get("text") == "梦见红月" for event in world.presentation.recent())
    assert any(trace["kind"] == "sovereign_intent" for trace in world.snapshot()["traces"])


def test_run_config_replays_compiled_sovereign_intent() -> None:
    plan = SovereignIntentPlan.from_dict(FakeSovereignClient().complete({}))

    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            sovereign_intents=[plan],
        )
    ).to_dict()

    mira = next(node for node in result["snapshot"]["nodes"] if node["id"] == "mira")
    assert result["config"]["sovereign_intents"][0]["id"] == "red_moon_dream"
    assert result["sovereign_intent_audits"][0]["dynamic_rule_count"] == 1
    assert result["snapshot"]["attributes"]["red_moon_night"] is True
    assert any(memory["text"] == "米拉 梦见红月压过城墙。" for memory in mira["memories"])
    assert any(event["source"] == "sovereign_intent" for event in result["events"])
