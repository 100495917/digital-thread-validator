"""API token authentication helpers and middleware for the thermostat REST API."""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

TOKEN_ENV_VAR = "THERMOSTAT_API_TOKEN"
DEFAULT_DEV_TOKEN = "dev-token"

_PROTECTED_METHOD = "PUT"
_PROTECTED_PATH = "/setpoint"
_INVALID_TOKEN_DETAIL = "Invalid or missing API token"


def configured_token() -> str:
    """Return the token from the environment, falling back to the dev token."""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    return token or DEFAULT_DEV_TOKEN


# @implements REQ-011
def is_authorized(authorization: str | None, token: str) -> bool:
    """Validate a ``Bearer <token>`` authorization header in constant time."""
    if not authorization or not token:
        return False
    scheme, separator, presented = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return False
    presented = presented.strip()
    if not presented:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8"))


# @implements REQ-012
def redact(secret: str | None) -> str:
    """Return a fixed placeholder so secrets never reach logs or errors."""
    return "***"


# @implements REQ-011
# @implements REQ-012
class AuthMiddleware(BaseHTTPMiddleware):
    """Require a bearer token for ``PUT /setpoint`` and never log credentials."""

    def __init__(self, app: ASGIApp, token: str | None = None) -> None:
        super().__init__(app)
        self._token = configured_token() if token is None else token

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == _PROTECTED_METHOD and request.url.path.rstrip("/") == _PROTECTED_PATH:
            authorization = request.headers.get("authorization")
            if not is_authorized(authorization, self._token):
                # Deliberately does not log the Authorization header or token.
                return JSONResponse(
                    {"detail": _INVALID_TOKEN_DETAIL},
                    status_code=401,
                )
        return await call_next(request)
