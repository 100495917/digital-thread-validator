"""JSON Schema validation for requirement files and the system model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from mbse.findings import Finding, sort_findings

RULE = "SCH-001"
REQUIREMENTS_SCHEMA = Path("models/schema/requirements.schema.json")
SYSTEM_SCHEMA = Path("models/schema/system.schema.json")
MODEL_FILE = Path("models/system.yaml")
REQUIREMENTS_DIR = Path("requirements")


def _display(path: Path, root: Path) -> str:
    """Return a root-relative POSIX path, falling back to the resolved path."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_schema(path: Path, root: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    display = _display(path, root)
    if not path.is_file():
        return None, [
            Finding(
                path=display,
                rule=RULE,
                severity="error",
                message=f"schema: schema file not found: {display}",
            )
        ]
    try:
        raw = path.read_text(encoding="utf-8")
        schema = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [
            Finding(
                path=display,
                rule=RULE,
                severity="error",
                message=f"schema: cannot load schema {display}: {exc}",
            )
        ]
    if not isinstance(schema, dict):
        return None, [
            Finding(
                path=display,
                rule=RULE,
                severity="error",
                message=f"schema: schema {display} must be a JSON object",
            )
        ]
    return schema, []


def _load_yaml(path: Path, root: Path) -> tuple[Any, list[Finding]]:
    display = _display(path, root)
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), []
    except (OSError, yaml.YAMLError) as exc:
        return None, [
            Finding(
                path=display,
                rule=RULE,
                severity="error",
                message=f"schema: invalid YAML: {exc}",
            )
        ]


def _validate_file(
    path: Path,
    root: Path,
    validator: Draft202012Validator,
) -> list[Finding]:
    data, findings = _load_yaml(path, root)
    if findings:
        return findings

    display = _display(path, root)
    for error in validator.iter_errors(data):
        location = ".".join(str(part) for part in error.absolute_path) or "schema"
        findings.append(
            Finding(
                path=display,
                rule=RULE,
                severity="error",
                message=f"{location}: {error.message}",
            )
        )
    return findings


def validate_schemas(root: Path = Path(".")) -> list[Finding]:
    """Validate requirements and the system model against their JSON Schemas."""
    root = Path(root)
    findings: list[Finding] = []

    req_schema, req_schema_findings = _load_schema(root / REQUIREMENTS_SCHEMA, root)
    findings.extend(req_schema_findings)
    model_schema, model_schema_findings = _load_schema(root / SYSTEM_SCHEMA, root)
    findings.extend(model_schema_findings)

    if req_schema is not None:
        validator = Draft202012Validator(req_schema)
        for path in sorted((root / REQUIREMENTS_DIR).glob("*.yaml")):
            findings.extend(_validate_file(path, root, validator))

    model_path = root / MODEL_FILE
    if model_schema is not None and model_path.is_file():
        validator = Draft202012Validator(model_schema)
        findings.extend(_validate_file(model_path, root, validator))

    return sort_findings(findings)
