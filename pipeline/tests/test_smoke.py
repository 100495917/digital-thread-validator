"""Tests for the standard-library smoke checks.

All HTTP interactions are replaced with in-memory fakes; the tests never open
sockets or touch the network.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from mbse import smoke


class FakeResponse:
    """Minimal ``urlopen`` response double."""

    def __init__(self, status: int, payload: bytes = b"{}") -> None:
        self.status = status
        self._payload = payload
        self.closed = False

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        self.closed = True


def _http_error(code: int, url: str = "http://api.test/setpoint") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(b"{}"))


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(smoke.urllib.request, "urlopen", handler)


def test_check_status_passes_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(
        monkeypatch,
        lambda request, timeout=None: FakeResponse(200, b'{"temperature": 21.0}'),
    )

    result = smoke.check_status("http://api.test")

    assert result["name"] == "status"
    assert result["status"] == "pass"
    assert result["status_code"] == 200


def test_check_status_fails_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, lambda request, timeout=None: FakeResponse(500))

    result = smoke.check_status("http://api.test")

    assert result["status"] == "fail"
    assert result["status_code"] == 500


def test_check_auth_passes_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_unauthorized(request, timeout=None):
        raise _http_error(401)

    _patch_urlopen(monkeypatch, raise_unauthorized)

    result = smoke.check_auth("http://api.test")

    assert result["status"] == "pass"
    assert result["status_code"] == 401


def test_check_auth_fails_without_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, lambda request, timeout=None: FakeResponse(200))

    result = smoke.check_auth("http://api.test")

    assert result["status"] == "fail"
    assert result["status_code"] == 200


def test_check_setpoint_range_uses_token_and_expected_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str | None, float]] = []

    def handler(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        seen.append((request.get_method(), request.get_header("Authorization"), body["setpoint"]))
        value = body["setpoint"]
        status = 200 if 5.0 <= value <= 30.0 else 422
        return FakeResponse(status)

    _patch_urlopen(monkeypatch, handler)

    result = smoke.check_setpoint_range("http://api.test", "secret-token")

    assert result["status"] == "pass"
    assert [case["status_code"] for case in result["cases"]] == [200, 422, 422]
    assert seen == [
        ("PUT", "Bearer secret-token", 21.0),
        ("PUT", "Bearer secret-token", 3.0),
        ("PUT", "Bearer secret-token", 31.0),
    ]


def test_check_setpoint_range_fails_when_range_is_not_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_urlopen(monkeypatch, lambda request, timeout=None: FakeResponse(200))

    result = smoke.check_setpoint_range("http://api.test", "secret-token")

    assert result["status"] == "fail"
    assert [case["case"] for case in result["cases"]] == [
        "valid",
        "below_minimum",
        "above_maximum",
    ]


def _clock(values: list[float]):
    iterator = iter(values)
    return lambda: next(iterator)


def test_check_performance_passes_under_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, lambda request, timeout=None: FakeResponse(200))
    timestamps: list[float] = []
    for index in range(100):
        timestamps.extend([float(index), float(index) + 0.010])
    monkeypatch.setattr(smoke, "_now", _clock(timestamps))

    result = smoke.check_performance("http://api.test", requests=100)

    assert result["status"] == "pass"
    assert result["p95_ms"] == 10.0
    assert result["requests"] == 100
    assert result["failures"] == 0


def test_check_performance_fails_on_high_p95(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, lambda request, timeout=None: FakeResponse(200))
    timestamps: list[float] = []
    for index in range(100):
        duration = 0.200 if index < 6 else 0.010
        timestamps.extend([float(index), float(index) + duration])
    monkeypatch.setattr(smoke, "_now", _clock(timestamps))

    result = smoke.check_performance("http://api.test", requests=100)

    assert result["status"] == "fail"
    assert result["p95_ms"] == pytest.approx(200.0)


def test_check_performance_fails_when_any_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_urlopen(monkeypatch, lambda request, timeout=None: FakeResponse(503))
    timestamps: list[float] = []
    for index in range(4):
        timestamps.extend([float(index), float(index) + 0.001])
    monkeypatch.setattr(smoke, "_now", _clock(timestamps))

    result = smoke.check_performance("http://api.test", requests=4)

    assert result["status"] == "fail"
    assert result["failures"] == 4


def test_percentile_uses_nearest_rank() -> None:
    values = [0.01, 0.02, 0.03, 0.04, 0.05]

    assert smoke._percentile(values, 0.95) == 0.05
    assert smoke._percentile([], 0.95) == 0.0


def test_run_smoke_passes_when_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "check_status", lambda base: {"name": "status", "status": "pass"})
    monkeypatch.setattr(smoke, "check_auth", lambda base: {"name": "auth", "status": "pass"})
    monkeypatch.setattr(
        smoke,
        "check_setpoint_range",
        lambda base, token: {"name": "setpoint_range", "status": "pass"},
    )
    monkeypatch.setattr(
        smoke,
        "check_performance",
        lambda base: {"name": "performance", "status": "pass"},
    )

    result = smoke.run_smoke("http://api.test", "token")

    assert result["status"] == "pass"
    assert [check["name"] for check in result["checks"]] == [
        "status",
        "auth",
        "setpoint_range",
        "performance",
    ]
    assert result["base_url"] == "http://api.test"


def test_run_smoke_fails_when_any_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "check_status", lambda base: {"name": "status", "status": "pass"})
    monkeypatch.setattr(smoke, "check_auth", lambda base: {"name": "auth", "status": "fail"})
    monkeypatch.setattr(
        smoke,
        "check_setpoint_range",
        lambda base, token: {"name": "setpoint_range", "status": "pass"},
    )
    monkeypatch.setattr(
        smoke,
        "check_performance",
        lambda base: {"name": "performance", "status": "fail"},
    )

    result = smoke.run_smoke("http://api.test", "token")

    assert result["status"] == "fail"
    assert [check["status"] for check in result["checks"]] == ["pass", "fail", "pass", "fail"]
