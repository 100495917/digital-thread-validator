"""Requirements quality checks and quality report generation.

Implements the Phase 3 requirement rules ``RQ-001`` through ``RQ-008`` from
PLAN.md. Every violation produces one :class:`~mbse.findings.Finding`; the
returned list is deterministically sorted by ``(path, rule, message)``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from mbse.findings import Finding, sort_findings
from mbse.loaders import Requirement

RULE_COUNT = 8

ID_PATTERN = re.compile(r"^REQ-\d{3}$")
SHALL_PATTERN = re.compile(r"\bshall\b", re.IGNORECASE)

# Ambiguous or unverifiable wording banned by RQ-003.
BANNED_TERMS: tuple[str, ...] = (
    "fast",
    "quickly",
    "user-friendly",
    "easy",
    "flexible",
    "appropriate",
    "as needed",
    "etc.",
    "and/or",
    "approximately",
    "TBD",
)
_BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)) for term in BANNED_TERMS
)

# RQ-004: a number adjacent to one of the supported engineering units.
_NUMBER_UNIT_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)?\s*"
    r"(?:(?:°C/s|°C|req/s|requests/s|milliseconds?|seconds?|minutes?|hours?|"
    r"ms|sec|min|h|s|MB|GB|mm|kg)\b|%)",
    re.IGNORECASE,
)

MAX_TEXT_LENGTH = 300


def _finding(requirement: Requirement, rule: str, severity: str, message: str) -> Finding:
    """Build a finding tied to ``requirement``."""
    return Finding(
        path=str(requirement.path),
        rule=rule,
        severity=severity,
        message=message,
        requirement=requirement.id,
    )


def _text(requirement: Requirement) -> str:
    """Return the requirement text, tolerating ``None``-like values."""
    return requirement.text or ""


def _cycle_path(requirement: Requirement, by_id: dict[str, Requirement]) -> list[str] | None:
    """Return the parent cycle reachable from ``requirement``, if any.

    The returned list is the cycle repeated at the end, e.g.
    ``["REQ-001", "REQ-002", "REQ-001"]``.
    """
    chain: list[str] = []
    current: str | None = requirement.id
    while current:
        if current in chain:
            return chain[chain.index(current) :] + [current]
        chain.append(current)
        parent_requirement = by_id.get(current)
        if parent_requirement is None:
            return None
        current = (parent_requirement.parent or "").strip() or None
    return None


def _validate_requirement(
    requirement: Requirement,
    id_counts: Counter[str],
    by_id: dict[str, Requirement],
) -> list[Finding]:
    """Run RQ-001..RQ-008 against one requirement."""
    findings: list[Finding] = []
    text = _text(requirement)
    requirement_id = requirement.id or ""

    # RQ-001: ID format, filename agreement, uniqueness.
    if not ID_PATTERN.match(requirement_id):
        findings.append(
            _finding(
                requirement,
                "RQ-001",
                "error",
                f"id {requirement_id!r} does not match the REQ-\\d{{3}} pattern",
            )
        )
    filename = Path(str(requirement.path)).name
    if Path(filename).stem != requirement_id:
        findings.append(
            _finding(
                requirement,
                "RQ-001",
                "error",
                f"id {requirement_id!r} does not match file name {filename!r}",
            )
        )
    if id_counts[requirement_id] > 1:
        findings.append(
            _finding(
                requirement,
                "RQ-001",
                "error",
                f"duplicate id {requirement_id!r} ({id_counts[requirement_id]} files)",
            )
        )

    # RQ-002: exactly one normative statement.
    shall_count = len(SHALL_PATTERN.findall(text))
    if shall_count != 1:
        findings.append(
            _finding(
                requirement,
                "RQ-002",
                "error",
                f"text contains {shall_count} occurrence(s) of 'shall'; "
                "exactly one normative statement is required",
            )
        )

    # RQ-003: no ambiguous terms.
    for term, pattern in _BANNED_PATTERNS:
        if pattern.search(text):
            findings.append(
                _finding(
                    requirement,
                    "RQ-003",
                    "error",
                    f"ambiguous term {term!r} in text",
                )
            )

    # RQ-004: performance requirements need a measurable value and unit.
    is_performance = (requirement.type or "").strip().lower() == "performance"
    if is_performance and not _NUMBER_UNIT_PATTERN.search(text):
        findings.append(
            _finding(
                requirement,
                "RQ-004",
                "error",
                "performance requirement lacks a measurable value with a unit",
            )
        )

    # RQ-005: mandatory fields.
    for field_name in ("owner", "priority", "verification"):
        value = getattr(requirement, field_name)
        if value is None or not str(value).strip():
            findings.append(
                _finding(
                    requirement,
                    "RQ-005",
                    "error",
                    f"missing required field {field_name!r}",
                )
            )

    # RQ-006: parent exists and the parent chain is acyclic.
    parent = (requirement.parent or "").strip()
    if parent and parent not in by_id:
        findings.append(
            _finding(
                requirement,
                "RQ-006",
                "error",
                f"parent {parent!r} does not exist",
            )
        )
    cycle = _cycle_path(requirement, by_id)
    if cycle is not None:
        findings.append(
            _finding(
                requirement,
                "RQ-006",
                "error",
                "parent chain contains a cycle: " + " -> ".join(cycle),
            )
        )

    # RQ-007: concise text.
    if len(text) > MAX_TEXT_LENGTH:
        findings.append(
            _finding(
                requirement,
                "RQ-007",
                "warning",
                f"text length {len(text)} exceeds {MAX_TEXT_LENGTH} characters",
            )
        )

    # RQ-008: approved requirements cannot defer verification.
    if (requirement.status or "").strip().lower() == "approved" and str(
        requirement.verification or ""
    ).strip().upper() == "TBD":
        findings.append(
            _finding(
                requirement,
                "RQ-008",
                "error",
                "approved requirement has verification 'TBD'",
            )
        )

    return findings


def validate_requirements(requirements: Iterable[Requirement]) -> list[Finding]:
    """Validate requirements quality, returning deterministically sorted findings."""
    requirement_list = list(requirements)
    id_counts = Counter(requirement.id for requirement in requirement_list)
    by_id: dict[str, Requirement] = {}
    for requirement in requirement_list:
        by_id.setdefault(requirement.id, requirement)

    findings: list[Finding] = []
    for requirement in requirement_list:
        findings.extend(_validate_requirement(requirement, id_counts, by_id))
    return sort_findings(findings)


def quality_report(requirements: Iterable[Requirement], findings: Iterable[Finding]) -> dict:
    """Build the deterministic requirement quality report."""
    requirement_list = sorted(requirements, key=lambda item: (item.id, item.path))
    finding_list = list(findings)

    errors = sum(1 for finding in finding_list if finding.severity == "error")
    warnings = sum(1 for finding in finding_list if finding.severity == "warning")

    failed_rules: dict[str, set[str]] = {}
    for finding in finding_list:
        if finding.requirement is None or not finding.rule.startswith("RQ-"):
            continue
        failed_rules.setdefault(finding.requirement, set()).add(finding.rule)

    entries: list[dict] = []
    scores: list[float] = []
    for requirement in requirement_list:
        failed = sorted(failed_rules.get(requirement.id, set()))
        score = round((RULE_COUNT - len(failed)) / RULE_COUNT * 100, 1)
        scores.append(score)
        entries.append(
            {
                "id": requirement.id,
                "title": requirement.title,
                "score": score,
                "failed_rules": failed,
            }
        )

    overall = round(sum(scores) / len(scores), 1) if scores else 0.0
    return {
        "summary": {
            "requirements": len(requirement_list),
            "score": overall,
            "errors": errors,
            "warnings": warnings,
        },
        "requirements": entries,
    }


def write_quality_report(
    requirements: Iterable[Requirement],
    findings: Iterable[Finding],
    root: Path = Path("."),
) -> Path:
    """Write ``build/reports/req_quality.json`` and return its path."""
    report = quality_report(requirements, findings)
    path = Path(root) / "build" / "reports" / "req_quality.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
