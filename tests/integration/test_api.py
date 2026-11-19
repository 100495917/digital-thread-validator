"""Integration tests for the thermostat REST API."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

TOKEN = "secret"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
STATUS_KEYS = {"temperature", "setpoint", "heating", "fail_safe"}


@pytest.mark.req("REQ-009")
def test_get_status_returns_complete_state(client: TestClient) -> None:
    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == STATUS_KEYS
    assert payload["temperature"] == 20.0
    assert payload["setpoint"] == 21.0
    assert payload["heating"] is True
    assert payload["fail_safe"] is False


@pytest.mark.req("REQ-009")
def test_get_status_does_not_require_token(client: TestClient) -> None:
    response = client.get("/status")

    assert response.status_code == 200


@pytest.mark.req("REQ-010")
def test_put_setpoint_updates_controller(client: TestClient) -> None:
    response = client.put("/setpoint", json={"setpoint": 25.0}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == STATUS_KEYS
    assert payload["setpoint"] == 25.0

    assert client.get("/status").json()["setpoint"] == 25.0


@pytest.mark.req("REQ-008")
@pytest.mark.req("REQ-010")
def test_put_setpoint_out_of_range_returns_422(client: TestClient) -> None:
    response = client.put("/setpoint", json={"setpoint": 4.9}, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert client.get("/status").json()["setpoint"] == 21.0


@pytest.mark.req("REQ-011")
def test_put_setpoint_without_token_is_rejected(client: TestClient) -> None:
    response = client.put("/setpoint", json={"setpoint": 22.0})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API token"
    assert client.get("/status").json()["setpoint"] == 21.0


@pytest.mark.req("REQ-011")
def test_put_setpoint_with_wrong_token_is_rejected(client: TestClient) -> None:
    response = client.put(
        "/setpoint",
        json={"setpoint": 22.0},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API token"


@pytest.mark.req("REQ-011")
def test_put_setpoint_with_basic_auth_is_rejected(client: TestClient) -> None:
    response = client.put(
        "/setpoint",
        json={"setpoint": 22.0},
        headers={"Authorization": f"Basic {TOKEN}"},
    )

    assert response.status_code == 401


@pytest.mark.req("REQ-012")
def test_api_token_is_never_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.put("/setpoint", json={"setpoint": 22.0}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert caplog.records
    assert TOKEN not in caplog.text


@pytest.mark.req("REQ-005")
def test_status_reports_fail_safe_on_over_temperature(
    make_client,
) -> None:
    client = make_client(token=TOKEN, readings=[31.0])

    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["temperature"] == 31.0
    assert payload["fail_safe"] is True
    assert payload["heating"] is False


@pytest.mark.req("REQ-006")
def test_status_enters_fail_safe_after_three_missing_readings(make_client) -> None:
    client = make_client(token=TOKEN, readings=[None])

    assert client.get("/status").json()["fail_safe"] is False
    assert client.get("/status").json()["fail_safe"] is False
    payload = client.get("/status").json()

    assert payload["fail_safe"] is True
    assert payload["heating"] is False
