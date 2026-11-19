"""Shared fixtures for the Smart Thermostat test suite."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest
from fastapi.testclient import TestClient

from thermostat.api import create_app
from thermostat.controller import TemperatureController
from thermostat.heater import Heater
from thermostat.sensor import Sensor


@pytest.fixture
def heater() -> Heater:
    """A fresh heater, switched off."""
    return Heater()


@pytest.fixture
def controller(heater: Heater) -> TemperatureController:
    """A controller with the default 21.0 degree setpoint."""
    return TemperatureController(heater)


@pytest.fixture
def make_client() -> Callable[..., TestClient]:
    """Factory building a TestClient with a chosen token and sensor readings."""

    def _make_client(
        token: str | None = "secret",
        readings: Iterable[float | None] | None = None,
    ) -> TestClient:
        return TestClient(create_app(token=token, sensor=Sensor(readings)))

    return _make_client


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    """API client with the shared test token and a single 20.0 degree reading."""
    return make_client(token="secret", readings=[20.0])
