"""Tests for baseline freezing, loading, diffing, and report rendering."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from mbse import baseline
from mbse.thread import load_thread
from mbse.trace import write_rtm

REQUIREMENT_ID = "REQ-001"
RTM_HEADERS = ("Req ID", "Title", "Priority", "Status")


def _write_requirement(root: Path) -> Path:
    content = (
        f"id: {REQUIREMENT_ID}\n"
        'title: "Demo requirement"\n'
        'text: "The system shall satisfy the demo requirement."\n'
        "type: functional\n"
        "priority: high\n"
        "owner: team-demo\n"
        "verification: test\n"
        "status: approved\n"
        'rationale: "Keeps the demo traceable."\n'
    )
    path = root / "requirements" / f"{REQUIREMENT_ID}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_model(root: Path) -> Path:
    content = (
        "system: DemoSystem\n"
        "version: 1.0.0\n"
        "elements:\n"
        "  - id: BLK-controller\n"
        "    kind: block\n"
        "    name: Controller\n"
        f"    satisfies: [{REQUIREMENT_ID}]\n"
        "    allocated_to: src/app.py\n"
        "relations: []\n"
    )
    path = root / "models" / "system.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_code(root: Path, text: str | None = None) -> Path:
    content = text or f"# @implements {REQUIREMENT_ID}\n\ndef demo() -> bool:\n    return True\n"
    path = root / "src" / "app.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_test(root: Path, name: str = "test_app.py") -> Path:
    content = (
        "import pytest\n"
        "\n"
        f'@pytest.mark.req("{REQUIREMENT_ID}")\n'
        "def test_demo() -> None:\n"
        "    assert True\n"
    )
    path = root / "tests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_rtm(root: Path, rows: list[dict[str, str]]) -> Path:
    path = root / "build" / "reports" / "rtm.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RTM_HEADERS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_thread(root: Path, nodes: list[dict[str, str]]) -> Path:
    path = root / "digital_thread" / "thread.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "metadata": {"commit_sha": "local"},
        "nodes": nodes,
        "edges": [],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project with requirement, model, code, and test files."""
    _write_requirement(tmp_path)
    _write_model(tmp_path)
    _write_code(tmp_path)
    _write_test(tmp_path)
    return tmp_path


def _two_baselines(root: Path) -> tuple[str, str]:
    """Write an old and a new baseline with deliberate artifact/RTM/thread changes."""
    _write_rtm(
        root,
        [
            {"Req ID": "REQ-001", "Title": "Old title", "Priority": "high", "Status": "complete"},
            {"Req ID": "REQ-002", "Title": "Second", "Priority": "low", "Status": "complete"},
        ],
    )
    _write_thread(
        root,
        [
            {"id": "REQ-001", "type": "Requirement", "sha256": "aaa"},
            {"id": "src/app.py", "type": "CodeModule", "sha256": "bbb"},
        ],
    )
    baseline.write_baseline("v1", root)

    _write_code(root, "# @implements REQ-001\n\nVALUE = 2\n")
    (root / "tests" / "test_app.py").unlink()
    (root / "src" / "extra.py").write_text("VALUE = 3\n", encoding="utf-8")
    _write_rtm(
        root,
        [
            {"Req ID": "REQ-001", "Title": "New title", "Priority": "high", "Status": "complete"},
            {"Req ID": "REQ-003", "Title": "Third", "Priority": "low", "Status": "complete"},
        ],
    )
    _write_thread(
        root,
        [
            {"id": "REQ-001", "type": "Requirement", "sha256": "changed"},
            {"id": "src/extra.py", "type": "CodeModule", "sha256": "ccc"},
        ],
    )
    baseline.write_baseline("v2", root)
    return "v1", "v2"


def test_collect_artifacts_hashes_tracked_files_and_skips_caches(project: Path) -> None:
    (project / "src" / "__pycache__").mkdir()
    (project / "src" / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"cache")
    (project / "tests" / "__pycache__").mkdir()
    (project / "tests" / "__pycache__" / "test_app.cpython-311.pyc").write_bytes(b"cache")
    (project / "src" / "notes.txt").write_text("not tracked\n", encoding="utf-8")
    (project / "docs").mkdir()
    (project / "docs" / "readme.md").write_text("not tracked\n", encoding="utf-8")

    artifacts = baseline.collect_artifacts(project)

    assert list(artifacts) == sorted(artifacts)
    assert set(artifacts) == {
        "requirements/REQ-001.yaml",
        "models/system.yaml",
        "src/app.py",
        "tests/test_app.py",
    }
    for relative, digest in artifacts.items():
        expected = hashlib.sha256((project / relative).read_bytes()).hexdigest()
        assert digest == expected
    assert all("__pycache__" not in path for path in artifacts)


def test_baseline_round_trip_embeds_rtm_rows_and_thread_snapshot(project: Path) -> None:
    write_rtm(project)
    _write_thread(project, [{"id": "REQ-001", "type": "Requirement", "sha256": "abc"}])

    created = baseline.create_baseline("v1", project)
    path = baseline.write_baseline("v1", project)
    loaded = baseline.load_baseline("v1", project)

    assert path == project / "baselines" / "baseline-v1.json"
    assert loaded == created
    assert created["version"] == "v1"
    assert created["artifacts"]["src/app.py"]
    assert created["rtm"] == [
        {
            "Req ID": REQUIREMENT_ID,
            "Title": "Demo requirement",
            "Priority": "high",
            "Model elements": "BLK-controller",
            "Code": "src/app.py",
            "Tests": "tests/test_app.py",
            "Last result": "not-run",
            "Status": "complete",
        }
    ]
    assert created["thread"] == load_thread(project)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "artifacts": {' in text


def test_diff_detects_artifact_rtm_and_thread_changes(project: Path) -> None:
    old, new = _two_baselines(project)

    diff = baseline.diff_baselines(old, new, project)

    assert set(diff) == {"old", "new", "artifacts", "rtm", "thread"}
    assert diff["old"] == "v1"
    assert diff["new"] == "v2"
    assert diff["artifacts"] == {
        "added": ["src/extra.py"],
        "removed": ["tests/test_app.py"],
        "changed": ["src/app.py"],
    }
    assert diff["rtm"] == {
        "added": ["REQ-003"],
        "removed": ["REQ-002"],
        "changed": ["REQ-001"],
    }
    assert diff["thread"] == {
        "added": ["src/extra.py"],
        "removed": ["src/app.py"],
        "modified": ["REQ-001"],
    }


def test_write_baseline_diff_writes_json_and_markdown_reports(project: Path) -> None:
    old, new = _two_baselines(project)

    json_path, markdown_path = baseline.write_baseline_diff(old, new, project)

    assert json_path == project / "build" / "reports" / "baseline_diff.json"
    assert markdown_path == project / "build" / "reports" / "baseline_diff.md"
    assert json.loads(json_path.read_text(encoding="utf-8")) == baseline.diff_baselines(
        old, new, project
    )

    text = markdown_path.read_text(encoding="utf-8")
    assert text.startswith("# Baseline Diff: v1 -> v2\n")
    for heading in (
        "## Artifacts",
        "## Requirements (RTM)",
        "## Digital thread",
        "### Added",
        "### Removed",
        "### Changed",
    ):
        assert heading in text
    assert "`src/extra.py`" in text
    assert "`REQ-003`" in text
    assert "`REQ-001`" in text
    assert text.endswith("\n")


def test_missing_baselines_raise_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="v404"):
        baseline.load_baseline("v404", tmp_path)

    with pytest.raises(FileNotFoundError, match="v404"):
        baseline.diff_baselines("v404", "v405", tmp_path)
