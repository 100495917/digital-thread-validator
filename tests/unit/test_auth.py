"""Unit tests for API token authentication helpers."""

from __future__ import annotations

import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from thermostat.auth import (
    DEFAULT_DEV_TOKEN,
    TOKEN_ENV_VAR,
    AuthMiddleware,
    configured_token,
    is_authorized,
    redact,
)


def test_auth_constants() -> None:
    assert TOKEN_ENV_VAR == "THERMOSTAT_API_TOKEN"
    assert DEFAULT_DEV_TOKEN == "dev-token"


def test_configured_token_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "env-secret")

    assert configured_token() == "env-secret"


def test_configured_token_falls_back_to_dev_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    assert configured_token() == DEFAULT_DEV_TOKEN


@pytest.mark.req("REQ-011")
def test_correct_bearer_token_is_authorized() -> None:
    assert is_authorized("Bearer secret-token", "secret-token") is True


@pytest.mark.req("REQ-011")
@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("Bearer wrong-token", id="wrong-token"),
        pytest.param("Basic secret-token", id="basic-scheme"),
        pytest.param("secret-token", id="no-scheme"),
        pytest.param("Bearer", id="scheme-only"),
        pytest.param("Bearer secret-token-extra", id="token-prefix"),
    ],
)
def test_bad_authorization_is_rejected(authorization: str | None) -> None:
    assert is_authorized(authorization, "secret-token") is False


@pytest.mark.req("REQ-012")
def test_redact_hides_secret() -> None:
    assert redact("secret-token") == "***"
    assert redact("") == "***"


def test_middleware_is_based_on_starlette() -> None:
    assert issubclass(AuthMiddleware, BaseHTTPMiddleware)
