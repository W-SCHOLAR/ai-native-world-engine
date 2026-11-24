"""Watch a world run in the terminal, one step at a time.

需要环境变量 ``DEEPSEEK_API_KEY``。模型只写结构化压力；行动由规则引擎裁决。
"""

from __future__ import annotations

import argparse
import json
import os
import time

from ai_native_world_engine.core import RunConfig, RunSession
from ai_native_world_engine.core.runner import default_rules_for_scenario
from live_deepseek_world import PRODUCT_SCENARIOS, build_provider


MAX_MODEL_LINES = 4
MAX_THOUGHT_LINES = 4
MAX_ACTION_LINES = 3
THOUGHT_MARKERS = {
    "thought_bubble": "思考",
    "action_bullet": "动作",
    "speech_bubble": "说",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default="tribe_survival",
        choices=PRODUCT_SCENARIOS,
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
            "DEEPSEEK_API_KEY=sk-... uv run python examples/watch_world.py"
        )

    rules = default_rules_for_scenario(args.scenario)
    provider = build_provider(
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
        rules=rules,
        max_attempts=max(1, args.max_attempts),
    )
    session = RunSession(
        RunConfig(
            scenario=args.scenario,
            seed=args.seed,
            ticks=args.ticks,
            scheduler_provider=provider,
        )
    )

    print(f"世界：{args.scenario}   模型：{args.model}   seed={args.seed}   ticks={args.ticks}")
    print("-" * 72)

    started = time.time()
    shown_thoughts = 0
    shown_actions = 0
    while True:
        increment = session.step_incremental()
        if increment is None:
            break
        tick = increment.commit.resulting_tick
        model_lines: list[str] = []
        thought_lines: list[str] = []
        action_lines: list[str] = []
        routine_actions = 0
        hidden_thoughts = 0

        for output in increment.provider_outputs:
            summary = str(output.get("summary", "")).strip()
            if not summary or summary.startswith("stable epoch candidates:"):
                continue
            if len(model_lines) < MAX_MODEL_LINES:
                model_lines.append(f"  [模型] {summary[:96]}")

        for event in increment.presentation_events:
            payload = event.get("payload", {})
            kind = str(payload.get("type", ""))
            marker = THOUGHT_MARKERS.get(kind)
            text = str(payload.get("text", "")).strip()
            if not marker or not text:
                continue
            if len(thought_lines) >= MAX_THOUGHT_LINES:
                hidden_thoughts += 1
                continue
            thought_lines.append(f"  [{marker}] {payload.get('node_id', '?')}: {text[:96]}")
            shown_thoughts += 1

        action_events = [
            event
            for event in increment.events
            if event.get("kind") == "action_feedback"
        ]
        for event in action_events:
            payload = event.get("payload", {})
            action = str(payload.get("action", "?"))
            if action.startswith("duty_"):
                routine_actions += 1
                continue
            if len(action_lines) < MAX_ACTION_LINES:
                action_lines.append(f"  [裁决] {payload.get('actor_id', '?')} → {action}")
                shown_actions += 1

        lines = model_lines + thought_lines + action_lines
        if routine_actions:
            lines.append(f"  [常规] 部落成员例行行动 {routine_actions} 条")
        if lines:
            print(f"[tick {tick}]")
            print("\n".join(lines))
            if hidden_thoughts:
                print(f"  … 另有 {hidden_thoughts} 条展示事件")
            print()

    if session.completed:
        session.close("run completed")
    report = session.result().to_dict()
    totals = report.get("provider_execution_report", {}).get("totals", {})
    scorecard = report.get("scorecard", {})
    pressure = report.get("pressure_action_report", {}).get("totals", {})

    print("-" * 72)
    print(
        json.dumps(
            {
                "world_tick": report.get("snapshot", {}).get("tick"),
                "elapsed_s": round(time.time() - started, 1),
                "score": scorecard.get("score"),
                "match_rate": pressure.get("match_rate"),
                "provider_outputs": totals.get("outputs"),
                "provider_attempts": totals.get("attempts"),
                "provider_failures": totals.get("failures"),
                "shown_thoughts": shown_thoughts,
                "shown_actions": shown_actions,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
