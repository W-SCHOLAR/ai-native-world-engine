from __future__ import annotations

import pytest

from ai_native_world_engine import (
    ScenarioRegistry,
    World,
    register_scenario,
    scenario_names,
    unregister_scenario,
)
from ai_native_world_engine.core import RunConfig, run


def test_default_registry_preserves_builtins_and_seed_alias() -> None:
    names = scenario_names(include_aliases=True)

    assert {
        "seed",
        "ai_earth_seed",
        "enterprise_earth",
        "compound_crisis",
        "tribe_survival",
        "catalog",
    }.issubset(names)
    assert World.scenario("seed", seed=17).snapshot() == World.scenario(
        "ai_earth_seed", seed=17
    ).snapshot()


def test_isolated_registry_supports_aliases_enumeration_and_unregistration() -> None:
    registry = ScenarioRegistry()

    def create_demo(seed: int = 0) -> World:
        return World("registry-demo", {"seed": seed})

    registration = registry.register(
        "demo",
        create_demo,
        aliases=("example",),
        origin="test",
    )

    assert registration.origin == "test"
    assert registry.names() == ("demo",)
    assert registry.names(include_aliases=True) == ("demo", "example")
    assert registry.create("example", seed=9).attributes["seed"] == 9
    assert "demo" in registry
    assert "example" in registry

    removed = registry.unregister("example")
    assert removed.name == "demo"
    assert registry.names(include_aliases=True) == ()
    with pytest.raises(ValueError, match="未知场景"):
        registry.create("demo")


def test_registry_rejects_collisions_and_supports_explicit_replacement() -> None:
    registry = ScenarioRegistry()
    registry.register("first", lambda: World("first"), aliases=("shared",))

    with pytest.raises(ValueError, match="已注册"):
        registry.register("shared", lambda: World("collision"))
    with pytest.raises(ValueError, match="已注册"):
        registry.register("second", lambda: World("collision"), aliases=("first",))

    registry.register(
        "second",
        lambda: World("second"),
        aliases=("shared",),
        replace=True,
    )

    assert registry.create("shared").id == "second"
    assert registry.names(include_aliases=True) == ("second", "shared")
    with pytest.raises(ValueError, match="未知场景"):
        registry.create("first")


def test_registry_validates_names_factories_and_factory_results() -> None:
    registry = ScenarioRegistry()

    with pytest.raises(ValueError, match="不能为空"):
        registry.register(" ", lambda: World("empty"))
    with pytest.raises(ValueError, match="主名称"):
        registry.register("same", lambda: World("same"), aliases=("same",))
    with pytest.raises(TypeError, match="必须可调用"):
        registry.register("bad", object())  # type: ignore[arg-type]

    registry.register("invalid-result", lambda: object())  # type: ignore[arg-type,return-value]
    with pytest.raises(TypeError, match="必须返回 World"):
        registry.create("invalid-result")


def test_external_scenario_uses_world_and_run_harness_public_paths() -> None:
    name = "test_external_registry_scenario"

    def create_external(seed: int = 0) -> World:
        world = World("external-registry-world", {"scenario": name, "seed": seed})
        world.add_node("node", "person", "Registry Node", (0, 0))
        return world

    register_scenario(name, create_external, origin="test")
    try:
        assert World.scenario(name, seed=23).attributes["seed"] == 23
        result = run(RunConfig(scenario=name, seed=23, ticks=1)).to_dict()
        assert result["snapshot"]["id"] == "external-registry-world"
        assert result["snapshot"]["tick"] == 1
        assert result["config"]["scenario"] == name
    finally:
        unregister_scenario(name)

    assert name not in scenario_names(include_aliases=True)


def test_world_scenario_keeps_unknown_name_error_compatible() -> None:
    with pytest.raises(ValueError, match="未知场景：missing-registry-scenario"):
        World.scenario("missing-registry-scenario")
