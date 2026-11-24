"""Tiny router compatibility layer for optional FastAPI imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class Route:
    method: str
    path: str
    name: str
    handler: Callable[..., Any]


class RouterStub:
    def __init__(self) -> None:
        self.routes: list[Route] = []

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._add("GET", path)

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._add("POST", path)

    def _add(self, method: str, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(Route(method=method, path=path, name=handler.__name__, handler=handler))
            return handler

        return decorator


def create_router() -> Any:
    try:
        from fastapi import APIRouter
    except ModuleNotFoundError:
        return RouterStub()
    return APIRouter()
