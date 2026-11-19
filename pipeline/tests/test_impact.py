"""Tests for impact analysis, selective test selection, and RTM diffing."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mbse.impact import analyse_impact, write_impact, write_rtm_diff

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

BASE_REQUIREMENT = "REQ-003"
CHILD_REQUIREMENT = "REQ-003-1"
MODEL_ELEMENT = "BLK-controller"
CODE_PATH = "src/thermostat/controller.py"
TEST_ID = "tests/test_controller.py::test_control"


def _run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-m", message)
    return _run_git(root, "rev-parse", "HEAD")


def _write_requirement(
    root: Path,
    requirement_id: str,
    *,
    title: str = "Controller requirement",
    parent: str | None = None,
) -> Path:
    lines = [
        f"id: {requirement_id}",
        f'title: "{title}"',
        'text: "The system shall control the thermostat."',
        "type: functional",
        "priority: high",
        "owner: team-demo",
        "verification: test",
        "status: approved",
        'rationale: "Keeps the demo traceable."',
    ]
    if parent is not None:
        lines.append(f"parent: {parent}")
    path = root / "requirements" / f"{requirement_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_project(root: Path) -> None:
    _write_requirement(root, BASE_REQUIREMENT)
    _write_requirement(root, CHILD_REQUIREMENT, parent=BASE_REQUIREMENT)

    model = (
        "system: DemoSystem\n"
        "version: 1.0.0\n"
        "elements:\n"
        f"  - id: {MODEL_ELEMENT}\n"
        "    kind: block\n"
        "    name: Controller\n"
        f"    satisfies: [{BASE_REQUIREMENT}]\n"
        f"    allocated_to: {CODE_PATH}\n"
        "relations: []\n"
    )
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "models" / "system.yaml").write_text(model, encoding="utf-8")

    code = (
        f"# @implements {BASE_REQUIREMENT}\n\ndef control(value: int) -> int:\n    return value\n"
    )
    code_path = root / CODE_PATH
    code_path.parent.mkdir(parents=True, exist_ok=True)
    code_path.write_text(code, encoding="utf-8")

    test = (
        "import pytest\n"
        "\n"
        f'@pytest.mark.req("{BASE_REQUIREMENT}")\n'
        "def test_control() -> None:\n"
        "    assert True\n"
    )
    test_path = root / "tests" / "test_controller.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test, encoding="utf-8")


def _make_repository(root: Path) -> str:
    """Create a project, commit the baseline, and return the base commit SHA."""
    _write_project(root)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True, text=True)
    _run_git(root, "config", "user.email", "impact@example.com")
    _run_git(root, "config", "user.name", "Impact Tests")
    return _commit(root, "baseline")


def _modify_and_commit(root: Path) -> str:
    _write_requirement(
        root,
        BASE_REQUIREMENT,
        title="Controller requirement revised",
    )
    return _commit(root, "revise requirement")


def _entries(report: dict, key: str) -> list[dict]:
    return report["artifacts"][key]


def _ids(report: dict, key: str) -> list[str]:
    return [entry["id"] for entry in _entries(report, key)]


def test_requirement_change_reaches_model_code_tests_and_children(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    base = _make_repository(root)
    _modify_and_commit(root)

    report = analyse_impact(base, "HEAD", root)

    assert report["base"] == base
    assert report["head"] == "HEAD"
    assert report["changed_files"] == ["requirements/REQ-003.yaml"]

    assert _ids(report, "directly_changed") == [BASE_REQUIREMENT]
    assert _ids(report, "needs_review") == [MODEL_ELEMENT, CHILD_REQUIREMENT]
    assert _ids(report, "needs_retest") == [TEST_ID]
    assert _ids(report, "impacted") == [CODE_PATH]

    assert report["summary"] == {
        "changed_files": 1,
        "directly_changed": 1,
        "impacted": 1,
        "needs_review": 2,
        "needs_retest": 1,
    }
    assert report["risk"]["level"] == "low"
    assert report["risk"]["depth"] == 1
    assert report["risk"]["changed_files"] == 1
    assert report["risk"]["safety_requirements"] == 0
    assert report["risk"]["security_requirements"] == 0
    assert report["requirements"] == {
        "direct": [BASE_REQUIREMENT],
        "affected": [BASE_REQUIREMENT, CHILD_REQUIREMENT],
    }

    reasons = {entry["id"]: entry["reasons"] for entry in _entries(report, "directly_changed")}
    assert reasons[BASE_REQUIREMENT] == ["changed file: requirements/REQ-003.yaml"]


def test_impact_report_writes_json_and_markdown(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    base = _make_repository(root)
    _modify_and_commit(root)
    report = analyse_impact(base, "HEAD", root)

    json_path, markdown_path = write_impact(report, root)

    assert json_path == root / "build" / "reports" / "impact.json"
    assert markdown_path == root / "build" / "reports" / "impact.md"
    assert json.loads(json_path.read_text(encoding="utf-8")) == report

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Impact Analysis" in markdown
    assert "## Summary" in markdown
    assert "## Risk" in markdown
    assert "## Directly changed" in markdown
    assert "## Impacted" in markdown
    assert "## Needs review" in markdown
    assert "## Needs retest" in markdown
    assert "## Changed files" in markdown
    assert "| ID | Type | Path | Reasons |" in markdown
    assert f"| {MODEL_ELEMENT} | ModelElement |" in markdown
    assert f"| {CODE_PATH} | CodeModule |" in markdown
    assert TEST_ID in markdown
    assert "requirements/REQ-003.yaml" in markdown


def test_rtm_diff_reports_changed_requirement(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    base = _make_repository(root)
    _modify_and_commit(root)

    path = write_rtm_diff(base, "HEAD", root)

    assert path == root / "build" / "reports" / "rtm_diff.md"
    content = path.read_text(encoding="utf-8")
    assert "# RTM Diff" in content
    assert "## Added requirements" in content
    assert "## Removed requirements" in content
    assert "## Changed requirements" in content
    assert BASE_REQUIREMENT in content
    assert "Title" in content
    assert "unavailable" not in content.lower()

    changed_section = content.split("## Changed requirements", 1)[1]
    assert BASE_REQUIREMENT in changed_section


def test_rtm_diff_marks_unavailable_when_git_fails(tmp_path: Path) -> None:
    root = tmp_path / "not-a-repository"
    root.mkdir()

    path = write_rtm_diff("origin/main", "HEAD", root)

    assert path == root / "build" / "reports" / "rtm_diff.md"
    assert "unavailable" in path.read_text(encoding="utf-8").lower()


def test_analysis_without_git_or_reports_does_not_crash(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()

    report = analyse_impact("origin/main", "HEAD", root)

    assert report["changed_files"] == []
    assert report["summary"] == {
        "changed_files": 0,
        "directly_changed": 0,
        "impacted": 0,
        "needs_review": 0,
        "needs_retest": 0,
    }
    assert report["risk"]["level"] == "low"
    assert report["risk"]["depth"] == 0
    assert report["requirements"] == {"direct": [], "affected": []}

    json_path, markdown_path = write_impact(report, root)
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert "None." in markdown_path.read_text(encoding="utf-8")
