"""Unit tests for the safety monitor."""

from __future__ import annotations

import pytest

from thermostat.heater import Heater
from thermostat.safety import MAX_MISSING_CYCLES, MAX_SAFE_TEMPERATURE_C, SafetyMonitor


def test_safety_constants() -> None:
    assert MAX_SAFE_TEMPERATURE_C == 30.0
    assert MAX_MISSING_CYCLES == 3


def test_default_monitor_is_not_in_fail_safe() -> None:
    monitor = SafetyMonitor()

    assert monitor.fail_safe is False
    assert monitor.missing_cycles == 0


@pytest.mark.req("REQ-005")
def test_over_temperature_latches_fail_safe_and_turns_heater_off(heater: Heater) -> None:
    heater.turn_on()
    monitor = SafetyMonitor()

    assert monitor.observe(30.1, heater) is False
    assert monitor.fail_safe is True
    assert heater.is_on is False


@pytest.mark.req("REQ-005")
def test_exactly_max_temperature_is_allowed() -> None:
    heater = Heater()
    monitor = SafetyMonitor()

    assert monitor.observe(30.0, heater) is True
    assert monitor.fail_safe is False


@pytest.mark.req("REQ-005")
def test_over_temperature_latch_survives_normal_readings(heater: Heater) -> None:
    monitor = SafetyMonitor()
    monitor.observe(31.0, heater)

    assert monitor.observe(21.0, heater) is False
    assert monitor.fail_safe is True


@pytest.mark.req("REQ-006")
def test_two_missing_readings_do_not_trigger_fail_safe(heater: Heater) -> None:
    monitor = SafetyMonitor()

    assert monitor.observe(None, heater) is True
    assert monitor.observe(None, heater) is True
    assert monitor.missing_cycles == 2
    assert monitor.fail_safe is False


@pytest.mark.req("REQ-006")
def test_three_missing_readings_latch_fail_safe_and_turn_heater_off(
    heater: Heater,
) -> None:
    heater.turn_on()
    monitor = SafetyMonitor()

    monitor.observe(None, heater)
    monitor.observe(None, heater)
    assert monitor.observe(None, heater) is False

    assert monitor.missing_cycles == 3
    assert monitor.fail_safe is True
    assert heater.is_on is False


@pytest.mark.req("REQ-006")
def test_valid_reading_resets_missing_counter(heater: Heater) -> None:
    monitor = SafetyMonitor()
    monitor.observe(None, heater)
    monitor.observe(None, heater)

    assert monitor.observe(21.0, heater) is True
    assert monitor.missing_cycles == 0
    assert monitor.fail_safe is False


@pytest.mark.req("REQ-005")
@pytest.mark.req("REQ-006")
def test_reset_clears_latched_fail_safe(heater: Heater) -> None:
    monitor = SafetyMonitor()
    monitor.observe(31.0, heater)
    assert monitor.fail_safe is True

    monitor.reset()

    assert monitor.fail_safe is False
    assert monitor.observe(21.0, heater) is True


@pytest.mark.req("REQ-006")
def test_reset_clears_missing_reading_fail_safe(heater: Heater) -> None:
    monitor = SafetyMonitor()
    for _ in range(MAX_MISSING_CYCLES):
        monitor.observe(None, heater)
    assert monitor.fail_safe is True

    monitor.reset()

    assert monitor.fail_safe is False
    assert monitor.observe(21.0, heater) is True
