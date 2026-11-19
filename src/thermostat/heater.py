"""Simulated heater actuator with idempotent switching."""


class Heater:
    """Track heater state and count effective switch transitions."""

    # @implements REQ-003
    # @implements REQ-004
    def __init__(self) -> None:
        self.is_on = False
        self.switch_count = 0

    def turn_on(self) -> None:
        """Turn the heater on, counting only an actual state change."""
        if not self.is_on:
            self.is_on = True
            self.switch_count += 1

    def turn_off(self) -> None:
        """Turn the heater off, counting only an actual state change."""
        if self.is_on:
            self.is_on = False
            self.switch_count += 1
