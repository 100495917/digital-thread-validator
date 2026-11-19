# Requirements

| ID | Title | Type | Priority | Owner | Verification | Status | Text |
| --- | --- | --- | --- | --- | --- | --- | --- |
| REQ-001 | Temperature setpoint tracking | functional | high | team-control | test | approved | The system shall maintain the room temperature within ±1 °C of the setpoint. |
| REQ-002 | Periodic sensor sampling | interface | medium | team-control | test | approved | The system shall read the temperature from the sensor every 5 seconds. |
| REQ-003 | Heating activation below hysteresis band | functional | medium | team-control | test | approved | The system shall activate heating when the temperature is below setpoint − 0.5 °C. |
| REQ-004 | Heating deactivation above hysteresis band | functional | medium | team-control | test | approved | The system shall deactivate heating when the temperature is at or above setpoint + 0.5 °C. |
| REQ-005 | Over-temperature shutdown | safety | high | team-safety | test | approved | The system shall force heating off if the temperature exceeds 30 °C. |
| REQ-006 | Missing-sensor fail-safe | safety | high | team-safety | test | approved | The system shall enter fail-safe (heating off) if the sensor reading is missing for 3 consecutive cycles. |
| REQ-007 | Setpoint change response time | performance | medium | team-performance | test | approved | The system shall respond to a setpoint change within 2 seconds. |
| REQ-008 | Setpoint range validation | functional | medium | team-control | test | approved | The system shall accept setpoints only between 5 °C and 30 °C. |
| REQ-009 | Status REST endpoint | interface | medium | team-interface | test | approved | The system shall expose the current state through a REST endpoint GET /status. |
| REQ-010 | Setpoint update endpoint | interface | medium | team-interface | test | approved | The system shall accept setpoint updates through PUT /setpoint. |
| REQ-011 | Authenticated setpoint updates | security | high | team-security | test | approved | The system shall require an API token for PUT /setpoint. |
| REQ-012 | Token confidentiality in logs | security | high | team-security | test | approved | The system shall not log API tokens. |
| REQ-013 | Status endpoint latency | performance | medium | team-performance | test | approved | The system shall respond to GET /status in under 100 ms (p95) under 50 req/s. |
