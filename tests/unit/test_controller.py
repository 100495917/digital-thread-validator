"""Unit tests for the hysteresis temperature controller."""

from __future__ import annotations

import math

import pytest

from thermostat.controller import HYSTERESIS_DELTA_C, TemperatureController
from thermostat.heater import Heater


def test_hysteresis_delta_constant() -> None:
    assert HYSTERESIS_DELTA_C == 0.5


def test_default_setpoint_is_21(controller: TemperatureController) -> None:
    assert controller.setpoint == 21.0


@pytest.mark.req("REQ-003")
def test_heating_activates_below_setpoint_minus_delta(
    controller: TemperatureController, heater: Heater
) -> None:
    assert controller.update(20.4) is True
    assert controller.heating is True
    assert heater.is_on is True


@pytest.mark.req("REQ-003")
def test_heating_not_activated_exactly_at_lower_threshold(
    controller: TemperatureController, heater: Heater
) -> None:
    assert controller.update(20.5) is False
    assert controller.heating is False
    assert heater.is_on is False


@pytest.mark.req("REQ-004")
def test_heating_deactivates_at_upper_threshold(
    controller: TemperatureController, heater: Heater
) -> None:
    assert controller.update(20.0) is True
    assert controller.update(21.5) is False
    assert controller.heating is False
    assert heater.is_on is False


@pytest.mark.req("REQ-004")
def test_heating_stays_on_just_below_upper_threshold(
    controller: TemperatureController,
) -> None:
    controller.update(20.0)
    assert controller.update(21.499) is True
    assert controller.heating is True


@pytest.mark.req("REQ-001")
def test_heating_stays_on_inside_deadband(controller: TemperatureController) -> None:
    controller.update(20.0)
    assert controller.update(21.0) is True
    assert controller.update(21.4) is True


@pytest.mark.req("REQ-001")
def test_heating_stays_off_inside_deadband(controller: TemperatureController) -> None:
    assert controller.update(21.0) is False
    assert controller.update(20.6) is False
    assert controller.heating is False


def test_none_reading_leaves_heating_off(controller: TemperatureController) -> None:
    assert controller.update(None) is False
    assert controller.heating is False


def test_none_reading_leaves_heating_on(controller: TemperatureController) -> None:
    controller.update(20.0)
    assert controller.update(None) is True
    assert controller.heating is True


@pytest.mark.req("REQ-007")
def test_setpoint_change_applies_immediately(
    controller: TemperatureController, heater: Heater
) -> None:
    controller.set_setpoint(25.0)

    assert controller.setpoint == 25.0
    assert controller.update(24.4) is True
    assert heater.is_on is True
    assert controller.update(25.5) is False
    assert heater.is_on is False


def test_custom_setpoint_is_used(heater: Heater) -> None:
    controller = TemperatureController(heater, setpoint=18.0)

    assert controller.setpoint == 18.0
    assert controller.update(17.4) is True
    assert controller.update(18.5) is False


@pytest.mark.req("REQ-007")
@pytest.mark.req("REQ-008")
@pytest.mark.parametrize(
    "invalid_setpoint",
    [
        pytest.param(4.9, id="below-min"),
        pytest.param(30.1, id="above-max"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="inf"),
    ],
)
def test_invalid_setpoint_raises_and_is_not_applied(
    controller: TemperatureController, invalid_setpoint: float
) -> None:
    with pytest.raises(ValueError):
        controller.set_setpoint(invalid_setpoint)

    assert controller.setpoint == 21.0
