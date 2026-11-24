"""Equal-capability user sessions and dependency-light ASGI authentication."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4


AUTH_MODE_ENV = "AI_NATIVE_WORLD_AUTH_MODE"
SESSION_SECRET_ENV = "AI_NATIVE_WORLD_SESSION_SECRET"
SESSION_TTL_ENV = "AI_NATIVE_WORLD_SESSION_TTL_SECONDS"
DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60
LOCAL_USER_ID = "local"

JsonDict = dict[str, Any]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    kind: str = "user"


@dataclass(frozen=True, slots=True)
class AuthConfig:
    mode: str = "disabled"
    secret: bytes = b""
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AuthConfig":
        values = env if env is not None else os.environ
        mode = str(values.get(AUTH_MODE_ENV, "disabled")).strip().lower()
        if mode not in {"disabled", "session"}:
            raise ValueError(f"unsupported {AUTH_MODE_ENV}: {mode}. Expected disabled or session.")
        raw_secret = str(values.get(SESSION_SECRET_ENV, ""))
        if mode == "session" and len(raw_secret.encode("utf-8")) < 32:
            raise ValueError(f"{SESSION_SECRET_ENV} must contain at least 32 bytes in session mode")
        ttl = int(values.get(SESSION_TTL_ENV, DEFAULT_SESSION_TTL_SECONDS) or DEFAULT_SESSION_TTL_SECONDS)
        if ttl <= 0:
            raise ValueError(f"{SESSION_TTL_ENV} must be greater than zero")
        return cls(
            mode=mode,
            secret=raw_secret.encode("utf-8") if raw_secret else secrets.token_bytes(32),
            session_ttl_seconds=ttl,
        )


class AuthenticationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SessionAuthenticator:
    def __init__(self, config: AuthConfig, clock: Clock = time.time) -> None:
        self.config = config
        self.clock = clock

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SessionAuthenticator":
        return cls(AuthConfig.from_env(env))

    def issue_session(self) -> JsonDict:
        issued_at = int(self.clock())
        expires_at = issued_at + self.config.session_ttl_seconds
        user_id = f"user_{uuid4().hex[:20]}"
        payload = {
            "ver": 1,
            "typ": "user_session",
            "sub": user_id,
            "iat": issued_at,
            "exp": expires_at,
        }
        token = self._encode(payload)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "expires_in": self.config.session_ttl_seconds,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }

    def authenticate_header(self, authorization: str | None) -> Principal:
        if self.config.mode == "disabled":
            return Principal(LOCAL_USER_ID, kind="local")
        scheme, separator, token = str(authorization or "").partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("authentication_required")
        payload = self._decode(token.strip())
        return Principal(str(payload["sub"]))

    def _encode(self, payload: JsonDict) -> str:
        encoded_payload = _base64url(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = hmac.new(
            self.config.secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_base64url(signature)}"

    def _decode(self, token: str) -> JsonDict:
        encoded_payload, separator, encoded_signature = token.partition(".")
        if not separator or not encoded_payload or not encoded_signature:
            raise AuthenticationError("invalid_session_token")
        try:
            signature = _unbase64url(encoded_signature)
            expected = hmac.new(
                self.config.secret,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                raise AuthenticationError("invalid_session_token")
            payload = json.loads(_unbase64url(encoded_payload).decode("utf-8"))
        except AuthenticationError:
            raise
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationError("invalid_session_token") from exc
        if not isinstance(payload, dict):
            raise AuthenticationError("invalid_session_token")
        if payload.get("typ") != "user_session" or int(payload.get("ver", 0) or 0) != 1:
            raise AuthenticationError("invalid_session_token")
        subject = str(payload.get("sub", "")).strip()
        if not subject.startswith("user_"):
            raise AuthenticationError("invalid_session_token")
        if int(payload.get("exp", 0) or 0) <= int(self.clock()):
            raise AuthenticationError("session_expired")
        return payload


_principal_context: ContextVar[Principal | None] = ContextVar(
    "ai_native_world_principal",
    default=None,
)


def current_principal() -> Principal:
    return _principal_context.get() or Principal(LOCAL_USER_ID, kind="local")


@contextmanager
def principal_context(user_id: str, kind: str = "user") -> Iterator[Principal]:
    principal = Principal(str(user_id), kind=str(kind))
    token = _principal_context.set(principal)
    try:
        yield principal
    finally:
        _principal_context.reset(token)


class SessionAuthMiddleware:
    """Pure ASGI middleware so FastAPI remains optional at import time."""

    def __init__(self, app: Any, authenticator: SessionAuthenticator) -> None:
        self.app = app
        self.authenticator = authenticator

    async def __call__(self, scope: JsonDict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", ""))
        try:
            if self.authenticator.config.mode == "disabled" or _is_public_route(method, path):
                principal = Principal(LOCAL_USER_ID, kind="local")
            else:
                principal = self.authenticator.authenticate_header(_authorization_header(scope))
        except AuthenticationError as exc:
            await _send_auth_error(send, exc.code)
            return
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["principal"] = principal
        context_token = _principal_context.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal_context.reset(context_token)


def _is_public_route(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return True
    if (method, path) in {
        ("POST", "/api/sessions"),
        ("GET", "/api/scenarios"),
        ("GET", "/api/health"),
    }:
        return True
    return path in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _authorization_header(scope: JsonDict) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1") if isinstance(raw_name, bytes) else str(raw_name)
        if name.lower() != "authorization":
            continue
        return raw_value.decode("latin-1") if isinstance(raw_value, bytes) else str(raw_value)
    return None


async def _send_auth_error(send: Any, code: str) -> None:
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unbase64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
