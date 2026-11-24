"""Anonymous user-session routes."""

from __future__ import annotations

from typing import Any

from ..auth import SessionAuthenticator
from ..router_compat import create_router


def build_session_router(authenticator: SessionAuthenticator) -> Any:
    router = create_router()

    @router.post("/sessions")
    def create_session() -> dict[str, object]:
        return authenticator.issue_session()

    return router

