"""Tests for conventional-commit and requirement-reference checks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from mbse.commits import check_commits

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repository(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")


def _commit(
    root: Path,
    message: str,
    path: str = "src/app.py",
    body: str | None = None,
) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n", encoding="utf-8")
    _git(root, "add", "-A")
    arguments = ["commit", "-q", "-m", message]
    if body is not None:
        arguments.extend(["-m", body])
    _git(root, *arguments)
    return _git(root, "rev-parse", "HEAD")


def test_conventional_commit_with_requirement_passes(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "feat(api): add status endpoint REQ-001", "src/status.py")

    findings = check_commits("HEAD", root=tmp_path)

    assert findings == []


def test_unconventional_subject_warns(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    sha = _commit(tmp_path, "bad subject", "docs/readme.md")

    findings = check_commits("HEAD", root=tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule == "CC-001"
    assert finding.severity == "warning"
    assert finding.path == sha[:7]
    assert "bad subject" in finding.message
    assert "conventional commit" in finding.message


def test_strict_makes_subject_violation_an_error(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "not conventional", "docs/readme.md")

    findings = check_commits("HEAD", root=tmp_path, strict=True)

    assert [finding.severity for finding in findings] == ["error"]


@pytest.mark.parametrize("path", ["requirements/REQ-001.yaml", "models/system.yaml", "src/app.py"])
def test_traced_artifacts_require_requirement_id(tmp_path: Path, path: str) -> None:
    _init_repository(tmp_path)
    sha = _commit(tmp_path, "feat: change traced artifact", path)

    findings = check_commits("HEAD", root=tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "CC-002"
    assert findings[0].severity == "warning"
    assert findings[0].path == sha[:7]


def test_requirement_id_in_body_satisfies_trace_rule(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "feat: change traced artifact", "src/app.py", body="Refs REQ-007")

    findings = check_commits("HEAD", root=tmp_path)

    assert findings == []


def test_strict_makes_missing_requirement_an_error(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "feat: change traced artifact", "src/app.py")

    findings = check_commits("HEAD", root=tmp_path, strict=True)

    assert len(findings) == 1
    assert findings[0].rule == "CC-002"
    assert findings[0].severity == "error"


def test_untraced_path_does_not_require_requirement_id(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "docs: refresh guide", "docs/guide.md")

    findings = check_commits("HEAD", root=tmp_path)

    assert findings == []


def test_findings_are_sorted_by_path_and_rule(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "unconventional change", "src/app.py")

    findings = check_commits("HEAD", root=tmp_path)

    assert [finding.rule for finding in findings] == ["CC-001", "CC-002"]
    assert findings == sorted(
        findings, key=lambda finding: (finding.path, finding.rule, finding.message)
    )


def test_without_git_returns_empty(tmp_path: Path) -> None:
    assert check_commits("HEAD", root=tmp_path) == []
