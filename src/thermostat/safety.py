"""Safety monitor enforcing over-temperature and missing-sensor fail-safe."""

from .heater import Heater

MAX_SAFE_TEMPERATURE_C = 30.0
MAX_MISSING_CYCLES = 3


# @implements REQ-005
# @implements REQ-006
class SafetyMonitor:
    """Latch fail-safe on unsafe temperature or prolonged missing readings."""

    def __init__(
        self,
        max_temperature_c: float = MAX_SAFE_TEMPERATURE_C,
        max_missing_cycles: int = MAX_MISSING_CYCLES,
    ) -> None:
        self._max_temperature_c = max_temperature_c
        self._max_missing_cycles = max_missing_cycles
        self._fail_safe = False
        self._missing_cycles = 0

    @property
    def fail_safe(self) -> bool:
        return self._fail_safe

    @property
    def missing_cycles(self) -> int:
        return self._missing_cycles

    def observe(self, reading: float | None, heater: Heater) -> bool:
        """Return True when control is allowed, forcing the heater off otherwise."""
        if self._fail_safe:
            heater.turn_off()
            return False
        if reading is None:
            self._missing_cycles += 1
            if self._missing_cycles >= self._max_missing_cycles:
                self._fail_safe = True
                heater.turn_off()
                return False
            return True
        self._missing_cycles = 0
        if reading > self._max_temperature_c:
            self._fail_safe = True
            heater.turn_off()
            return False
        return True

    def reset(self) -> None:
        """Clear the latched fail-safe and the missing-reading counter."""
        self._fail_safe = False
        self._missing_cycles = 0
