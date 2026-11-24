"""Runtime-readiness API route."""

from __future__ import annotations

from typing import Any

from ..router_compat import create_router


def build_health_router(health: dict[str, object]) -> Any:
    router = create_router()

    @router.get("/health")
    def get_health() -> dict[str, object]:
        return dict(health)

    return router
