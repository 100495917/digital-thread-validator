"""Tests for deterministic changelog generation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from mbse.changelog import generate_changelog, write_changelog

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


def _commit(root: Path, message: str, path: str, body: str | None = None) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n", encoding="utf-8")
    _git(root, "add", "-A")
    arguments = ["commit", "-q", "-m", message]
    if body is not None:
        arguments.extend(["-m", body])
    _git(root, *arguments)
    return _git(root, "rev-parse", "HEAD")


def _build_history(root: Path) -> tuple[str, str, str]:
    _init_repository(root)
    feature = _commit(root, "feat(api): add status endpoint REQ-001", "src/status.py")
    fix = _commit(root, "fix: clamp setpoint REQ-002", "src/clamp.py")
    docs = _commit(root, "docs: describe the release", "docs/release.md")
    return feature, fix, docs


def test_generate_changelog_groups_types_and_extracts_requirements(tmp_path: Path) -> None:
    _build_history(tmp_path)

    text = generate_changelog("1.1.0", tmp_path)

    assert text.startswith("# Changelog\n")
    assert "## 1.1.0" in text
    assert text.index("### feat") < text.index("### fix") < text.index("### docs")
    assert "add status endpoint REQ-001" in text
    assert "clamp setpoint REQ-002" in text
    assert "REQ-001" in text
    assert "REQ-002" in text
    short_feature = _git(tmp_path, "rev-parse", "--short", "HEAD~2")
    short_fix = _git(tmp_path, "rev-parse", "--short", "HEAD~1")
    assert short_feature in text
    assert short_fix in text
    assert "docs: describe the release" not in text


def test_generate_changelog_without_git_is_graceful(tmp_path: Path) -> None:
    text = generate_changelog(None, tmp_path)

    assert "# Changelog" in text
    assert "## Unreleased" in text
    assert "No git history available" in text


def test_generate_changelog_uses_previous_tag_range(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _commit(tmp_path, "feat: first release REQ-001", "src/first.py")
    _git(tmp_path, "tag", "v1.0.0")
    _commit(tmp_path, "fix: second release REQ-002", "src/second.py")

    text = generate_changelog("v1.1.0", tmp_path)

    assert "second release" in text
    assert "first release" not in text
    assert "REQ-002" in text


def test_generate_changelog_without_version_lists_recent_history(tmp_path: Path) -> None:
    _build_history(tmp_path)

    text = generate_changelog(None, tmp_path)

    assert "## Unreleased" in text
    assert "add status endpoint" in text
    assert "describe the release" in text


def test_write_changelog_is_deterministic_and_uses_default_path(tmp_path: Path) -> None:
    _build_history(tmp_path)

    first = write_changelog("1.1.0", root=tmp_path)
    second = write_changelog("1.1.0", root=tmp_path)

    assert first == tmp_path / "build" / "reports" / "changelog.md"
    assert first == second
    written = first.read_text(encoding="utf-8")
    assert written == generate_changelog("1.1.0", tmp_path)
    assert written.endswith("\n")
    assert not written.endswith("\n\n")


def test_write_changelog_honours_explicit_output(tmp_path: Path) -> None:
    _build_history(tmp_path)
    output = tmp_path / "artifacts" / "CHANGELOG-1.1.0.md"

    path = write_changelog("1.1.0", output=output, root=tmp_path)

    assert path == output
    assert output.read_text(encoding="utf-8").startswith("# Changelog\n")
