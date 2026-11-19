"""Setpoint range validation."""

import math

MIN_SETPOINT_C = 5.0
MAX_SETPOINT_C = 30.0


# @implements REQ-008
def validate_setpoint(value: float) -> None:
    """Raise ``ValueError`` unless the setpoint is a finite in-range number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        # The public contract is ValueError for every invalid setpoint, including type errors.
        raise ValueError("Setpoint must be a number")  # noqa: TRY004
    if not math.isfinite(value):
        raise ValueError("Setpoint must be finite")
    if not MIN_SETPOINT_C <= value <= MAX_SETPOINT_C:
        raise ValueError(f"Setpoint must be between {MIN_SETPOINT_C} and {MAX_SETPOINT_C} °C")
