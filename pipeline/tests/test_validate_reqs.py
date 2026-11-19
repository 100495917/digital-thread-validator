"""Unit tests for requirements quality validation (RQ-001 .. RQ-008)."""

from __future__ import annotations

import json
from pathlib import Path

from mbse.loaders import Requirement
from mbse.validate_reqs import quality_report, validate_requirements, write_quality_report


def make_req(req_id: str = "REQ-001", **overrides: object) -> Requirement:
    """Build a valid requirement, overriding individual fields as needed."""
    fields: dict[str, object] = {
        "id": req_id,
        "title": "Heating threshold",
        "text": "The system shall activate heating below 0.5 °C.",
        "type": "functional",
        "priority": "high",
        "owner": "team-control",
        "verification": "test",
        "status": "approved",
        "rationale": "Keeps the room warm.",
        "parent": None,
        "path": f"requirements/{req_id}.yaml",
        "raw": {},
    }
    fields.update(overrides)
    if "id" in overrides and "path" not in overrides:
        fields["path"] = f"requirements/{overrides['id']}.yaml"
    return Requirement(**fields)  # type: ignore[arg-type]


def rules(findings: list) -> set[str]:
    """Return the set of rule IDs present in ``findings``."""
    return {finding.rule for finding in findings}


def test_valid_requirement_has_no_findings() -> None:
    assert validate_requirements([make_req()]) == []


def test_validate_requirements_empty_input() -> None:
    assert validate_requirements([]) == []


def test_rq_001_id_pattern_name_and_uniqueness() -> None:
    assert rules(validate_requirements([make_req()])) == set()

    invalid_id = validate_requirements([make_req(id="REQ-1", path="requirements/REQ-1.yaml")])
    assert rules(invalid_id) == {"RQ-001"}
    assert invalid_id[0].severity == "error"
    assert invalid_id[0].path == "requirements/REQ-1.yaml"
    assert invalid_id[0].requirement == "REQ-1"
    assert "REQ-1" in invalid_id[0].message

    mismatch = validate_requirements([make_req(id="REQ-042", path="requirements/REQ-001.yaml")])
    assert rules(mismatch) == {"RQ-001"}
    assert "REQ-042" in mismatch[0].message
    assert "REQ-001.yaml" in mismatch[0].message


def test_rq_001_flags_every_duplicate_id() -> None:
    findings = validate_requirements([make_req(), make_req(path="requirements/REQ-002.yaml")])
    duplicates = [
        finding
        for finding in findings
        if finding.rule == "RQ-001" and "duplicate" in finding.message
    ]

    assert len(duplicates) == 2
    assert {finding.requirement for finding in duplicates} == {"REQ-001"}
    assert all(finding.severity == "error" for finding in duplicates)


def test_rq_002_requires_exactly_one_shall() -> None:
    assert rules(validate_requirements([make_req()])) == set()

    without_shall = validate_requirements(
        [make_req(text="The system activates heating below 0.5 °C.")]
    )
    assert rules(without_shall) == {"RQ-002"}
    assert without_shall[0].severity == "error"
    assert "0 occurrence(s)" in without_shall[0].message

    twice = validate_requirements([make_req(text="The system shall heat and shall cool the room.")])
    assert rules(twice) == {"RQ-002"}
    assert "2 occurrence(s)" in twice[0].message


def test_rq_003_rejects_ambiguous_terms() -> None:
    assert rules(validate_requirements([make_req()])) == set()

    findings = validate_requirements(
        [make_req(text="The system shall quickly activate heating below 0.5 °C.")]
    )
    assert rules(findings) == {"RQ-003"}
    assert findings[0].severity == "error"
    assert "quickly" in findings[0].message


def test_rq_004_requires_measurable_performance_values() -> None:
    valid_performance = make_req(
        type="performance",
        text="The system shall respond to a setpoint change within 2 seconds.",
    )
    assert validate_requirements([valid_performance]) == []

    for text in (
        "The system shall respond in under 100 ms (p95) under 50 req/s.",
        "The system shall keep the setpoint within 0.5 °C.",
        "The system shall sustain 500 requests/s.",
        "The system shall store at least 10 MB.",
    ):
        assert validate_requirements([make_req(type="performance", text=text)]) == []

    vague = validate_requirements(
        [
            make_req(
                type="performance",
                text="The system shall respond to a setpoint change promptly.",
            )
        ]
    )
    assert rules(vague) == {"RQ-004"}
    assert vague[0].severity == "error"

    # RQ-004 does not apply to non-performance requirements.
    assert rules(validate_requirements([make_req()])) == set()


def test_rq_005_requires_mandatory_fields() -> None:
    assert rules(validate_requirements([make_req()])) == set()

    missing_owner = validate_requirements([make_req(owner="")])
    assert rules(missing_owner) == {"RQ-005"}
    assert "owner" in missing_owner[0].message
    assert missing_owner[0].severity == "error"

    missing_all = validate_requirements([make_req(owner="", priority="", verification="")])
    assert rules(missing_all) == {"RQ-005"}
    assert len([finding for finding in missing_all if finding.rule == "RQ-005"]) == 3
    assert {"owner", "priority", "verification"} <= {
        field
        for field in ("owner", "priority", "verification")
        if any(field in finding.message for finding in missing_all)
    }


def test_rq_006_requires_existing_parent_without_cycles() -> None:
    parented = [make_req(id="REQ-001", parent="REQ-002"), make_req(id="REQ-002")]
    assert validate_requirements(parented) == []

    missing_parent = validate_requirements([make_req(parent="REQ-999")])
    assert rules(missing_parent) == {"RQ-006"}
    assert "REQ-999" in missing_parent[0].message
    assert missing_parent[0].severity == "error"

    cyclic = [
        make_req(id="REQ-001", parent="REQ-002"),
        make_req(id="REQ-002", parent="REQ-001"),
    ]
    cycle_findings = validate_requirements(cyclic)
    assert rules(cycle_findings) == {"RQ-006"}
    assert len(cycle_findings) == 2
    assert {finding.requirement for finding in cycle_findings} == {"REQ-001", "REQ-002"}
    assert all("cycle" in finding.message for finding in cycle_findings)

    with_child = cyclic + [make_req(id="REQ-003", parent="REQ-001")]
    flagged = {
        finding.requirement
        for finding in validate_requirements(with_child)
        if finding.rule == "RQ-006"
    }
    assert flagged == {"REQ-001", "REQ-002", "REQ-003"}


def test_rq_007_flags_overlong_text_as_warning() -> None:
    assert validate_requirements([make_req()]) == []

    long_text = (
        "The system shall maintain the room temperature within the configured comfort band"
        + " while preserving stable control behaviour" * 8
        + "."
    )
    assert len(long_text) > 300

    findings = validate_requirements([make_req(text=long_text)])
    assert rules(findings) == {"RQ-007"}
    assert findings[0].severity == "warning"
    assert "300" in findings[0].message


def test_rq_008_rejects_tbd_verification_for_approved_requirements() -> None:
    findings = validate_requirements([make_req(status="approved", verification="TBD")])
    assert rules(findings) == {"RQ-008"}
    assert findings[0].severity == "error"
    assert "TBD" in findings[0].message

    draft = make_req(status="draft", verification="TBD")
    assert validate_requirements([draft]) == []


def test_quality_report_full_score() -> None:
    report = quality_report([make_req()], [])

    assert report["summary"] == {
        "requirements": 1,
        "score": 100.0,
        "errors": 0,
        "warnings": 0,
    }
    assert report["requirements"] == [
        {
            "id": "REQ-001",
            "title": "Heating threshold",
            "score": 100.0,
            "failed_rules": [],
        }
    ]


def test_quality_report_deducts_once_per_distinct_rule() -> None:
    bad = make_req(text="The system will quickly activate heating.")
    findings = validate_requirements([bad])

    assert rules(findings) == {"RQ-002", "RQ-003"}

    report = quality_report([bad], findings)
    entry = report["requirements"][0]
    assert entry["failed_rules"] == ["RQ-002", "RQ-003"]
    assert entry["score"] == 75.0
    assert report["summary"]["score"] == 75.0
    assert report["summary"]["errors"] == 2
    assert report["summary"]["warnings"] == 0


def test_quality_report_scores_are_rounded_mean() -> None:
    long_text = (
        "The system shall maintain the room temperature within the configured comfort band"
        + " while preserving stable control behaviour" * 8
        + "."
    )
    requirements = [
        make_req(),
        make_req(id="REQ-002"),
        make_req(id="REQ-003", text=long_text),
    ]
    findings = validate_requirements(requirements)

    report = quality_report(requirements, findings)
    entries = {entry["id"]: entry for entry in report["requirements"]}

    assert entries["REQ-001"]["score"] == 100.0
    assert entries["REQ-002"]["score"] == 100.0
    assert entries["REQ-003"]["score"] == 87.5
    assert entries["REQ-003"]["failed_rules"] == ["RQ-007"]
    assert report["summary"]["score"] == 95.8
    assert report["summary"]["warnings"] == 1


def test_quality_report_empty_input() -> None:
    report = quality_report([], [])

    assert report == {
        "summary": {"requirements": 0, "score": 0.0, "errors": 0, "warnings": 0},
        "requirements": [],
    }


def test_write_quality_report_creates_json_with_expected_shape(tmp_path: Path) -> None:
    requirements = [
        make_req(),
        make_req(id="REQ-002", text="The system will quickly activate heating."),
    ]
    findings = validate_requirements(requirements)

    path = write_quality_report(requirements, findings, root=tmp_path)

    assert path == tmp_path / "build" / "reports" / "req_quality.json"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "timestamp" not in text.lower()

    report = json.loads(text)
    assert text == json.dumps(report, indent=2, sort_keys=True) + "\n"
    assert report["summary"] == {
        "requirements": 2,
        "score": 87.5,
        "errors": 2,
        "warnings": 0,
    }
    assert [entry["id"] for entry in report["requirements"]] == ["REQ-001", "REQ-002"]
    assert set(report["requirements"][1]) == {"id", "title", "score", "failed_rules"}
    assert report["requirements"][1]["score"] == 75.0
    assert report["requirements"][1]["failed_rules"] == ["RQ-002", "RQ-003"]


def test_validation_and_report_are_deterministic() -> None:
    requirements = [
        make_req(),
        make_req(id="REQ-002", text="The system will quickly activate heating."),
        make_req(id="REQ-003", parent="REQ-999"),
    ]
    findings_a = validate_requirements(requirements)
    findings_b = validate_requirements(reversed(requirements))

    assert findings_a == findings_b
    assert findings_a == sorted(findings_a, key=lambda item: (item.path, item.rule, item.message))

    report_a = quality_report(requirements, findings_a)
    report_b = quality_report(reversed(requirements), findings_b)

    assert report_a == report_b
    assert json.dumps(report_a, sort_keys=True) == json.dumps(report_b, sort_keys=True)
