from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rule_runtime_is_split_behind_compatibility_facade() -> None:
    core = ROOT / "src" / "ai_native_world_engine" / "core"
    facade = core / "rules.py"
    implementation_modules = [
        core / "rule_contracts.py",
        core / "rule_engine.py",
        core / "rule_lifecycle.py",
        core / "rule_packages.py",
        core / "rule_registry.py",
        core / "rule_support.py",
    ]

    assert _line_count(facade) <= 100
    assert all(path.exists() for path in implementation_modules)
    assert all(_line_count(path) <= 650 for path in implementation_modules)
    facade_source = facade.read_text(encoding="utf-8")
    assert "RuleEngineSet" in facade_source
    assert "RuleCandidate" in facade_source
    assert "expand_rule_names" in facade_source


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())
