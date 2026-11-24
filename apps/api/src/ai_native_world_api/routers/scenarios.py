"""Scenario API routes."""

from __future__ import annotations

from typing import Any

from ..router_compat import create_router
from ..services.run_service import RunService


def build_scenario_router(run_service: RunService) -> Any:
    router = create_router()

    @router.get("/scenarios")
    def list_scenarios() -> list[dict[str, object]]:
        return run_service.list_scenarios()

    return router
