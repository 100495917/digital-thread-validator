"""Deterministic changelog generation from conventional commit messages."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

_TYPE_ORDER = (
    "feat",
    "fix",
    "perf",
    "refactor",
    "docs",
    "test",
    "build",
    "ci",
    "chore",
    "style",
    "revert",
)
_TYPES = frozenset(_TYPE_ORDER)
_CONVENTIONAL = re.compile(r"^([A-Za-z]+)(?:\([^)]*\))?!?: (.+)$")
_REQUIREMENT = re.compile(r"\bREQ-\d+\b")
_RECORD = "\x1e"
_SHORT_SHA_LENGTH = 7
_HISTORY_LIMIT = 100
_DEFAULT_OUTPUT = Path("build") / "reports" / "changelog.md"


def _git(root: Path, *arguments: str) -> str | None:
    """Run ``git`` and return stdout, or ``None`` when git is unavailable/fails."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _tags(root: Path) -> list[str]:
    output = _git(
        root,
        "for-each-ref",
        "--sort=creatordate",
        "--format=%(refname:short)",
        "refs/tags",
    )
    if output is None:
        return []
    return [line.strip() for line in output.splitlines() if line.strip().startswith("v")]


def _previous_tag(version: str | None, tags: list[str]) -> str | None:
    """Return the ``v*`` tag immediately preceding ``version``."""
    if not tags:
        return None
    if version is not None and version in tags:
        index = tags.index(version)
        return tags[index - 1] if index > 0 else None
    return tags[-1]


def _history_range(root: Path, version: str | None) -> list[str]:
    if version is not None:
        previous = _previous_tag(version, _tags(root))
        if previous is not None:
            return [f"{previous}..HEAD"]
    return ["-n", str(_HISTORY_LIMIT), "HEAD"]


def _read_commits(root: Path, version: str | None) -> list[dict[str, object]] | None:
    log_range = _history_range(root, version)
    output = _git(
        root,
        "log",
        f"--format=%h%x1f%H%x1f%s%x1f%b{_RECORD}",
        *log_range,
    )
    if output is None:
        return None
    commits: list[dict[str, object]] = []
    for record in output.split(_RECORD):
        record = record.strip("\n\r")
        if not record:
            continue
        fields = record.split("\x1f", 3)
        if len(fields) < 3:
            continue
        short_sha, full_sha, subject = fields[0].strip(), fields[1].strip(), fields[2].strip()
        body = fields[3] if len(fields) > 3 else ""
        commits.append(
            {
                "sha": full_sha,
                "short_sha": short_sha,
                "subject": subject,
                "body": body,
            }
        )
    return commits


def _classify(subject: str) -> tuple[str, str]:
    """Return ``(type, displayed_subject)`` for one commit subject."""
    match = _CONVENTIONAL.match(subject)
    if match is None:
        return "other", subject
    commit_type = match.group(1).lower()
    if commit_type not in _TYPES:
        return "other", match.group(2).strip()
    return commit_type, match.group(2).strip()


def _requirement_ids(commit: dict[str, object]) -> list[str]:
    text = f"{commit['subject']}\n{commit['body']}"
    return sorted(set(_REQUIREMENT.findall(text)))


def _group(commits: Iterable[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {"other": []}
    for commit in commits:
        commit_type, subject = _classify(str(commit["subject"]))
        entry = dict(commit)
        entry["display_subject"] = subject
        entry["requirements"] = _requirement_ids(commit)
        groups.setdefault(commit_type, []).append(entry)
    return groups


def _ordered_types(groups: dict[str, list[dict[str, object]]]) -> list[str]:
    ordered = [commit_type for commit_type in _TYPE_ORDER if groups.get(commit_type)]
    if groups.get("other"):
        ordered.append("other")
    return ordered


def _render(version: str | None, groups: dict[str, list[dict[str, object]]]) -> str:
    lines = ["# Changelog", "", f"## {version or 'Unreleased'}", ""]
    ordered = _ordered_types(groups)
    if not ordered:
        lines.append("_No commits._")
        lines.append("")
        return "\n".join(lines)
    for commit_type in ordered:
        lines.append(f"### {commit_type}")
        lines.append("")
        for entry in groups[commit_type]:
            line = f"- {entry['display_subject']} (`{entry['short_sha']}`)"
            requirements = entry["requirements"]
            if requirements:
                line += " " + ", ".join(requirements)
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def generate_changelog(version: str | None = None, root: Path = Path(".")) -> str:
    """Render a Markdown changelog for the project history."""
    root = Path(root)
    commits = _read_commits(root, version)
    if commits is None:
        return "\n".join(
            [
                "# Changelog",
                "",
                f"## {version or 'Unreleased'}",
                "",
                "_No git history available._",
                "",
            ]
        )
    return _render(version, _group(commits))


def write_changelog(
    version: str | None,
    output: Path | None = None,
    root: Path = Path("."),
) -> Path:
    """Write the changelog and return the path to the written file."""
    root = Path(root)
    destination = Path(output) if output is not None else root / _DEFAULT_OUTPUT
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = generate_changelog(version, root)
    if not text.endswith("\n"):
        text += "\n"
    destination.write_text(text, encoding="utf-8")
    return destination
