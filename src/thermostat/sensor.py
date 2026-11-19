"""Simulated temperature sensor replaying a fixed reading sequence."""

from collections.abc import Iterable

SENSOR_INTERVAL_SECONDS = 5.0


# @implements REQ-002
class Sensor:
    """Return readings in order, repeating the last value once exhausted."""

    def __init__(self, readings: Iterable[float | None] | None = None) -> None:
        source = [21.0] if readings is None else readings
        self._readings = iter(source)
        self._last: float | None = None

    def read(self) -> float | None:
        """Return the next reading, sticking at the last one when exhausted."""
        try:
            self._last = next(self._readings)
        except StopIteration:
            pass
        return self._last
