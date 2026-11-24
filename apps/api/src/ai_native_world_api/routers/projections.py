"""Viewer projection API routes."""

from __future__ import annotations

from typing import Any

from ..router_compat import create_router
from ..services.run_service import RunService


def build_projection_router(run_service: RunService) -> Any:
    router = create_router()

    @router.get("/runs/{run_id}/projection")
    def get_projection(run_id: str) -> dict[str, object]:
        return run_service.get_projection(run_id)

    @router.post("/runs/{run_id}/presentation/consume")
    def consume_thought_schedules(
        run_id: str, request: dict[str, object]
    ) -> dict[str, object]:
        raw = request.get("schedule_sequences", [])
        sequences = [int(value) for value in raw] if isinstance(raw, list) else []
        raw_occurrences = request.get("occurrence_ids", [])
        occurrence_ids = (
            [str(value) for value in raw_occurrences]
            if isinstance(raw_occurrences, list)
            else []
        )
        return run_service.consume_thought_schedules(
            run_id, sequences, occurrence_ids
        )

    @router.get("/runs/{run_id}/timeline")
    def get_timeline(run_id: str, cursor: int = 0, limit: int = 50) -> dict[str, object]:
        return run_service.get_timeline(run_id, cursor=cursor, limit=limit)

    return router
