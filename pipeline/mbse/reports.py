"""Aggregate pipeline reporting and generated documentation pages.

The module recomputes validation, traceability, and requirement coverage from
the source artifacts and reads the machine-readable reports produced by earlier
pipeline stages. Missing reports degrade to zeros or ``not-run`` so the report
command always produces a deterministic summary.
"""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import trace as trace_module
from . import validate_reqs
from .loaders import LoadError, load_requirements
from .reqcov import compute_requirements_coverage

REPORT_DIRECTORY = Path("build") / "reports"
GENERATED_DIRECTORY = Path("docs") / "generated"
PUBLISHED_DIRECTORY = Path("docs") / "reports"

_IMPACT_CLASSES = (
    "directly_changed",
    "impacted",
    "needs_review",
    "needs_retest",
)

_SECURITY_SEVERITIES = ("critical", "high", "medium", "low")

_THREAD_SECTIONS = (
    ("added", "Added nodes"),
    ("removed", "Removed nodes"),
    ("modified", "Modified nodes"),
    ("stale", "Stale nodes"),
)

# Reports that a generated page may link to, in stable presentation order.
_REPORT_FILES = (
    "summary.json",
    "summary.md",
    "req_quality.json",
    "rtm.csv",
    "rtm.md",
    "rtm.html",
    "junit.xml",
    "coverage.xml",
    "reqcov.json",
    "security.json",
    "security.sarif",
    "sbom.json",
    "impact.json",
    "impact.md",
    "rtm_diff.md",
    "thread_diff.md",
)


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, returning ``{}`` when unavailable or malformed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_text(path: Path) -> str:
    """Read UTF-8 text, returning ``""`` when unavailable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _validation_summary(root: Path) -> dict[str, Any]:
    """Recompute requirement quality metrics from the source artifacts."""
    try:
        requirements = load_requirements(root)
        findings = validate_reqs.validate_requirements(requirements)
        report = validate_reqs.quality_report(requirements, findings)
    except (OSError, LoadError, ValueError, UnicodeDecodeError):
        return {"requirements": 0, "errors": 0, "warnings": 0, "quality_score": 0.0}
    summary = report.get("summary", {})
    return {
        "requirements": _as_int(summary.get("requirements")),
        "errors": _as_int(summary.get("errors")),
        "warnings": _as_int(summary.get("warnings")),
        "quality_score": round(_as_float(summary.get("score")), 1),
    }


def _traceability_summary(root: Path) -> dict[str, float]:
    """Recompute traceability and verification coverage from source artifacts."""
    empty = {"traceability_coverage": 0.0, "verification_coverage": 0.0}
    try:
        links = trace_module.build_links(root)
        metrics = trace_module.compute_metrics(links, root)
    except (OSError, LoadError, ValueError, UnicodeDecodeError):
        return empty
    return {
        "traceability_coverage": round(_as_float(metrics.get("traceability_coverage")), 1),
        "verification_coverage": round(_as_float(metrics.get("verification_coverage")), 1),
    }


def _junit_totals(path: Path) -> dict[str, int]:
    """Return test totals from a JUnit XML report, zeros when unavailable."""
    empty = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return empty

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return empty
    for suite in suites:
        for key in totals:
            totals[key] += _as_int(suite.get(key))
    total = totals["tests"]
    failed = totals["failures"] + totals["errors"]
    skipped = totals["skipped"]
    return {
        "total": total,
        "passed": max(total - failed - skipped, 0),
        "failed": failed,
        "skipped": skipped,
    }


def _coverage_percent(path: Path) -> float:
    """Return line coverage percent from a Cobertura ``coverage.xml``."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return 0.0
    rate = root.get("line-rate")
    if rate is not None:
        return round(_as_float(rate) * 100.0, 1)
    valid = _as_int(root.get("lines-valid"))
    covered = _as_int(root.get("lines-covered"))
    if valid:
        return round(100.0 * covered / valid, 1)
    return 0.0


def _security_summary(path: Path) -> dict[str, Any]:
    """Read the security report summary, degrading to ``not-run``."""
    summary = _read_json(path).get("summary", {})
    by_severity = summary.get("by_severity", {}) if isinstance(summary, dict) else {}
    by_tool = summary.get("by_tool", {}) if isinstance(summary, dict) else {}
    if not isinstance(by_severity, dict):
        by_severity = {}
    if not isinstance(by_tool, dict):
        by_tool = {}
    status = str(summary.get("status", "not-run")) if isinstance(summary, dict) else "not-run"
    return {
        "status": status or "not-run",
        "total": _as_int(summary.get("total")) if isinstance(summary, dict) else 0,
        **{severity: _as_int(by_severity.get(severity)) for severity in _SECURITY_SEVERITIES},
        "tools": sorted(str(tool) for tool in by_tool),
    }


def _impact_summary(path: Path) -> dict[str, Any]:
    """Read the impact report summary, degrading to ``not-run``."""
    raw = _read_json(path)
    if not raw:
        return {"status": "not-run"}
    summary = raw.get("summary", {})
    risk = raw.get("risk", {})
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(risk, dict):
        risk = {}
    entry: dict[str, Any] = {
        "risk": str(risk.get("level", "low")) or "low",
        "changed_files": _as_int(summary.get("changed_files")),
    }
    for name in _IMPACT_CLASSES:
        entry[name] = _as_int(summary.get(name))
    return entry


def _thread_summary(root: Path) -> dict[str, int]:
    """Count graph nodes/edges and parse ``thread_diff.md`` section counts."""
    counts = {"nodes": 0, "edges": 0, "added": 0, "removed": 0, "modified": 0, "stale": 0}
    graph = _read_json(root / "digital_thread" / "thread.json")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    counts["nodes"] = len(nodes) if isinstance(nodes, (list, dict)) else 0
    counts["edges"] = len(edges) if isinstance(edges, (list, dict)) else 0

    text = _read_text(root / REPORT_DIRECTORY / "thread_diff.md")
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = next(
                (key for key, label in _THREAD_SECTIONS if label == heading),
                None,
            )
            continue
        if current is None or not line.startswith("- "):
            continue
        item = line[2:].strip()
        if not item or item.lower() == "none":
            continue
        counts[current] += 1
    return counts


def _requirements_coverage(root: Path) -> float:
    """Return approved requirement verification coverage percentage."""
    try:
        coverage = compute_requirements_coverage(root)
    except (OSError, LoadError, ValueError, UnicodeDecodeError):
        return 0.0
    summary = coverage.get("summary", {})
    return round(_as_float(summary.get("coverage")), 1)


def build_summary(root: Path = Path(".")) -> dict[str, Any]:
    """Build the deterministic aggregate pipeline summary."""
    root = Path(root)
    reports = root / REPORT_DIRECTORY

    validation = _validation_summary(root)
    traceability = _traceability_summary(root)
    tests = _junit_totals(reports / "junit.xml")
    tests["requirements_coverage"] = _requirements_coverage(root)
    coverage = {"percent": _coverage_percent(reports / "coverage.xml")}
    security = _security_summary(reports / "security.json")
    impact = _impact_summary(reports / "impact.json")
    thread = _thread_summary(root)

    status = (
        "pass"
        if validation["errors"] == 0 and tests["failed"] == 0 and security["status"] != "failed"
        else "fail"
    )

    return {
        "status": status,
        "validation": validation,
        "traceability": traceability,
        "tests": tests,
        "coverage": coverage,
        "security": security,
        "impact": impact,
        "thread": thread,
    }


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> list[str]:
    """Render a deterministic Markdown table."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def _report_links(root: Path, names: tuple[str, ...] = _REPORT_FILES) -> list[str]:
    """Render links to report files that exist under ``build/reports``."""
    reports = root / REPORT_DIRECTORY
    lines = ["## Reports", ""]
    linked = 0
    for name in names:
        if name in {"summary.json", "summary.md"} or (reports / name).is_file():
            lines.append(f"- [{name}](../reports/{name})")
            linked += 1
    if not linked:
        lines.append("_No reports produced yet._")
    return lines


def _badge(status: str) -> str:
    state = "passing-brightgreen" if status == "pass" else "failing-red"
    return f"![pipeline](https://img.shields.io/badge/pipeline-{state})"


def _summary_markdown(summary: dict[str, Any], root: Path) -> str:
    validation = summary["validation"]
    traceability = summary["traceability"]
    tests = summary["tests"]
    coverage = summary["coverage"]
    security = summary["security"]
    impact = summary["impact"]
    thread = summary["thread"]

    lines = [
        _badge(summary["status"]),
        "",
        "# Pipeline summary",
        "",
        f"**Status:** {summary['status']}",
        "",
        "## Validation",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Requirements", validation["requirements"]),
                ("Errors", validation["errors"]),
                ("Warnings", validation["warnings"]),
                ("Quality score", validation["quality_score"]),
            ],
        ),
        "",
        "## Traceability",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Traceability coverage (%)", traceability["traceability_coverage"]),
                ("Verification coverage (%)", traceability["verification_coverage"]),
            ],
        ),
        "",
        "## Tests",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Total", tests["total"]),
                ("Passed", tests["passed"]),
                ("Failed", tests["failed"]),
                ("Skipped", tests["skipped"]),
                ("Requirements coverage (%)", tests["requirements_coverage"]),
            ],
        ),
        "",
        "## Coverage",
        "",
        *_table(("Metric", "Value"), [("Line coverage (%)", coverage["percent"])]),
        "",
        "## Security",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Status", security["status"]),
                ("Total findings", security["total"]),
                *((severity.capitalize(), security[severity]) for severity in _SECURITY_SEVERITIES),
                ("Tools", ", ".join(security["tools"]) or "none"),
            ],
        ),
        "",
        "## Impact",
        "",
    ]
    if "status" in impact:
        lines.append("_Impact analysis has not been run._")
    else:
        lines.extend(
            _table(
                ("Metric", "Value"),
                [
                    ("Risk", impact["risk"]),
                    ("Changed files", impact["changed_files"]),
                    ("Directly changed", impact["directly_changed"]),
                    ("Impacted", impact["impacted"]),
                    ("Needs review", impact["needs_review"]),
                    ("Needs retest", impact["needs_retest"]),
                ],
            )
        )
    lines.extend(
        [
            "",
            "## Digital thread",
            "",
            *_table(
                ("Metric", "Value"),
                [
                    ("Nodes", thread["nodes"]),
                    ("Edges", thread["edges"]),
                    ("Added", thread["added"]),
                    ("Removed", thread["removed"]),
                    ("Modified", thread["modified"]),
                    ("Stale", thread["stale"]),
                ],
            ),
            "",
            *_report_links(root),
            "",
        ]
    )
    return "\n".join(lines)


def _summary_page(summary: dict[str, Any], root: Path) -> str:
    validation = summary["validation"]
    traceability = summary["traceability"]
    tests = summary["tests"]
    security = summary["security"]
    impact = summary["impact"]
    thread = summary["thread"]

    lines = [
        _badge(summary["status"]),
        "",
        "# Pipeline summary",
        "",
        f"**Status:** {summary['status']}",
        "",
        "## Validation and traceability",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Requirements", validation["requirements"]),
                ("Validation errors", validation["errors"]),
                ("Validation warnings", validation["warnings"]),
                ("Quality score", validation["quality_score"]),
                ("Traceability coverage (%)", traceability["traceability_coverage"]),
                ("Verification coverage (%)", traceability["verification_coverage"]),
            ],
        ),
        "",
        "## Tests and coverage",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Total tests", tests["total"]),
                ("Passed", tests["passed"]),
                ("Failed", tests["failed"]),
                ("Skipped", tests["skipped"]),
                ("Requirements coverage (%)", tests["requirements_coverage"]),
                ("Line coverage (%)", summary["coverage"]["percent"]),
            ],
        ),
        "",
        "## Security and impact",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Security status", security["status"]),
                ("Security findings", security["total"]),
                (
                    "Impact risk",
                    "not-run" if "status" in impact else impact["risk"],
                ),
                (
                    "Needs retest",
                    0 if "status" in impact else impact["needs_retest"],
                ),
                ("Thread nodes", thread["nodes"]),
                ("Thread edges", thread["edges"]),
            ],
        ),
        "",
        *_report_links(root),
        "",
    ]
    return "\n".join(lines)


def _tests_page(summary: dict[str, Any], root: Path) -> str:
    tests = summary["tests"]
    lines = [
        "# Test results",
        "",
        "Test totals are read from the JUnit report; requirement coverage comes",
        "from the requirement-tagged test results.",
        "",
        "## Totals",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Total", tests["total"]),
                ("Passed", tests["passed"]),
                ("Failed", tests["failed"]),
                ("Skipped", tests["skipped"]),
            ],
        ),
        "",
        "## Coverage",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Requirements coverage (%)", tests["requirements_coverage"]),
                ("Line coverage (%)", summary["coverage"]["percent"]),
            ],
        ),
        "",
        *_report_links(
            root,
            ("junit.xml", "coverage.xml", "reqcov.json", "req_results.json"),
        ),
        "",
    ]
    return "\n".join(lines)


def _security_page(summary: dict[str, Any], root: Path) -> str:
    security = summary["security"]
    lines = [
        "# Security",
        "",
        f"**Gate status:** {security['status']}",
        "",
        "## Findings by severity",
        "",
        *_table(
            ("Severity", "Count"),
            [
                ("Total", security["total"]),
                *((severity.capitalize(), security[severity]) for severity in _SECURITY_SEVERITIES),
            ],
        ),
        "",
        "## Scanners",
        "",
    ]
    if security["tools"]:
        lines.extend(f"- {tool}" for tool in security["tools"])
    else:
        lines.append("_No scanner report available._")
    lines.extend(
        [
            "",
            *_report_links(root, ("security.json", "security.sarif", "sbom.json")),
            "",
        ]
    )
    return "\n".join(lines)


def _impact_page(summary: dict[str, Any], root: Path) -> str:
    impact = summary["impact"]
    lines = ["# Impact of last change", ""]
    if "status" in impact:
        lines.extend(
            [
                "_Impact analysis has not been run._",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"**Risk level:** {impact['risk']}",
                "",
                *_table(
                    ("Metric", "Value"),
                    [
                        ("Changed files", impact["changed_files"]),
                        ("Directly changed", impact["directly_changed"]),
                        ("Impacted", impact["impacted"]),
                        ("Needs review", impact["needs_review"]),
                        ("Needs retest", impact["needs_retest"]),
                    ],
                ),
                "",
            ]
        )
    lines.extend(
        [
            *_report_links(root, ("impact.json", "impact.md", "rtm_diff.md")),
            "",
        ]
    )
    return "\n".join(lines)


def _metrics_page(summary: dict[str, Any], root: Path) -> str:
    validation = summary["validation"]
    traceability = summary["traceability"]
    tests = summary["tests"]
    security = summary["security"]
    impact = summary["impact"]
    thread = summary["thread"]
    lines = [
        "# Metrics",
        "",
        "Current pipeline counts. DORA metrics are not part of this report.",
        "",
        "## Pipeline counts",
        "",
        *_table(
            ("Metric", "Value"),
            [
                ("Requirements", validation["requirements"]),
                ("Validation errors", validation["errors"]),
                ("Validation warnings", validation["warnings"]),
                ("Quality score", validation["quality_score"]),
                ("Traceability coverage (%)", traceability["traceability_coverage"]),
                ("Verification coverage (%)", traceability["verification_coverage"]),
                ("Total tests", tests["total"]),
                ("Failed tests", tests["failed"]),
                ("Requirements coverage (%)", tests["requirements_coverage"]),
                ("Line coverage (%)", summary["coverage"]["percent"]),
                ("Security findings", security["total"]),
                (
                    "Impact risk",
                    "not-run" if "status" in impact else impact["risk"],
                ),
                ("Thread nodes", thread["nodes"]),
                ("Thread edges", thread["edges"]),
            ],
        ),
        "",
        *_report_links(root),
        "",
    ]
    return "\n".join(lines)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _copy_reports(root: Path) -> list[Path]:
    """Copy every file in ``build/reports`` to ``docs/reports``."""
    source = root / REPORT_DIRECTORY
    destination = root / PUBLISHED_DIRECTORY
    copied: list[Path] = []
    if not source.is_dir():
        return copied
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(target)
    return copied


def write_summary(root: Path = Path(".")) -> dict[str, Any]:
    """Write summary reports and generated site pages; return written paths."""
    root = Path(root)
    summary = build_summary(root)
    reports = root / REPORT_DIRECTORY
    generated = root / GENERATED_DIRECTORY

    summary_json = _write(
        reports / "summary.json",
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
    )
    summary_md = _write(reports / "summary.md", _summary_markdown(summary, root))

    site_pages = [
        _write(generated / "summary.md", _summary_page(summary, root)),
        _write(generated / "tests.md", _tests_page(summary, root)),
        _write(generated / "security.md", _security_page(summary, root)),
        _write(generated / "impact.md", _impact_page(summary, root)),
        _write(generated / "metrics.md", _metrics_page(summary, root)),
    ]

    copied = _copy_reports(root)

    return {
        "summary_json": summary_json,
        "summary_md": summary_md,
        "site_pages": sorted(site_pages, key=lambda path: path.as_posix()),
        "reports_copied": sorted(copied, key=lambda path: path.as_posix()),
    }
