"""Unit tests for setpoint range validation."""

from __future__ import annotations

import math

import pytest

from thermostat.validator import MAX_SETPOINT_C, MIN_SETPOINT_C, validate_setpoint


def test_setpoint_bounds() -> None:
    assert MIN_SETPOINT_C == 5.0
    assert MAX_SETPOINT_C == 30.0


@pytest.mark.req("REQ-008")
@pytest.mark.parametrize("value", [5.0, 21.0, 30.0])
def test_inclusive_bounds_are_accepted(value: float) -> None:
    assert validate_setpoint(value) is None


@pytest.mark.req("REQ-008")
@pytest.mark.parametrize("value", [4.9, 4.999, 30.1, 30.001])
def test_out_of_range_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        validate_setpoint(value)


@pytest.mark.req("REQ-008")
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="inf"),
        pytest.param(-math.inf, id="negative-inf"),
    ],
)
def test_non_finite_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        validate_setpoint(value)


@pytest.mark.req("REQ-008")
@pytest.mark.parametrize(
    "value",
    [pytest.param(True, id="true"), pytest.param(False, id="false")],
)
def test_boolean_values_are_rejected(value: bool) -> None:
    with pytest.raises(ValueError):
        validate_setpoint(value)
