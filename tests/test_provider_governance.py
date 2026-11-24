from ai_native_world_engine.core import (
    GovernedProviderRunner,
    ProviderContext,
    ProviderOutput,
    ProviderRegistry,
    RunConfig,
    World,
    effect,
    run,
)


class AllowlistProvider:
    name = "allowlist-provider"

    def __init__(self, rule: str = "move", relation: str = "trust") -> None:
        self.rule = rule
        self.relation = relation

    def observe(self, context: ProviderContext) -> ProviderOutput:
        return ProviderOutput(
            source=self.name,
            summary="governed output",
            effects=[
                effect(
                    "rule_pressure_add",
                    target="node:mira",
                    rule=self.rule,
                    weight=0.4,
                    ttl=2,
                ),
                effect(
                    "relationship_delta",
                    source="node:mira",
                    target="node:atlas",
                    relation=self.relation,
                    delta=0.1,
                ),
            ],
        )


def make_world() -> World:
    world = World("governance-test")
    world.add_node("mira", "person", "Mira", (0, 0))
    world.add_node("atlas", "person", "Atlas", (1, 0))
    return world


def make_context(world: World) -> ProviderContext:
    return ProviderContext(world=world, tick=0, snapshot=world.snapshot(), params={})


def test_provider_registry_exposes_allowlist_metadata() -> None:
    registry = ProviderRegistry()
    registry.register(
        "baseline",
        AllowlistProvider(),
        allowed_rule_names={"move"},
        allowed_relationship_types={"trust"},
    )

    assert registry.to_dict() == {
        "providers": [
            {
                "id": "baseline",
                "provider": "allowlist-provider",
                "allowed_rule_names": ["move"],
                "allowed_relationship_types": ["trust"],
            }
        ]
    }


def test_governed_provider_accepts_allowed_output() -> None:
    world = make_world()
    world.set_movement_target("mira", (2, 0), 1.0)
    registry = ProviderRegistry()
    registry.register(
        "baseline",
        AllowlistProvider(rule="move", relation="trust"),
        allowed_rule_names={"move"},
        allowed_relationship_types={"trust"},
    )

    result = GovernedProviderRunner(registry).observe("baseline", make_context(world))

    assert result.output is not None
    assert result.audit.accepted is True
    assert result.audit.raw_effect_count == 2
    assert result.audit.accepted_effect_count == 2
    assert [effect.type for effect in result.output.effects] == ["rule_pressure_add", "relationship_delta"]


def test_governed_provider_rejects_disallowed_rule_without_effects() -> None:
    world = make_world()
    registry = ProviderRegistry()
    registry.register(
        "baseline",
        AllowlistProvider(rule="attack", relation="trust"),
        allowed_rule_names={"move"},
        allowed_relationship_types={"trust"},
    )

    result = GovernedProviderRunner(registry).observe("baseline", make_context(world))

    assert result.output is None
    assert result.audit.accepted is False
    assert "unregistered rule" in result.audit.error
    assert world.node("mira").rule_pressures == []


def test_run_harness_preserves_provider_failure_audit() -> None:
    result = run(
        RunConfig(
            scenario="seed",
            seed=7,
            ticks=1,
            provider=AllowlistProvider(rule="attack", relation="trust"),
            govern_provider_output=True,
            provider_id="bad-provider",
            allowed_rule_names=["move"],
            allowed_relationship_types=["trust"],
        )
    ).to_dict()

    assert result["provider_outputs"] == []
    assert result["provider_audits"][0]["accepted"] is False
    assert "unregistered rule" in result["provider_audits"][0]["error"]
    assert all(node["rule_pressures"] == [] for node in result["snapshot"]["nodes"])
