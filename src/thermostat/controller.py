"""Hysteresis temperature controller."""

from .heater import Heater
from .validator import validate_setpoint

HYSTERESIS_DELTA_C = 0.5


# @implements REQ-001
# @implements REQ-003
# @implements REQ-004
# @implements REQ-007
class TemperatureController:
    """Drive the heater with hysteresis around a validated setpoint."""

    def __init__(self, heater: Heater, setpoint: float = 21.0) -> None:
        self._heater = heater
        self._setpoint = setpoint

    @property
    def setpoint(self) -> float:
        return self._setpoint

    @property
    def heating(self) -> bool:
        return self._heater.is_on

    def set_setpoint(self, value: float) -> None:
        """Validate and apply a new setpoint immediately."""
        validate_setpoint(value)
        self._setpoint = float(value)

    def update(self, measured: float | None) -> bool:
        """Apply hysteresis and return the resulting heating state."""
        if measured is not None:
            if measured < self._setpoint - HYSTERESIS_DELTA_C:
                self._heater.turn_on()
            elif measured >= self._setpoint + HYSTERESIS_DELTA_C:
                self._heater.turn_off()
        return self._heater.is_on
