"""Trace API routes."""

from __future__ import annotations

from typing import Any

from ..router_compat import create_router
from ..services.run_service import RunService


def build_trace_router(run_service: RunService) -> Any:
    router = create_router()

    @router.get("/runs/{run_id}/traces")
    def get_traces(run_id: str, cursor: int = 0, limit: int = 1000) -> dict[str, object]:
        return run_service.get_traces(run_id, cursor=cursor, limit=limit)

    @router.get("/runs/{run_id}/events")
    def get_events(run_id: str, cursor: int = 0, limit: int = 1000) -> dict[str, object]:
        return run_service.get_events(run_id, cursor=cursor, limit=limit)

    @router.get("/runs/{run_id}/status-events")
    def get_status_events(run_id: str) -> dict[str, object]:
        return run_service.get_status_events(run_id)

    @router.get("/runs/{run_id}/stream")
    def get_run_stream(run_id: str, cursor: int = 0, limit: int = 50) -> dict[str, object]:
        return run_service.get_stream(run_id, cursor=cursor, limit=limit)

    return router
