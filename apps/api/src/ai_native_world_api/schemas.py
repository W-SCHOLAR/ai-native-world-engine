"""Application DTO constructors.

These plain dictionaries mirror the shared-contract JSON schemas. They keep the
first API skeleton usable before Pydantic is introduced as an installed
dependency.
"""

from __future__ import annotations

from typing import Any


JsonDict = dict[str, Any]


def run_create_request(scenario: str = "seed", seed: int = 7, ticks: int = 3) -> JsonDict:
    return {"scenario": scenario, "seed": int(seed), "ticks": int(ticks)}


def run_status_event(run_id: str, status: str, message: str = "") -> JsonDict:
    return {
        "type": "run.status",
        "run_id": run_id,
        "status": status,
        "message": message,
    }
