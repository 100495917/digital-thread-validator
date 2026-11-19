"""FastAPI application exposing the thermostat status and setpoint endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from thermostat.auth import AuthMiddleware
from thermostat.controller import TemperatureController
from thermostat.heater import Heater
from thermostat.safety import SafetyMonitor
from thermostat.sensor import Sensor

logger = logging.getLogger(__name__)


class SetpointUpdate(BaseModel):
    """Request body for a setpoint change."""

    setpoint: float


def _log_request(method: str, path: str, status_code: int) -> None:
    """Log only the request method, path, and resulting status code."""
    logger.info("%s %s -> %d", method, path, status_code)


def create_app(token: str | None = None, sensor: Sensor | None = None) -> FastAPI:
    """Build the thermostat REST application with its in-memory devices."""
    temperature_sensor = Sensor() if sensor is None else sensor
    heater = Heater()
    safety = SafetyMonitor()
    controller = TemperatureController(heater)

    app = FastAPI(title="Smart Thermostat Controller", version="0.1.0")
    app.add_middleware(AuthMiddleware, token=token)

    def collect_status() -> dict[str, Any]:
        measured = temperature_sensor.read()
        if safety.observe(measured, heater) and measured is not None:
            controller.update(measured)
        return {
            "temperature": measured,
            "setpoint": controller.setpoint,
            "heating": controller.heating,
            "fail_safe": safety.fail_safe,
        }

    # @implements REQ-009
    # @implements REQ-013
    @app.get("/status")
    async def get_status(request: Request) -> dict[str, Any]:
        """Report the current temperature, setpoint, heating, and fail-safe state."""
        payload = collect_status()
        _log_request(request.method, request.url.path, 200)
        return payload

    # @implements REQ-010
    @app.put("/setpoint")
    async def put_setpoint(update: SetpointUpdate, request: Request) -> dict[str, Any]:
        """Validate and apply a new setpoint, then report the updated state."""
        try:
            controller.set_setpoint(update.setpoint)
        except ValueError as exc:
            _log_request(request.method, request.url.path, 422)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = collect_status()
        _log_request(request.method, request.url.path, 200)
        return payload

    return app
