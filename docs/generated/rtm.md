# Requirements traceability matrix

| Req ID | Title | Priority | Model elements | Code | Tests | Last result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| REQ-001 | Temperature setpoint tracking | high | BHV-control-loop; BLK-controller | src/thermostat/controller.py | tests/requirements/test_requirements.py; tests/unit/test_controller.py | pass | complete |
| REQ-002 | Periodic sensor sampling | medium | BLK-sensor; IF-sensor | src/thermostat/sensor.py | tests/requirements/test_requirements.py; tests/unit/test_sensor.py | pass | complete |
| REQ-003 | Heating activation below hysteresis band | medium | BLK-controller; BLK-heater | src/thermostat/controller.py; src/thermostat/heater.py | tests/requirements/test_requirements.py; tests/unit/test_controller.py | pass | complete |
| REQ-004 | Heating deactivation above hysteresis band | medium | BLK-controller; BLK-heater | src/thermostat/controller.py; src/thermostat/heater.py | tests/requirements/test_requirements.py; tests/unit/test_controller.py | pass | complete |
| REQ-005 | Over-temperature shutdown | high | BLK-safety | src/thermostat/safety.py | tests/integration/test_api.py; tests/requirements/test_requirements.py; tests/unit/test_safety.py | pass | complete |
| REQ-006 | Missing-sensor fail-safe | high | BLK-safety | src/thermostat/safety.py | tests/integration/test_api.py; tests/requirements/test_requirements.py; tests/unit/test_safety.py | pass | complete |
| REQ-007 | Setpoint change response time | medium | BLK-controller | src/thermostat/controller.py | tests/requirements/test_requirements.py; tests/unit/test_controller.py | pass | complete |
| REQ-008 | Setpoint range validation | medium | BLK-validator | src/thermostat/validator.py | tests/integration/test_api.py; tests/requirements/test_requirements.py; tests/unit/test_controller.py; tests/unit/test_validator.py | pass | complete |
| REQ-009 | Status REST endpoint | medium | BLK-api; IF-rest | src/thermostat/api.py | tests/integration/test_api.py; tests/requirements/test_requirements.py | pass | complete |
| REQ-010 | Setpoint update endpoint | medium | BLK-api; IF-rest | src/thermostat/api.py | tests/integration/test_api.py; tests/requirements/test_requirements.py | pass | complete |
| REQ-011 | Authenticated setpoint updates | high | BLK-auth | src/thermostat/auth.py | tests/integration/test_api.py; tests/requirements/test_requirements.py; tests/unit/test_auth.py | pass | complete |
| REQ-012 | Token confidentiality in logs | high | BLK-auth | src/thermostat/auth.py | tests/integration/test_api.py; tests/requirements/test_requirements.py; tests/unit/test_auth.py | pass | complete |
| REQ-013 | Status endpoint latency | medium | BLK-api | src/thermostat/api.py | tests/perf/test_status_perf.py; tests/requirements/test_requirements.py | pass | complete |
