"""Performance test for the GET /status endpoint."""

from __future__ import annotations

import math
from time import perf_counter

import pytest
from fastapi.testclient import TestClient

REQUESTS = 100
P95_BUDGET_SECONDS = 0.100


@pytest.mark.req("REQ-013")
@pytest.mark.perf
def test_status_p95_under_100_ms(client: TestClient) -> None:
    client.get("/status")  # warm up route resolution

    durations = []
    for _ in range(REQUESTS):
        start = perf_counter()
        response = client.get("/status")
        durations.append(perf_counter() - start)
        assert response.status_code == 200

    durations.sort()
    p95 = durations[math.ceil(0.95 * REQUESTS) - 1]

    assert p95 < P95_BUDGET_SECONDS
