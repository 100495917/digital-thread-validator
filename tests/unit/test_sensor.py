"""Unit tests for the simulated temperature sensor."""

from __future__ import annotations

import pytest

from thermostat.sensor import SENSOR_INTERVAL_SECONDS, Sensor


@pytest.mark.req("REQ-002")
def test_sensor_interval_is_five_seconds() -> None:
    assert SENSOR_INTERVAL_SECONDS == 5.0


@pytest.mark.req("REQ-002")
def test_default_sensor_repeatedly_reads_21_degrees() -> None:
    sensor = Sensor()

    assert sensor.read() == 21.0
    assert sensor.read() == 21.0


def test_sensor_returns_readings_in_order() -> None:
    sensor = Sensor([20.0, 21.0, 22.0])

    assert sensor.read() == 20.0
    assert sensor.read() == 21.0
    assert sensor.read() == 22.0


@pytest.mark.req("REQ-002")
def test_sensor_sticks_at_last_reading() -> None:
    sensor = Sensor([20.0, 21.0])

    assert sensor.read() == 20.0
    assert sensor.read() == 21.0
    assert sensor.read() == 21.0
    assert sensor.read() == 21.0


def test_sensor_can_report_missing_reading() -> None:
    sensor = Sensor([None, 22.0])

    assert sensor.read() is None
    assert sensor.read() == 22.0


def test_sensor_accepts_any_iterable() -> None:
    sensor = Sensor(reading for reading in (19.5, 20.5))

    assert sensor.read() == 19.5
    assert sensor.read() == 20.5
    assert sensor.read() == 20.5
