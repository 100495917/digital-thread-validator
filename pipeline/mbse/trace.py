"""Traceability checks, coverage metrics, and requirement traceability matrix output."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path

from .findings import Finding, sort_findings
from .loaders import (
    Requirement,
    SystemModel,
    load_code_tags,
    load_model,
    load_requirements,
    load_test_tags,
)

RTM_HEADERS = (
    "Req ID",
    "Title",
    "Priority",
    "Model elements",
    "Code",
    "Tests",
    "Last result",
    "Status",
)

_REPORT_DIRECTORY = Path("build") / "reports"
_RESULTS_PATH = _REPORT_DIRECTORY / "req_results.json"

_PASSED_OUTCOMES = {"passed", "pass", "success", "succeeded"}
_FAILED_OUTCOMES = {"failed", "fail", "error", "errored"}


@dataclass(frozen=True)
class TraceLink:
    """All trace artifacts associated with a single requirement."""

    requirement: Requirement
    model_elements: tuple[str, ...]
    code_paths: tuple[str, ...]
    test_paths: tuple[str, ...]


def _normalise(value: object) -> str:
    return str(value or "").strip().lower()


def _satisfying_elements(model: SystemModel) -> dict[str, set[str]]:
    satisfiers: dict[str, set[str]] = {}
    for element in model.elements:
        for requirement_id in element.satisfies:
            satisfiers.setdefault(requirement_id, set()).add(element.id)
    return satisfiers


def _links_from(
    requirements: list[Requirement],
    model: SystemModel,
    code_tags: dict[str, tuple[str, ...]],
    test_tags: dict[str, tuple[str, ...]],
) -> list[TraceLink]:
    satisfiers = _satisfying_elements(model)
    links = [
        TraceLink(
            requirement=requirement,
            model_elements=tuple(sorted(satisfiers.get(requirement.id, set()))),
            code_paths=tuple(sorted(code_tags.get(requirement.id, ()))),
            test_paths=tuple(sorted(test_tags.get(requirement.id, ()))),
        )
        for requirement in requirements
    ]
    return sorted(links, key=lambda link: link.requirement.id)


def build_links(root: Path = Path(".")) -> list[TraceLink]:
    """Build the requirement-to-artifact link table for the project."""
    root = Path(root)
    return _links_from(
        load_requirements(root),
        load_model(root),
        load_code_tags(root),
        load_test_tags(root),
    )


def _unknown_reference_findings(
    requirements: list[Requirement],
    model: SystemModel,
    code_tags: dict[str, tuple[str, ...]],
    test_tags: dict[str, tuple[str, ...]],
) -> list[Finding]:
    known = {requirement.id for requirement in requirements}
    sources: dict[str, set[str]] = {}
    paths: dict[str, str] = {}

    def record(unknown_id: str, source: str, path: str) -> None:
        sources.setdefault(unknown_id, set()).add(source)
        paths.setdefault(unknown_id, path)

    for element in model.elements:
        for requirement_id in element.satisfies:
            if requirement_id not in known:
                record(
                    requirement_id,
                    f"model element {element.id}",
                    str(model.path),
                )

    for requirement_id, code_paths in sorted(code_tags.items()):
        if requirement_id not in known:
            for code_path in code_paths:
                record(requirement_id, f"code tag {code_path}", code_path)

    for requirement_id, test_paths in sorted(test_tags.items()):
        if requirement_id not in known:
            for test_path in test_paths:
                record(requirement_id, f"test tag {test_path}", test_path)

    findings: list[Finding] = []
    for unknown_id in sorted(sources):
        detail = ", ".join(sorted(sources[unknown_id]))
        findings.append(
            Finding(
                path=paths[unknown_id],
                rule="TRC-004",
                severity="error",
                message=f"{unknown_id} is referenced by {detail} but no requirement defines it",
            )
        )
    return findings


def check_traceability(root: Path = Path(".")) -> list[Finding]:
    """Return traceability findings for requirements, model, code, and tests."""
    root = Path(root)
    requirements = load_requirements(root)
    model = load_model(root)
    code_tags = load_code_tags(root)
    test_tags = load_test_tags(root)
    links = _links_from(requirements, model, code_tags, test_tags)

    findings: list[Finding] = []
    for link in links:
        requirement = link.requirement
        status = _normalise(requirement.status)
        verification = _normalise(requirement.verification)

        if status == "approved":
            if not link.model_elements:
                findings.append(
                    Finding(
                        path=requirement.path,
                        rule="TRC-001",
                        severity="error",
                        message=(
                            f"{requirement.id} is approved but has no satisfying model element"
                        ),
                        requirement=requirement.id,
                    )
                )

            if not link.code_paths:
                severity = "warning" if verification in {"inspection", "analysis"} else "error"
                findings.append(
                    Finding(
                        path=requirement.path,
                        rule="TRC-002",
                        severity=severity,
                        message=(f"{requirement.id} is approved but no code module implements it"),
                        requirement=requirement.id,
                    )
                )

            if verification == "test" and not link.test_paths:
                findings.append(
                    Finding(
                        path=requirement.path,
                        rule="TRC-003",
                        severity="error",
                        message=(
                            f"{requirement.id} is approved with verification 'test' "
                            "but has no requirement-tagged test"
                        ),
                        requirement=requirement.id,
                    )
                )

            if _normalise(requirement.type) == "security" and not link.test_paths:
                findings.append(
                    Finding(
                        path=requirement.path,
                        rule="TRC-006",
                        severity="error",
                        message=(
                            f"{requirement.id} is an approved security requirement "
                            "but has no requirement-tagged test"
                        ),
                        requirement=requirement.id,
                    )
                )

        if status == "deprecated" and link.test_paths:
            findings.append(
                Finding(
                    path=requirement.path,
                    rule="TRC-005",
                    severity="warning",
                    message=(
                        f"{requirement.id} is deprecated but still has active "
                        f"tests: {', '.join(link.test_paths)}"
                    ),
                    requirement=requirement.id,
                )
            )

    findings.extend(_unknown_reference_findings(requirements, model, code_tags, test_tags))
    return sort_findings(findings)


def _load_results(root: Path) -> dict[str, list[dict[str, object]]]:
    path = root / _RESULTS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    results: dict[str, list[dict[str, object]]] = {}
    for requirement_id, entries in raw.items():
        if isinstance(entries, list):
            results[str(requirement_id)] = [entry for entry in entries if isinstance(entry, dict)]
    return results


def _last_result(requirement_id: str, results: dict[str, list[dict[str, object]]]) -> str:
    entries = results.get(requirement_id)
    if not entries:
        return "not-run"

    outcomes = [_normalise(entry.get("outcome")) for entry in entries]
    has_pass = any(outcome in _PASSED_OUTCOMES for outcome in outcomes)
    has_fail = any(outcome in _FAILED_OUTCOMES for outcome in outcomes)

    if has_pass and has_fail:
        return "mixed"
    if has_fail:
        return "fail"
    if outcomes and all(outcome in _PASSED_OUTCOMES for outcome in outcomes):
        return "pass"
    return "not-run"


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(100.0 * numerator / denominator, 2)


def compute_metrics(links: list[TraceLink], root: Path = Path(".")) -> dict[str, float]:
    """Compute traceability and verification coverage as percentages."""
    root = Path(root)
    results = _load_results(root)
    approved = [link for link in links if _normalise(link.requirement.status) == "approved"]

    full_chain = sum(
        1 for link in approved if link.model_elements and link.code_paths and link.test_paths
    )
    verified = sum(1 for link in approved if _last_result(link.requirement.id, results) == "pass")

    return {
        "traceability_coverage": _percentage(full_chain, len(approved)),
        "verification_coverage": _percentage(verified, len(approved)),
    }


def _display(value: object) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _list_cell(values: tuple[str, ...]) -> str:
    return "; ".join(values)


def _status(link: TraceLink) -> str:
    if _normalise(link.requirement.status) == "deprecated":
        return "deprecated"
    complete = bool(link.model_elements and link.code_paths and link.test_paths)
    return "complete" if complete else "incomplete"


def _rtm_rows(
    links: list[TraceLink], results: dict[str, list[dict[str, object]]]
) -> list[tuple[str, ...]]:
    return [
        (
            _display(link.requirement.id),
            _display(link.requirement.title),
            _display(link.requirement.priority),
            _list_cell(link.model_elements),
            _list_cell(link.code_paths),
            _list_cell(link.test_paths),
            _last_result(link.requirement.id, results),
            _status(link),
        )
        for link in links
    ]


def _write_csv(path: Path, rows: list[tuple[str, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(RTM_HEADERS)
        writer.writerows(rows)


def _write_markdown(path: Path, rows: list[tuple[str, ...]]) -> None:
    def cell(value: str) -> str:
        return value.replace("|", "\\|")

    lines = [
        "# Requirement Traceability Matrix",
        "",
        "| " + " | ".join(RTM_HEADERS) + " |",
        "| " + " | ".join("---" for _ in RTM_HEADERS) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_html(path: Path, rows: list[tuple[str, ...]]) -> None:
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Requirement Traceability Matrix</title>",
        "<style>",
        "body { font-family: sans-serif; margin: 2rem; }",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: left; }",
        "th { background: #f2f2f2; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Requirement Traceability Matrix</h1>",
        "<table>",
        "<thead>",
        "<tr>" + "".join(f"<th>{html.escape(header)}</th>" for header in RTM_HEADERS) + "</tr>",
        "</thead>",
        "<tbody>",
    ]
    for row in rows:
        lines.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>")
    lines.extend(["</tbody>", "</table>", "</body>", "</html>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rtm(root: Path = Path(".")) -> list[Path]:
    """Write the RTM as CSV, Markdown, and HTML; return the sorted paths."""
    root = Path(root)
    links = build_links(root)
    results = _load_results(root)
    rows = _rtm_rows(links, results)

    report_directory = root / _REPORT_DIRECTORY
    report_directory.mkdir(parents=True, exist_ok=True)

    paths = [
        report_directory / "rtm.csv",
        report_directory / "rtm.md",
        report_directory / "rtm.html",
    ]
    _write_csv(paths[0], rows)
    _write_markdown(paths[1], rows)
    _write_html(paths[2], rows)
    return sorted(paths, key=lambda path: str(path))
