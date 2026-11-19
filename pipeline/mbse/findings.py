"""Shared finding model used by every validation and traceability check."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Finding:
    """A single validation or traceability result.

    ``severity`` is either ``"error"`` or ``"warning"``. ``requirement`` is the
    requirement the finding belongs to, when applicable.
    """

    path: str
    rule: str
    severity: str
    message: str
    requirement: str | None = None


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Return findings ordered deterministically by path, rule, and message."""
    return sorted(findings, key=lambda finding: (finding.path, finding.rule, finding.message))
