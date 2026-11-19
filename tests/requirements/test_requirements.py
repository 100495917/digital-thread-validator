"""Requirement-based tests: one test per REQ-001 ... REQ-013."""

from __future__ import annotations

import logging
import math
from time import perf_counter

import pytest
from fastapi.testclient import TestClient

from thermostat.controller import TemperatureController
from thermostat.heater import Heater
from thermostat.safety import SafetyMonitor
from thermostat.sensor import SENSOR_INTERVAL_SECONDS, Sensor
from thermostat.validator import validate_setpoint

TOKEN = "secret"
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.req("REQ-001")
def test_req_001_temperature_is_held_within_deadband(
    controller: TemperatureController,
) -> None:
    assert controller.update(20.4) is True
    assert controller.update(21.0) is True
    assert controller.update(21.4) is True
    assert controller.update(21.5) is False
    assert controller.update(20.5) is False


@pytest.mark.req("REQ-002")
def test_req_002_sensor_is_read_every_five_seconds() -> None:
    sensor = Sensor([20.0, 21.0, 22.0])

    assert SENSOR_INTERVAL_SECONDS == 5.0
    assert sensor.read() == 20.0
    assert sensor.read() == 21.0
    assert sensor.read() == 22.0


@pytest.mark.req("REQ-003")
def test_req_003_heating_activates_below_setpoint_minus_half(
    controller: TemperatureController, heater: Heater
) -> None:
    assert controller.update(20.4) is True
    assert heater.is_on is True


@pytest.mark.req("REQ-004")
def test_req_004_heating_deactivates_at_setpoint_plus_half(
    controller: TemperatureController, heater: Heater
) -> None:
    controller.update(20.0)
    assert controller.update(21.5) is False
    assert heater.is_on is False


@pytest.mark.req("REQ-005")
def test_req_005_heating_is_forced_off_above_30_degrees() -> None:
    heater = Heater()
    heater.turn_on()
    monitor = SafetyMonitor()

    assert monitor.observe(30.1, heater) is False
    assert monitor.fail_safe is True
    assert heater.is_on is False


@pytest.mark.req("REQ-006")
def test_req_006_three_missing_readings_enter_fail_safe() -> None:
    heater = Heater()
    heater.turn_on()
    monitor = SafetyMonitor()

    assert monitor.observe(None, heater) is True
    assert monitor.observe(None, heater) is True
    assert monitor.observe(None, heater) is False
    assert monitor.fail_safe is True
    assert heater.is_on is False


@pytest.mark.req("REQ-007")
def test_req_007_setpoint_change_takes_effect_immediately(
    controller: TemperatureController,
) -> None:
    controller.set_setpoint(24.0)

    assert controller.setpoint == 24.0
    assert controller.update(23.4) is True
    assert controller.update(24.5) is False


@pytest.mark.req("REQ-008")
@pytest.mark.parametrize("value", [5.0, 30.0])
def test_req_008_inclusive_setpoint_bounds_are_accepted(value: float) -> None:
    assert validate_setpoint(value) is None


@pytest.mark.req("REQ-008")
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(4.9, id="below-min"),
        pytest.param(30.1, id="above-max"),
        pytest.param(math.nan, id="nan"),
    ],
)
def test_req_008_invalid_setpoints_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        validate_setpoint(value)


@pytest.mark.req("REQ-009")
def test_req_009_get_status_exposes_current_state(client: TestClient) -> None:
    response = client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"temperature", "setpoint", "heating", "fail_safe"}
    assert payload["temperature"] == 20.0
    assert payload["setpoint"] == 21.0
    assert payload["heating"] is True
    assert payload["fail_safe"] is False


@pytest.mark.req("REQ-010")
def test_req_010_put_setpoint_accepts_updates(client: TestClient) -> None:
    response = client.put("/setpoint", json={"setpoint": 24.0}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["setpoint"] == 24.0
    assert client.get("/status").json()["setpoint"] == 24.0


@pytest.mark.req("REQ-011")
def test_req_011_put_setpoint_requires_api_token(client: TestClient) -> None:
    response = client.put("/setpoint", json={"setpoint": 24.0})

    assert response.status_code == 401
    assert client.get("/status").json()["setpoint"] == 21.0


@pytest.mark.req("REQ-012")
def test_req_012_api_token_is_not_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.put("/setpoint", json={"setpoint": 24.0}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert caplog.records
    assert TOKEN not in caplog.text


@pytest.mark.req("REQ-013")
def test_req_013_get_status_responds_under_100_ms(client: TestClient) -> None:
    client.get("/status")  # warm up import/route resolution

    durations = []
    for _ in range(25):
        start = perf_counter()
        response = client.get("/status")
        durations.append(perf_counter() - start)
        assert response.status_code == 200

    durations.sort()
    p95 = durations[math.ceil(0.95 * len(durations)) - 1]
    assert p95 < 0.100
