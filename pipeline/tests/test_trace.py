"""Tests for traceability checks, metrics, and RTM generation."""

from __future__ import annotations

import json
from pathlib import Path

from mbse.trace import (
    build_links,
    check_traceability,
    compute_metrics,
    write_rtm,
)


def _write_requirement(
    root: Path,
    requirement_id: str,
    *,
    status: str = "approved",
    verification: str = "test",
    requirement_type: str = "functional",
) -> None:
    lines = [
        f"id: {requirement_id}",
        'title: "Demo requirement"',
        'text: "The system shall satisfy the demo requirement."',
        f"type: {requirement_type}",
        "priority: high",
        "owner: team-demo",
        f"verification: {verification}",
        f"status: {status}",
        'rationale: "Keeps the demo traceable."',
    ]
    path = root / "requirements" / f"{requirement_id}.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_model(root: Path, satisfies: tuple[str, ...]) -> None:
    satisfies_cell = "[" + ", ".join(satisfies) + "]"
    content = (
        "system: DemoSystem\n"
        "version: 1.0.0\n"
        "elements:\n"
        "  - id: BLK-controller\n"
        "    kind: block\n"
        "    name: Controller\n"
        f"    satisfies: {satisfies_cell}\n"
        "    allocated_to: src/app.py\n"
        "relations: []\n"
    )
    (root / "models" / "system.yaml").write_text(content, encoding="utf-8")


def _write_code(root: Path, requirement_ids: tuple[str, ...]) -> None:
    lines = [f"# @implements {requirement_id}" for requirement_id in requirement_ids]
    lines.extend(["", "def demo() -> bool:", "    return True", ""])
    (root / "src" / "app.py").write_text("\n".join(lines), encoding="utf-8")


def _write_tests(root: Path, requirement_ids: tuple[str, ...]) -> None:
    lines = ["import pytest", ""]
    if requirement_ids:
        for requirement_id in requirement_ids:
            lines.extend(
                [
                    f'@pytest.mark.req("{requirement_id}")',
                    "def test_demo() -> None:",
                    "    assert True",
                    "",
                ]
            )
    else:
        lines.extend(["def test_demo() -> None:", "    assert True", ""])
    (root / "tests" / "test_app.py").write_text("\n".join(lines), encoding="utf-8")


def _make_project(
    root: Path,
    *,
    requirements: tuple[tuple[str, str, str], ...] = (("REQ-001", "approved", "test"),),
    satisfies: tuple[str, ...] = ("REQ-001",),
    code_tags: tuple[str, ...] = ("REQ-001",),
    test_tags: tuple[str, ...] = ("REQ-001",),
    results: dict[str, list[dict[str, str]]] | None = None,
) -> None:
    for directory in ("requirements", "models", "src", "tests"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for requirement_id, status, verification in requirements:
        _write_requirement(root, requirement_id, status=status, verification=verification)
    _write_model(root, satisfies)
    _write_code(root, code_tags)
    _write_tests(root, test_tags)
    if results is not None:
        report_directory = root / "build" / "reports"
        report_directory.mkdir(parents=True, exist_ok=True)
        (report_directory / "req_results.json").write_text(json.dumps(results), encoding="utf-8")


def test_complete_chain_passes_checks_and_metrics(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        results={"REQ-001": [{"test": "test_demo", "outcome": "passed"}]},
    )

    links = build_links(tmp_path)

    assert [link.requirement.id for link in links] == ["REQ-001"]
    link = links[0]
    assert link.model_elements == ("BLK-controller",)
    assert link.code_paths == ("src/app.py",)
    assert link.test_paths == ("tests/test_app.py",)
    assert check_traceability(tmp_path) == []
    assert compute_metrics(links, tmp_path) == {
        "traceability_coverage": 100.0,
        "verification_coverage": 100.0,
    }


def test_rtm_is_written_in_three_formats_and_is_deterministic(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        results={"REQ-001": [{"test": "test_demo", "outcome": "passed"}]},
    )

    paths = write_rtm(tmp_path)

    assert [path.name for path in paths] == ["rtm.csv", "rtm.html", "rtm.md"]
    assert paths == sorted(paths, key=str)
    for path in paths:
        assert path.is_file()
        assert "REQ-001" in path.read_text(encoding="utf-8")
    assert paths[0].read_text(encoding="utf-8").splitlines()[0] == (
        "Req ID,Title,Priority,Model elements,Code,Tests,Last result,Status"
    )

    first_run = {path: path.read_bytes() for path in paths}
    second_paths = write_rtm(tmp_path)
    assert second_paths == paths
    for path in paths:
        assert path.read_bytes() == first_run[path]


def test_missing_test_tag_reports_trc_003_for_requirement(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _write_tests(tmp_path, ())

    findings = check_traceability(tmp_path)

    assert [finding.rule for finding in findings] == ["TRC-003"]
    assert "REQ-001" in findings[0].message
    assert findings[0].severity == "error"


def test_unknown_code_tag_reports_trc_004(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _write_code(tmp_path, ("REQ-001", "REQ-999"))

    findings = check_traceability(tmp_path)

    assert [finding.rule for finding in findings] == ["TRC-004"]
    assert "REQ-999" in findings[0].message
    assert findings[0].path == "src/app.py"


def test_deprecated_requirement_with_test_reports_trc_005(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        requirements=(("REQ-002", "deprecated", "test"),),
        satisfies=(),
        code_tags=(),
        test_tags=("REQ-002",),
    )

    findings = check_traceability(tmp_path)

    assert [finding.rule for finding in findings] == ["TRC-005"]
    assert "REQ-002" in findings[0].message
    assert findings[0].severity == "warning"


def test_security_requirement_without_test_reports_trc_006(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        requirements=(("REQ-011", "approved", "inspection"),),
        satisfies=("REQ-011",),
        code_tags=("REQ-011",),
        test_tags=(),
    )
    _write_requirement(
        tmp_path,
        "REQ-011",
        verification="inspection",
        requirement_type="security",
    )

    findings = check_traceability(tmp_path)

    assert [finding.rule for finding in findings] == ["TRC-006"]
    assert "REQ-011" in findings[0].message
    assert findings[0].requirement == "REQ-011"
    assert findings[0].severity == "error"


def test_security_requirement_with_test_has_no_trc_006(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        requirements=(("REQ-011", "approved", "inspection"),),
        satisfies=("REQ-011",),
        code_tags=("REQ-011",),
        test_tags=("REQ-011",),
    )
    _write_requirement(
        tmp_path,
        "REQ-011",
        verification="inspection",
        requirement_type="security",
    )

    assert check_traceability(tmp_path) == []
