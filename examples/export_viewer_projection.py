"""Export a run result projection as a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from ai_native_world_engine.core import RunConfig, project_run_for_viewer, run


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = (ROOT / "examples" / "world-data.json",)
EXPORT_SCENARIO = "enterprise_earth"
EXPORT_SEED = 5
EXPORT_TICKS = 1


def build_projection() -> dict[str, object]:
    result = run(
        RunConfig(
            scenario=EXPORT_SCENARIO,
            seed=EXPORT_SEED,
            ticks=EXPORT_TICKS,
        )
    )
    return project_run_for_viewer(result).to_dict()


def write_projection(
    projection: dict[str, object],
    outputs: tuple[Path, ...] = DEFAULT_OUTPUTS,
) -> None:
    payload = json.dumps(projection, ensure_ascii=False, indent=2) + "\n"
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")


def main() -> None:
    write_projection(build_projection())
    for output in DEFAULT_OUTPUTS:
        print(output)


if __name__ == "__main__":
    main()
