"""FastAPI application factory.

FastAPI is intentionally optional at import time so repository-level tests can
verify the application service boundary before API dependencies are installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from types import SimpleNamespace
from typing import Any, Mapping

from .auth import SessionAuthenticator, SessionAuthMiddleware
from .repository_config import RepositoryRuntimeConfig, create_run_repository
from .routers.health import build_health_router
from .routers.projections import build_projection_router
from .routers.runs import build_run_router
from .routers.scenarios import build_scenario_router
from .routers.sessions import build_session_router
from .routers.traces import build_trace_router
from .services.run_service import RunService


@dataclass(slots=True)
class RouteSpec:
    method: str
    path: str
    name: str


@dataclass(slots=True)
class ApiAppStub:
    """Small inspection stub used when FastAPI is not installed."""

    title: str
    routes: list[RouteSpec] = field(default_factory=list)
    state: Any = field(default_factory=SimpleNamespace)

    def include_router(self, router: Any, prefix: str = "") -> None:
        for route in getattr(router, "routes", []):
            self.routes.append(
                RouteSpec(
                    method=getattr(route, "method", "GET"),
                    path=f"{prefix}{getattr(route, 'path', '')}",
                    name=getattr(route, "name", ""),
                )
            )


def create_app(environ: Mapping[str, str] | None = None) -> Any:
    env = environ if environ is not None else os.environ
    authenticator = SessionAuthenticator.from_env(env)
    repository_config = RepositoryRuntimeConfig.from_env(env)
    repository = create_run_repository(env)
    worker_mode = str(env.get("AI_NATIVE_WORLD_WORKER_MODE", "embedded")).strip().lower()
    if worker_mode not in {"embedded", "external", "disabled"}:
        raise ValueError(f"unsupported AI_NATIVE_WORLD_WORKER_MODE: {worker_mode}")
    queue = None
    if worker_mode == "embedded":
        try:
            from ai_native_world_worker import InProcessRunQueue
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "AI_NATIVE_WORLD_WORKER_MODE=embedded requires the Worker package. "
                "Start the repository with `python scripts/dev_demo.py` or add "
                "apps/worker/src to PYTHONPATH."
            ) from exc
        else:
            queue = InProcessRunQueue(repository, auto_drain=False, cooperative_ticks=True)
    runtime_ready = queue is not None or worker_mode == "external"
    health: dict[str, object] = {
        "status": "ok" if runtime_ready else "degraded",
        "repository_mode": repository_config.mode,
        "worker_mode": worker_mode,
        "queue_available": queue is not None,
        "runtime_ready": runtime_ready,
    }
    if not runtime_ready:
        health["reason"] = "Worker mode is disabled; queued Runs cannot advance."
    run_service = RunService(
        repository=repository,
        queue=queue,
        external_worker=worker_mode == "external",
    )

    try:
        from fastapi import FastAPI
    except ModuleNotFoundError:
        app: Any = ApiAppStub(title="AI Native World API")
    else:
        app = FastAPI(title="AI Native World API", version="0.1.0")
        app.add_middleware(SessionAuthMiddleware, authenticator=authenticator)

    app.state.authenticator = authenticator
    app.state.auth_mode = authenticator.config.mode
    app.state.repository = repository
    app.state.run_service = run_service
    app.state.run_queue = queue
    app.state.worker_mode = worker_mode
    app.state.runtime_health = health
    app.include_router(build_health_router(health), prefix="/api")
    app.include_router(build_session_router(authenticator), prefix="/api")
    app.include_router(build_scenario_router(run_service), prefix="/api")
    app.include_router(build_run_router(run_service), prefix="/api")
    app.include_router(build_projection_router(run_service), prefix="/api")
    app.include_router(build_trace_router(run_service), prefix="/api")
    return app


app = create_app()
