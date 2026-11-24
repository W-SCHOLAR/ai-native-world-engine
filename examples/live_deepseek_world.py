"""Run a product world with a live DeepSeek JSON provider.

模型只写结构化压力；行动仍由规则引擎裁决。需要环境变量 ``DEEPSEEK_API_KEY``。
"""

from __future__ import annotations

import argparse
import json
import os

from ai_native_world_engine.core import (
    DeepSeekJsonClient,
    JsonLlmProviderAdapter,
    RunConfig,
    expand_rule_names,
    project_run_for_viewer,
    run,
)
from ai_native_world_engine.core.runner import default_rules_for_scenario


PRODUCT_SCENARIOS = ("enterprise_earth", "tribe_survival")


def build_provider(
    *,
    api_key: str,
    model: str,
    base_url: str,
    rules: list[str],
    max_attempts: int,
) -> JsonLlmProviderAdapter:
    allowed = set(expand_rule_names(rules))
    if "movement" in allowed:
        allowed.add("move")
    return JsonLlmProviderAdapter(
        client=DeepSeekJsonClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
        ),
        allowed_rule_names=allowed,
        max_attempts=max_attempts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default="enterprise_earth",
        choices=PRODUCT_SCENARIOS,
        help="产品世界：星球文明或蛮荒世界",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--ticks", type=int, default=1)
    parser.add_argument(
        "--model",
        default=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "DEEPSEEK_API_KEY is required, for example: "
            "DEEPSEEK_API_KEY=sk-... uv run python examples/live_deepseek_world.py"
        )

    rules = default_rules_for_scenario(args.scenario)
    provider = build_provider(
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
        rules=rules,
        max_attempts=max(1, args.max_attempts),
    )

    result = run(
        RunConfig(
            scenario=args.scenario,
            seed=args.seed,
            ticks=args.ticks,
            scheduler_provider=provider,
            capture_timeline=True,
        )
    )
    report = result.to_dict()
    projection = project_run_for_viewer(result).to_dict()
    summary = projection.get("summary", {})
    scorecard = report.get("scorecard", {})
    pressure = report.get("pressure_action_report", {}).get("totals", {})
    provider_totals = report.get("provider_execution_report", {}).get("totals", {})

    print(
        json.dumps(
            {
                "scenario": args.scenario,
                "model": args.model,
                "requested_ticks": args.ticks,
                "world_tick": report.get("snapshot", {}).get("tick"),
                "scene_title": summary.get("scene_title"),
                "score": scorecard.get("score"),
                "match_rate": pressure.get("match_rate"),
                "grounded_actions": len(projection.get("grounded_actions", [])),
                "provider_outputs": provider_totals.get("outputs"),
                "provider_attempts": provider_totals.get("attempts"),
                "provider_failures": provider_totals.get("failures"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    visible_thoughts: list[tuple[str, str]] = []
    for output in report.get("provider_outputs", []):
        for effect in output.get("effects", []):
            if effect.get("type") not in {
                "thought_bubble_add",
                "memory_add",
                "action_bullet_add",
            }:
                continue
            text = str(effect.get("text", "")).strip()
            if text:
                target = str(effect.get("target", "")).removeprefix("node:")
                visible_thoughts.append((target or "?", text))
    for node_id, text in visible_thoughts[:5]:
        print(f"- {node_id}: {text[:120]}")


if __name__ == "__main__":
    main()
