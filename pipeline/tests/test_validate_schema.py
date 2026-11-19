"""Tests for JSON Schema validation of requirements and the system model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from mbse.validate_schema import validate_schemas

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SOURCE = REPO_ROOT / "models" / "schema"
REQUIREMENT_FILE = "requirements/REQ-001.yaml"
MODEL_FILE = "models/system.yaml"


def _install_schemas(root: Path) -> None:
    target = root / "models" / "schema"
    target.mkdir(parents=True)
    for name in ("requirements.schema.json", "system.schema.json"):
        content = (SCHEMA_SOURCE / name).read_text(encoding="utf-8")
        (target / name).write_text(content, encoding="utf-8")


def _valid_requirement() -> dict[str, Any]:
    return {
        "id": "REQ-001",
        "title": "Temperature setpoint tracking",
        "text": "The system shall maintain the room temperature within 1 C of the setpoint.",
        "type": "functional",
        "priority": "high",
        "owner": "team-control",
        "verification": "test",
        "status": "approved",
        "rationale": "Room comfort depends on tracking the setpoint.",
        "parent": "REQ-002",
    }


def _valid_model() -> dict[str, Any]:
    return {
        "system": "SmartThermostat",
        "version": "1.0.0",
        "elements": [
            {
                "id": "BLK-controller",
                "kind": "block",
                "name": "TemperatureController",
                "satisfies": ["REQ-001"],
                "allocated_to": "src/thermostat/controller.py",
            },
            {
                "id": "IF-sensor",
                "kind": "interface",
                "name": "SensorInterface",
                "satisfies": ["REQ-001"],
                "allocated_to": "src/thermostat/sensor.py",
            },
        ],
        "relations": [
            {"from": "BLK-controller", "to": "IF-sensor", "type": "uses"},
        ],
    }


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_requirement(root: Path, data: dict[str, Any]) -> None:
    _write_yaml(root / REQUIREMENT_FILE, data)


def test_valid_files_produce_no_findings(tmp_path: Path) -> None:
    _install_schemas(tmp_path)
    _write_requirement(tmp_path, _valid_requirement())
    _write_yaml(tmp_path / MODEL_FILE, _valid_model())

    assert validate_schemas(tmp_path) == []


@pytest.mark.parametrize(
    ("overrides", "location", "fragment"),
    [
        ({"id": "REQ-1"}, "id", "does not match"),
        ({"priority": "urgent"}, "priority", "is not one of"),
        ({"verification": "walkthrough"}, "verification", "is not one of"),
        ({"text": ["not", "a", "string"]}, "text", "is not of type 'string'"),
    ],
)
def test_invalid_requirement_field_reports_json_path(
    tmp_path: Path,
    overrides: dict[str, Any],
    location: str,
    fragment: str,
) -> None:
    _install_schemas(tmp_path)
    requirement = _valid_requirement()
    requirement.update(overrides)
    _write_requirement(tmp_path, requirement)

    findings = validate_schemas(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "SCH-001"
    assert finding.severity == "error"
    assert finding.path == REQUIREMENT_FILE
    assert finding.message.startswith(f"{location}:")
    assert fragment in finding.message


def test_missing_required_requirement_field(tmp_path: Path) -> None:
    _install_schemas(tmp_path)
    requirement = _valid_requirement()
    del requirement["owner"]
    _write_requirement(tmp_path, requirement)

    findings = validate_schemas(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "SCH-001"
    assert finding.path == REQUIREMENT_FILE
    assert finding.message.startswith("schema:")
    assert "owner" in finding.message


@pytest.mark.parametrize(
    ("update", "location", "fragment"),
    [
        ({"id": "controller"}, "elements.0.id", "does not match"),
        ({"kind": "component"}, "elements.0.kind", "is not one of"),
        ({"name": ""}, "elements.0.name", "non-empty"),
    ],
)
def test_invalid_model_element_reports_json_path(
    tmp_path: Path,
    update: dict[str, Any],
    location: str,
    fragment: str,
) -> None:
    _install_schemas(tmp_path)
    model = _valid_model()
    model["elements"][0].update(update)
    _write_yaml(tmp_path / MODEL_FILE, model)

    findings = validate_schemas(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "SCH-001"
    assert finding.severity == "error"
    assert finding.path == MODEL_FILE
    assert finding.message.startswith(f"{location}:")
    assert fragment in finding.message


def test_missing_required_model_element_field(tmp_path: Path) -> None:
    _install_schemas(tmp_path)
    model = _valid_model()
    del model["elements"][0]["allocated_to"]
    _write_yaml(tmp_path / MODEL_FILE, model)

    findings = validate_schemas(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.path == MODEL_FILE
    assert finding.message.startswith("elements.0:")
    assert "allocated_to" in finding.message


def test_malformed_yaml_reports_error(tmp_path: Path) -> None:
    _install_schemas(tmp_path)
    requirements = tmp_path / "requirements"
    requirements.mkdir()
    (requirements / "REQ-001.yaml").write_text("id: [unclosed\n", encoding="utf-8")

    findings = validate_schemas(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "SCH-001"
    assert finding.severity == "error"
    assert finding.path == REQUIREMENT_FILE
    assert "invalid YAML" in finding.message


def test_missing_schema_files_report_errors(tmp_path: Path) -> None:
    _write_requirement(tmp_path, _valid_requirement())

    findings = validate_schemas(tmp_path)

    assert len(findings) == 2
    assert {finding.path for finding in findings} == {
        "models/schema/requirements.schema.json",
        "models/schema/system.schema.json",
    }
    assert all(finding.rule == "SCH-001" for finding in findings)
    assert all(finding.severity == "error" for finding in findings)
