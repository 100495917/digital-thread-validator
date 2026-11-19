"""Conventional-commit and requirement-reference checks for git history."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .findings import Finding, sort_findings

_CONVENTIONAL = re.compile(
    r"^(feat|fix|perf|refactor|docs|test|build|ci|chore|style|revert)(\([^)]+\))?: .+"
)
_REQUIREMENT = re.compile(r"\bREQ-\d+\b")
_TRACE_PREFIXES = ("requirements/", "models/", "src/")
_RECORD = "\x1e"
_BODY_END = "\x1d"
_FIELD = "\x1f"
_SHORT_SHA_LENGTH = 7


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


def _commits(root: Path, range_spec: str) -> list[dict[str, object]] | None:
    output = _git(
        root,
        "log",
        f"--format={_RECORD}%H{_FIELD}%s{_FIELD}%b{_BODY_END}",
        "--name-only",
        range_spec,
    )
    if output is None:
        return None
    commits: list[dict[str, object]] = []
    for record in output.split(_RECORD):
        if not record.strip():
            continue
        header, _, files_part = record.partition(_BODY_END)
        fields = header.split(_FIELD, 2)
        if len(fields) < 2:
            continue
        sha = fields[0].strip()
        subject = fields[1].strip()
        body = fields[2] if len(fields) > 2 else ""
        files = [line.strip() for line in files_part.splitlines() if line.strip()]
        commits.append(
            {
                "sha": sha,
                "short_sha": sha[:_SHORT_SHA_LENGTH],
                "subject": subject,
                "body": body,
                "files": files,
            }
        )
    return commits


def _touches_traced_artifacts(files: list[str]) -> bool:
    return any(path.startswith(_TRACE_PREFIXES) for path in files)


def check_commits(
    range_spec: str = "HEAD~1..HEAD",
    root: Path = Path("."),
    strict: bool = False,
) -> list[Finding]:
    """Validate commit subjects and requirement references in ``range_spec``."""
    commits = _commits(Path(root), range_spec)
    if not commits:
        return []

    severity = "error" if strict else "warning"
    findings: list[Finding] = []
    for commit in commits:
        sha = str(commit["short_sha"])
        subject = str(commit["subject"])
        if _CONVENTIONAL.match(subject) is None:
            findings.append(
                Finding(
                    path=sha,
                    rule="CC-001",
                    severity=severity,
                    message=f'Commit subject is not a conventional commit: "{subject}"',
                )
            )
        if _touches_traced_artifacts(commit["files"]):
            text = f"{subject}\n{commit['body']}"
            if _REQUIREMENT.search(text) is None:
                findings.append(
                    Finding(
                        path=sha,
                        rule="CC-002",
                        severity=severity,
                        message=(
                            "Commit touching requirements/, models/, or src/ does not "
                            f'reference a requirement ID: "{subject}"'
                        ),
                    )
                )
    return sort_findings(findings)
