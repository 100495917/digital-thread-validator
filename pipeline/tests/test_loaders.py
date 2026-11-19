"""Tests for the artifact loaders and shared findings model."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from mbse.findings import Finding, sort_findings
from mbse.loaders import (
    LoadError,
    load_code_tags,
    load_model,
    load_requirements,
    load_test_tags,
)


def _write_requirement(root: Path, requirement_id: str, **overrides: object) -> Path:
    """Write a minimal requirement YAML file and return its path."""
    data: dict[str, object] = {
        "id": requirement_id,
        "title": f"Title for {requirement_id}",
        "text": f"The system shall do something for {requirement_id}.",
        "type": "functional",
        "priority": "high",
        "owner": "team-control",
        "verification": "test",
        "status": "approved",
    }
    data.update(overrides)
    path = root / "requirements" / f"{requirement_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_requirements_sorts_and_defaults_optional_fields(tmp_path: Path) -> None:
    _write_requirement(
        tmp_path,
        "REQ-002",
        rationale="Because it matters.",
        parent="REQ-001",
    )
    _write_requirement(tmp_path, "REQ-001")

    requirements = load_requirements(tmp_path)

    assert [requirement.id for requirement in requirements] == ["REQ-001", "REQ-002"]
    first, second = requirements
    assert first.path == "requirements/REQ-001.yaml"
    assert first.rationale == ""
    assert first.parent is None
    assert first.raw["id"] == "REQ-001"
    assert second.rationale == "Because it matters."
    assert second.parent == "REQ-001"
    assert second.text == "The system shall do something for REQ-002."


def test_load_requirements_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert load_requirements(tmp_path) == []


def test_load_requirements_malformed_yaml_raises_load_error(tmp_path: Path) -> None:
    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()
    (requirements_dir / "REQ-001.yaml").write_text("id: [unclosed\n", encoding="utf-8")

    with pytest.raises(LoadError) as error:
        load_requirements(tmp_path)

    assert error.value.path == "requirements/REQ-001.yaml"
    assert error.value.message


def test_load_requirements_non_mapping_raises_load_error(tmp_path: Path) -> None:
    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()
    (requirements_dir / "REQ-001.yaml").write_text("- just\n- a list\n", encoding="utf-8")

    with pytest.raises(LoadError, match="expected a YAML mapping"):
        load_requirements(tmp_path)


def test_load_model_maps_elements_and_relations(tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "system.yaml").write_text(
        yaml.safe_dump(
            {
                "system": "SmartThermostat",
                "version": "1.0.0",
                "elements": [
                    {
                        "id": "BLK-controller",
                        "kind": "block",
                        "name": "TemperatureController",
                        "satisfies": ["REQ-001", "REQ-002"],
                        "allocated_to": "src/thermostat/controller.py",
                    },
                    {
                        "id": "IF-sensor",
                        "kind": "interface",
                        "name": "SensorInterface",
                    },
                ],
                "relations": [
                    {
                        "from": "BLK-controller",
                        "to": "IF-sensor",
                        "type": "uses",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    model = load_model(tmp_path)

    assert model.system == "SmartThermostat"
    assert model.version == "1.0.0"
    assert model.path == "models/system.yaml"
    assert [element.id for element in model.elements] == ["BLK-controller", "IF-sensor"]
    assert model.elements[0].satisfies == ("REQ-001", "REQ-002")
    assert model.elements[0].allocated_to == "src/thermostat/controller.py"
    assert model.elements[1].satisfies == ()
    assert model.elements[1].allocated_to is None
    assert len(model.relations) == 1
    relation = model.relations[0]
    assert (relation.from_id, relation.to_id, relation.type) == (
        "BLK-controller",
        "IF-sensor",
        "uses",
    )
    assert relation.raw["from"] == "BLK-controller"


def test_load_model_missing_raises_load_error(tmp_path: Path) -> None:
    with pytest.raises(LoadError) as error:
        load_model(tmp_path)

    assert error.value.path == "models/system.yaml"
    assert "not found" in error.value.message


def test_load_model_invalid_yaml_raises_load_error(tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "system.yaml").write_text("system: [unclosed\n", encoding="utf-8")

    with pytest.raises(LoadError) as error:
        load_model(tmp_path)

    assert error.value.path == "models/system.yaml"


def test_load_code_tags_maps_sorted_paths(tmp_path: Path) -> None:
    package = tmp_path / "src" / "thermostat"
    package.mkdir(parents=True)
    (package / "controller.py").write_text(
        "# @implements REQ-001\n# @implements REQ-003\ndef control():\n    pass\n",
        encoding="utf-8",
    )
    (package / "heater.py").write_text(
        "# @implements REQ-003\n# @implements REQ-001\n",
        encoding="utf-8",
    )
    (package / "unused.py").write_text("# no tags here\n", encoding="utf-8")
    (tmp_path / "src" / "top.py").write_text("# @implements REQ-002\n", encoding="utf-8")

    tags = load_code_tags(tmp_path)

    assert tags == {
        "REQ-001": ("src/thermostat/controller.py", "src/thermostat/heater.py"),
        "REQ-002": ("src/top.py",),
        "REQ-003": ("src/thermostat/controller.py", "src/thermostat/heater.py"),
    }


def test_load_code_tags_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert load_code_tags(tmp_path) == {}


def test_load_test_tags_extracts_marker_ids(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests" / "requirements"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_requirements.py").write_text(
        "import pytest\n"
        "from pytest import mark\n"
        "\n"
        "\n"
        '@pytest.mark.req("REQ-001", "REQ-002")\n'
        "def test_multiple():\n"
        "    pass\n"
        "\n"
        "\n"
        '@pytest.mark.req("REQ-001")\n'
        "def test_duplicate():\n"
        "    pass\n"
        "\n"
        "\n"
        '@mark.req("REQ-003")\n'
        "class TestClass:\n"
        "    def test_method(self):\n"
        "        pass\n"
        "\n"
        "\n"
        'REQUIREMENT = "REQ-004"\n'
        "\n"
        "\n"
        "@pytest.mark.req(REQUIREMENT)\n"
        "def test_non_literal():\n"
        "    pass\n"
        "\n"
        "\n"
        '@pytest.mark.other("REQ-005")\n'
        "def test_other_marker():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_top.py").write_text(
        '@pytest.mark.req("REQ-002")\ndef test_top():\n    pass\n',
        encoding="utf-8",
    )

    tags = load_test_tags(tmp_path)

    assert tags == {
        "REQ-001": ("tests/requirements/test_requirements.py",),
        "REQ-002": (
            "tests/requirements/test_requirements.py",
            "tests/test_top.py",
        ),
        "REQ-003": ("tests/requirements/test_requirements.py",),
    }


def test_load_test_tags_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert load_test_tags(tmp_path) == {}


def test_sort_findings_orders_by_path_rule_message() -> None:
    findings = [
        Finding("b.yaml", "RQ-001", "error", "second"),
        Finding("a.yaml", "RQ-002", "warning", "third"),
        Finding("a.yaml", "RQ-001", "error", "first"),
    ]

    assert sort_findings(findings) == [
        Finding("a.yaml", "RQ-001", "error", "first"),
        Finding("a.yaml", "RQ-002", "warning", "third"),
        Finding("b.yaml", "RQ-001", "error", "second"),
    ]
