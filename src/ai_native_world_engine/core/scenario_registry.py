"""Extensible scenario factory registry."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable


if TYPE_CHECKING:
    from .world import World


ScenarioFactory = Callable[..., "World"]


@dataclass(frozen=True, slots=True)
class ScenarioRegistration:
    name: str
    factory: ScenarioFactory
    aliases: tuple[str, ...] = ()
    origin: str = "external"


class ScenarioRegistry:
    """Map scenario names and aliases to world factories."""

    def __init__(self) -> None:
        self._registrations: dict[str, ScenarioRegistration] = {}
        self._aliases: dict[str, str] = {}
        self._lock = RLock()

    def register(
        self,
        name: str,
        factory: ScenarioFactory,
        *,
        aliases: tuple[str, ...] | list[str] = (),
        origin: str = "external",
        replace: bool = False,
    ) -> ScenarioRegistration:
        canonical = _scenario_name(name)
        normalized_aliases = tuple(dict.fromkeys(_scenario_name(alias) for alias in aliases))
        if canonical in normalized_aliases:
            raise ValueError(f"场景别名不能与主名称相同：{canonical}")
        if not callable(factory):
            raise TypeError("场景工厂必须可调用")

        registration = ScenarioRegistration(
            name=canonical,
            factory=factory,
            aliases=normalized_aliases,
            origin=str(origin or "external"),
        )
        with self._lock:
            conflicts = self._conflicting_registrations((canonical, *normalized_aliases))
            if conflicts and not replace:
                names = ", ".join(sorted(conflicts))
                raise ValueError(f"场景名称或别名已注册：{names}")
            if replace:
                for conflict in conflicts:
                    self._remove_registration(conflict)
            self._registrations[canonical] = registration
            for alias in normalized_aliases:
                self._aliases[alias] = canonical
        return registration

    def unregister(self, name: str) -> ScenarioRegistration:
        with self._lock:
            canonical = self._canonical_name(name)
            if canonical is None:
                raise ValueError(f"未知场景：{name}")
            registration = self._registrations[canonical]
            self._remove_registration(canonical)
            return registration

    def registration(self, name: str) -> ScenarioRegistration:
        with self._lock:
            canonical = self._canonical_name(name)
            if canonical is None:
                raise ValueError(f"未知场景：{name}")
            return self._registrations[canonical]

    def create(self, name: str, **kwargs: Any) -> "World":
        registration = self.registration(name)
        world = registration.factory(**kwargs)
        from .world import World

        if not isinstance(world, World):
            raise TypeError(
                f"场景工厂 {registration.name} 必须返回 World，实际为 {type(world).__name__}"
            )
        return world

    def names(self, *, include_aliases: bool = False) -> tuple[str, ...]:
        with self._lock:
            names = set(self._registrations)
            if include_aliases:
                names.update(self._aliases)
            return tuple(sorted(names))

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        with self._lock:
            return self._canonical_name(name) is not None

    def _canonical_name(self, name: str) -> str | None:
        normalized = _scenario_name(name)
        if normalized in self._registrations:
            return normalized
        return self._aliases.get(normalized)

    def _conflicting_registrations(self, names: tuple[str, ...]) -> set[str]:
        conflicts: set[str] = set()
        for name in names:
            if name in self._registrations:
                conflicts.add(name)
            alias_owner = self._aliases.get(name)
            if alias_owner is not None:
                conflicts.add(alias_owner)
        return conflicts

    def _remove_registration(self, canonical: str) -> None:
        registration = self._registrations.pop(canonical, None)
        if registration is None:
            return
        for alias in registration.aliases:
            self._aliases.pop(alias, None)


def lazy_scenario_factory(module_name: str, attribute: str) -> ScenarioFactory:
    """Resolve a scenario factory only when the scenario is first created."""

    resolved: ScenarioFactory | None = None
    lock = RLock()

    def create(**kwargs: Any) -> "World":
        nonlocal resolved
        if resolved is None:
            with lock:
                if resolved is None:
                    candidate = getattr(import_module(module_name), attribute)
                    if not callable(candidate):
                        raise TypeError(f"场景工厂不可调用：{module_name}:{attribute}")
                    resolved = candidate
        return resolved(**kwargs)

    return create


def _scenario_name(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError("场景名称不能为空")
    return name


DEFAULT_SCENARIO_REGISTRY = ScenarioRegistry()


def register_scenario(
    name: str,
    factory: ScenarioFactory,
    *,
    aliases: tuple[str, ...] | list[str] = (),
    origin: str = "external",
    replace: bool = False,
) -> ScenarioRegistration:
    return DEFAULT_SCENARIO_REGISTRY.register(
        name,
        factory,
        aliases=aliases,
        origin=origin,
        replace=replace,
    )


def unregister_scenario(name: str) -> ScenarioRegistration:
    return DEFAULT_SCENARIO_REGISTRY.unregister(name)


def scenario_names(*, include_aliases: bool = False) -> tuple[str, ...]:
    return DEFAULT_SCENARIO_REGISTRY.names(include_aliases=include_aliases)


def _register_builtin_scenarios() -> None:
    builtins = [
        (
            "seed",
            "ai_native_world_engine.scenarios.seed_scenarios",
            "create_seed_world",
            ("ai_earth_seed",),
        ),
        (
            "enterprise_earth",
            "ai_native_world_engine.scenarios.enterprise_earth",
            "create_enterprise_earth_world",
            (),
        ),
        (
            "compound_crisis",
            "ai_native_world_engine.scenarios.compound_crisis",
            "create_compound_crisis_world",
            (),
        ),
        (
            "tribe_survival",
            "ai_native_world_engine.scenarios.tribe_survival",
            "create_tribe_survival_world",
            (),
        ),
        (
            "catalog",
            "ai_native_world_engine.scenarios.catalog_loader",
            "load_catalog_world",
            (),
        ),
    ]
    for name, module_name, attribute, aliases in builtins:
        DEFAULT_SCENARIO_REGISTRY.register(
            name,
            lazy_scenario_factory(module_name, attribute),
            aliases=aliases,
            origin="builtin",
        )


_register_builtin_scenarios()
