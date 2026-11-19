"""Tests for model structure validation (Phase 3.3)."""

from __future__ import annotations

from pathlib import Path

from mbse.findings import Finding
from mbse.loaders import ModelElement, ModelRelation, SystemModel
from mbse.validate_model import MODEL_PATH, validate_model

ALLOCATED_FILES = (
    "src/alpha.py",
    "src/beta.py",
    "src/bus.py",
    "src/cycle.py",
)


def _element(
    id: str,
    kind: str,
    name: str,
    satisfies: tuple[str, ...] = (),
    allocated_to: str | None = None,
) -> ModelElement:
    return ModelElement(
        id=id,
        kind=kind,
        name=name,
        satisfies=satisfies,
        allocated_to=allocated_to,
        raw={},
    )


def _relation(from_id: str, to_id: str) -> ModelRelation:
    return ModelRelation(from_id=from_id, to_id=to_id, type="uses", raw={})


def _model(elements: list[ModelElement], relations: list[ModelRelation]) -> SystemModel:
    return SystemModel(
        system="SmartThermostat",
        version="1.0.0",
        elements=elements,
        relations=relations,
        path="models/system.yaml",
        raw={},
    )


def _write_allocations(root: Path, paths: tuple[str, ...] = ALLOCATED_FILES) -> None:
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")


def _valid_elements() -> list[ModelElement]:
    return [
        _element("BLK-alpha", "block", "Alpha", ("REQ-001",), "src/alpha.py"),
        _element("BLK-beta", "block", "Beta", (), "src/beta.py"),
        _element("IF-bus", "interface", "Bus", (), "src/bus.py"),
        _element("BHV-cycle", "behavior", "ControlCycle", (), "src/cycle.py"),
    ]


def _valid_relations() -> list[ModelRelation]:
    return [
        _relation("BLK-alpha", "IF-bus"),
        _relation("BLK-beta", "IF-bus"),
        _relation("BHV-cycle", "BLK-alpha"),
    ]


def _rules(findings: list[Finding]) -> list[str]:
    return [finding.rule for finding in findings]


def _assert_only_rule(findings: list[Finding], rule: str) -> None:
    assert _rules(findings) == [rule]
    assert findings[0].path == MODEL_PATH
    assert findings[0].severity == "error"


def test_valid_model_has_no_findings(tmp_path: Path) -> None:
    _write_allocations(tmp_path)

    findings = validate_model(
        _model(_valid_elements(), _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    assert findings == []


def test_mdl_001_duplicate_ids(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = _valid_elements() + [_element("BLK-beta", "block", "Beta", (), "src/beta.py")]

    findings = validate_model(
        _model(elements, _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-001")
    assert "BLK-beta" in findings[0].message


def test_mdl_002_block_id_prefix(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = _valid_elements() + [
        _element("IF-wrong", "block", "Wrong", ("REQ-001",), "src/alpha.py")
    ]

    findings = validate_model(
        _model(elements, _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-002")
    assert "IF-wrong" in findings[0].message
    assert "'BLK-'" in findings[0].message


def test_mdl_002_block_name_pascal_case(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = _valid_elements() + [
        _element("BLK-gamma", "block", "not_pascal", ("REQ-001",), "src/alpha.py")
    ]

    findings = validate_model(
        _model(elements, _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-002")
    assert "BLK-gamma" in findings[0].message
    assert "not_pascal" in findings[0].message


def test_mdl_003_unknown_satisfies_target(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = [
        _element("BLK-alpha", "block", "Alpha", ("REQ-999",), "src/alpha.py"),
        _element("BLK-beta", "block", "Beta", (), "src/beta.py"),
        _element("IF-bus", "interface", "Bus", (), "src/bus.py"),
        _element("BHV-cycle", "behavior", "ControlCycle", (), "src/cycle.py"),
    ]

    findings = validate_model(
        _model(elements, _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-003")
    assert "REQ-999" in findings[0].message


def test_mdl_003_loads_requirements_from_root(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    requirements = tmp_path / "requirements"
    requirements.mkdir()
    (requirements / "REQ-001.yaml").write_text(
        "id: REQ-001\n"
        "title: Temperature setpoint tracking\n"
        'text: "The system shall maintain the room temperature."\n'
        "type: functional\n"
        "priority: high\n"
        "owner: team-control\n"
        "verification: test\n"
        "status: approved\n",
        encoding="utf-8",
    )

    findings = validate_model(_model(_valid_elements(), _valid_relations()), root=tmp_path)

    assert findings == []


def test_mdl_004_missing_allocated_to_path(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = _valid_elements()
    elements[1] = _element("BLK-beta", "block", "Beta", (), "src/missing.py")

    findings = validate_model(
        _model(elements, _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-004")
    assert "BLK-beta" in findings[0].message
    assert "src/missing.py" in findings[0].message


def test_mdl_005_orphan_block(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = _valid_elements() + [_element("BLK-orphan", "block", "Orphan", (), "src/alpha.py")]

    findings = validate_model(
        _model(elements, _valid_relations()),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-005")
    assert "BLK-orphan" in findings[0].message


def test_mdl_006_dangling_relation_endpoint(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    relations = _valid_relations() + [_relation("BLK-alpha", "BLK-ghost")]

    findings = validate_model(
        _model(_valid_elements(), relations),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-006")
    assert "BLK-ghost" in findings[0].message


def test_mdl_007_interface_counts_distinct_blocks(tmp_path: Path) -> None:
    _write_allocations(tmp_path)
    elements = _valid_elements()
    elements[1] = _element("BLK-beta", "block", "Beta", ("REQ-001",), "src/beta.py")
    relations = [
        _relation("BLK-alpha", "IF-bus"),
        _relation("BLK-alpha", "IF-bus"),
        _relation("BHV-cycle", "IF-bus"),
        _relation("BHV-cycle", "BLK-alpha"),
    ]

    findings = validate_model(
        _model(elements, relations),
        root=tmp_path,
        requirement_ids={"REQ-001"},
    )

    _assert_only_rule(findings, "MDL-007")
    assert "IF-bus" in findings[0].message
    assert "1 block(s)" in findings[0].message
