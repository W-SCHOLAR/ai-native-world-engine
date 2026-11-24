"""Run API routes."""

from __future__ import annotations

from typing import Any

from ..router_compat import create_router
from ..services.run_service import RunService


def build_run_router(run_service: RunService) -> Any:
    router = create_router()

    @router.get("/runs")
    def list_runs() -> list[dict[str, object]]:
        return run_service.list_runs()

    @router.post("/runs")
    def create_run(
        scenario: str = "seed",
        seed: int = 7,
        ticks: int = 3,
        request: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = request if isinstance(request, dict) else {}
        resolved_scenario = str(payload.get("scenario", scenario))
        resolved_seed = int(payload.get("seed", seed) or seed)
        resolved_ticks = int(payload.get("ticks", ticks) or ticks)
        runtime_provider = payload.get("runtime_provider")
        require_cognition_ready = bool(
            payload.get("require_cognition_ready", False)
        )
        provider_config = runtime_provider if isinstance(runtime_provider, dict) else None
        live_provider = bool(
            provider_config
            and str(provider_config.get("mode", "deterministic")) != "deterministic"
        )
        if (
            resolved_ticks <= 5
            and not live_provider
            and not require_cognition_ready
        ):
            return run_service.create_sync_run(
                scenario=resolved_scenario,
                seed=resolved_seed,
                ticks=resolved_ticks,
                runtime_provider=provider_config,
            )
        return run_service.enqueue_run(
            scenario=resolved_scenario,
            seed=resolved_seed,
            ticks=resolved_ticks,
            runtime_provider=provider_config,
            require_cognition_ready=require_cognition_ready,
        )

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        return run_service.get_run(run_id)

    @router.get("/runs/{run_id}/result")
    def get_run_result(run_id: str) -> dict[str, object]:
        return run_service.get_final_result(run_id)

    @router.post("/runs/{run_id}/interventions")
    def add_intervention(run_id: str, intervention: dict[str, object]) -> dict[str, object]:
        return run_service.add_intervention(run_id, intervention)

    @router.post("/runs/{run_id}/sovereign-intents")
    def add_sovereign_intent(run_id: str, request: dict[str, object]) -> dict[str, object]:
        return run_service.add_sovereign_intent(run_id, request)

    @router.post("/runs/{run_id}/control")
    def control_run(run_id: str, request: dict[str, object]) -> dict[str, object]:
        return run_service.control_run(
            run_id,
            command=str(request.get("command", "")),
            reason=str(request.get("reason", "")),
            actor_id=str(request.get("actor_id", "operator")),
        )

    @router.post("/runs/{run_id}/retry")
    def retry_run(run_id: str, request: dict[str, object]) -> dict[str, object]:
        runtime_provider = request.get("runtime_provider")
        return run_service.retry_run(
            run_id,
            runtime_provider=(
                dict(runtime_provider)
                if isinstance(runtime_provider, dict)
                else None
            ),
        )

    @router.post("/runs/{run_id}/advance")
    def advance_run(run_id: str) -> dict[str, object]:
        return run_service.advance_run(run_id)

    return router
