"""Black-box smoke checks for the deployed Smart Thermostat API.

The checks use only the standard library so they can run from the staging
workflow without installing the project's development dependencies.  Every
helper returns a plain dictionary; failures are reported rather than raised so
callers can aggregate the results and exit non-zero once.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 5.0
PERFORMANCE_THRESHOLD_SECONDS = 0.100
VALID_SETPOINT = 21.0
LOW_SETPOINT = 3.0
HIGH_SETPOINT = 31.0


def _now() -> float:
    """Return a monotonic timestamp; wrapped for deterministic tests."""
    return time.perf_counter()


def _request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Perform one HTTP request and return its status and decoded body.

    HTTP error responses are treated as ordinary responses so expected 401 and
    422 status codes can be asserted.  Network failures produce ``status=None``
    and an ``error`` message instead of raising.
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        response = urllib.request.urlopen(request, timeout=timeout)
        try:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            body = response.read()
        finally:
            response.close()
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read() if exc.fp is not None else b""
        except (OSError, ValueError, TypeError, KeyError):  # pragma: no cover - defensive
            body = b""
        finally:
            exc.close()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"status": None, "body": None, "error": str(exc)}

    try:
        decoded = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = None
    return {"status": status, "body": decoded, "error": None}


def _result(name: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    """Build a consistent check result dictionary."""
    result: dict[str, Any] = {
        "name": name,
        "status": "pass" if passed else "fail",
        "detail": detail,
    }
    result.update(extra)
    return result


def check_status(base_url: str) -> dict[str, Any]:
    """Verify ``GET /status`` answers with HTTP 200 and a JSON object."""
    response = _request(f"{base_url.rstrip('/')}/status")
    status = response["status"]
    passed = status == 200 and isinstance(response["body"], dict)
    detail = (
        "status endpoint returned 200"
        if passed
        else (f"expected HTTP 200 with JSON object, got {status!r}")
    )
    return _result("status", passed, detail, status_code=status, error=response["error"])


def check_auth(base_url: str) -> dict[str, Any]:
    """Verify an unauthenticated ``PUT /setpoint`` is rejected with 401."""
    response = _request(
        f"{base_url.rstrip('/')}/setpoint",
        method="PUT",
        payload={"setpoint": VALID_SETPOINT},
    )
    status = response["status"]
    passed = status == 401
    detail = (
        "unauthenticated setpoint update rejected"
        if passed
        else (f"expected HTTP 401 without a token, got {status!r}")
    )
    return _result("auth", passed, detail, status_code=status, error=response["error"])


def check_setpoint_range(base_url: str, token: str) -> dict[str, Any]:
    """Verify accepted setpoints succeed and out-of-range values fail with 422."""
    url = f"{base_url.rstrip('/')}/setpoint"
    cases: list[dict[str, Any]] = []

    for label, value, expected in (
        ("valid", VALID_SETPOINT, 200),
        ("below_minimum", LOW_SETPOINT, 422),
        ("above_maximum", HIGH_SETPOINT, 422),
    ):
        response = _request(url, method="PUT", payload={"setpoint": value}, token=token)
        status = response["status"]
        cases.append(
            {
                "case": label,
                "setpoint": value,
                "expected_status": expected,
                "status_code": status,
                "error": response["error"],
            }
        )

    failures = [case for case in cases if case["status_code"] != case["expected_status"]]
    passed = not failures
    if passed:
        detail = "setpoint range validation behaves as specified"
    else:
        detail = "unexpected status for " + ", ".join(str(case["case"]) for case in failures)
    return _result("setpoint_range", passed, detail, cases=cases)


def _percentile(values: list[float], percentile: float) -> float:
    """Return the nearest-rank percentile of a non-empty list of values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def check_performance(base_url: str, requests: int = 100) -> dict[str, Any]:
    """Verify the 95th percentile ``GET /status`` latency is under 100 ms."""
    url = f"{base_url.rstrip('/')}/status"
    durations: list[float] = []
    failures = 0
    for _ in range(max(1, int(requests))):
        started = _now()
        response = _request(url)
        finished = _now()
        durations.append(max(0.0, finished - started))
        if response["status"] != 200:
            failures += 1

    p95 = _percentile(durations, 0.95)
    passed = failures == 0 and p95 < PERFORMANCE_THRESHOLD_SECONDS
    if passed:
        detail = f"p95 latency {p95 * 1000:.1f} ms is under 100 ms"
    elif failures:
        detail = f"{failures} of {len(durations)} requests failed"
    else:
        detail = f"p95 latency {p95 * 1000:.1f} ms is not under 100 ms"
    return _result(
        "performance",
        passed,
        detail,
        requests=len(durations),
        failures=failures,
        p95_ms=round(p95 * 1000.0, 3),
        threshold_ms=PERFORMANCE_THRESHOLD_SECONDS * 1000.0,
    )


def run_smoke(base_url: str, token: str) -> dict[str, Any]:
    """Run every smoke check and summarise the aggregate status."""
    checks: list[dict[str, Any]] = [
        check_status(base_url),
        check_auth(base_url),
        check_setpoint_range(base_url, token),
        check_performance(base_url),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {"base_url": base_url, "status": status, "checks": checks}
