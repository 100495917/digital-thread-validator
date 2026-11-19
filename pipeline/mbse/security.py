"""Security scanners, gating, and report generation for the DevSecOps pipeline."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .findings import Finding, sort_findings
from .loaders import load_requirements, load_test_tags

_TIMEOUT = 120
_SEVERITIES = ("critical", "high", "medium", "low")
_TOOL_ORDER = ("gitleaks", "bandit", "semgrep", "pip-audit", "trivy", "checkov")

_SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site",
        "venv",
    }
)

_SECRET_RULES = (
    (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "critical",
        "SEC-SECRET-AWS",
        "possible AWS access key",
    ),
    (
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
        "critical",
        "SEC-SECRET-GITHUB",
        "possible GitHub token",
    ),
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
        "critical",
        "SEC-SECRET-PRIVATE-KEY",
        "private key material",
    ),
    (
        re.compile(
            r"(api[_-]?key|api[_-]?token|secret|password)\s*[:=]\s*"
            r"['\"][^'\"]{12,}['\"]",
            re.IGNORECASE,
        ),
        "high",
        "SEC-SECRET-ASSIGNMENT",
        "hard-coded credential assignment",
    ),
)


@dataclass(frozen=True)
class SecurityFinding:
    """A single finding produced by a security scanner."""

    tool: str
    severity: str
    path: str
    line: int
    message: str
    rule: str


@dataclass(frozen=True)
class ToolResult:
    """The outcome of running one security scanner."""

    tool: str
    status: str
    findings: tuple[SecurityFinding, ...] = ()
    note: str = ""


def _normalise(value: object) -> str:
    return str(value or "").strip().lower()


def _severity(value: object, default: str = "medium") -> str:
    text = _normalise(value)
    if text in _SEVERITIES:
        return text
    mapped = {
        "error": "high",
        "warning": "medium",
        "warn": "medium",
        "info": "low",
        "informational": "low",
        "note": "low",
        "unknown": default,
    }
    return mapped.get(text, default)


def _line(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _display_path(value: object, root: Path) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return path.as_posix()
    return path.as_posix()


def _sort_findings(findings: list[SecurityFinding]) -> tuple[SecurityFinding, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.path,
                finding.line,
                finding.rule,
                finding.message,
                finding.tool,
                finding.severity,
            ),
        )
    )


def _unavailable(tool: str) -> ToolResult:
    return ToolResult(tool=tool, status="unavailable", note=f"{tool} is not installed")


def _invoke(command: list[str], root: Path) -> tuple[subprocess.CompletedProcess[str] | None, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, " ".join(str(exc).split())
    return completed, ""


def _load_json(text: str) -> Any | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _detail(completed: subprocess.CompletedProcess[str]) -> str:
    output = (completed.stderr or completed.stdout or "").strip()
    return " ".join(output.split())[:200]


def _status_for(findings: list[SecurityFinding], gating: set[str]) -> str:
    if any(_severity(finding.severity) in gating for finding in findings):
        return "failed"
    return "passed"


def _iter_scan_files(root: Path):
    try:
        candidates = sorted(root.rglob("*"), key=lambda path: path.as_posix())
    except OSError:
        return
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root)
        except (OSError, ValueError):
            continue
        parts = relative.parts[:-1]
        if any(part in _SKIPPED_DIRECTORIES or part.endswith(".egg-info") for part in parts):
            continue
        yield path


def _fallback_secrets(root: Path) -> ToolResult:
    findings: list[SecurityFinding] = []
    for path in _iter_scan_files(root):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:8192]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        display = _display_path(path, root)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, severity, rule, message in _SECRET_RULES:
                if pattern.search(line):
                    findings.append(
                        SecurityFinding(
                            tool="gitleaks",
                            severity=severity,
                            path=display,
                            line=line_number,
                            message=message,
                            rule=rule,
                        )
                    )
    ordered = _sort_findings(findings)
    status = "failed" if ordered else "passed"
    return ToolResult(tool="gitleaks", status=status, findings=ordered, note="")


def scan_secrets(root: Path = Path(".")) -> ToolResult:
    """Scan for committed secrets with gitleaks, or a built-in fallback."""
    root = Path(root)
    executable = shutil.which("gitleaks")
    if executable is None:
        return _fallback_secrets(root)

    with tempfile.TemporaryDirectory(prefix="mbse-gitleaks-") as directory:
        report_path = Path(directory) / "gitleaks.json"
        command = [
            executable,
            "detect",
            "--no-git",
            "--report-format",
            "json",
            "--report-path",
            str(report_path),
            "--source",
            str(root),
        ]
        completed, error = _invoke(command, root)
        if completed is None:
            return ToolResult(
                tool="gitleaks",
                status="error",
                note=f"gitleaks could not run: {error}",
            )

        data: Any | None = None
        if report_path.is_file():
            try:
                data = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                data = None
        if data is None:
            data = _load_json(completed.stdout)
        if data is None:
            if completed.returncode == 0:
                return ToolResult(tool="gitleaks", status="passed", note="")
            detail = _detail(completed) or "gitleaks produced no JSON report"
            return ToolResult(
                tool="gitleaks",
                status="error",
                note=f"gitleaks failed: {detail}",
            )

        items = data.get("findings") if isinstance(data, dict) else data
        findings: list[SecurityFinding] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                findings.append(
                    SecurityFinding(
                        tool="gitleaks",
                        severity=_severity(
                            item.get("Severity") or item.get("severity"), default="high"
                        ),
                        path=_display_path(item.get("File") or item.get("file"), root),
                        line=_line(item.get("StartLine") or item.get("startLine") or 1),
                        message=str(
                            item.get("Description")
                            or item.get("description")
                            or "potential secret detected"
                        ),
                        rule=str(item.get("RuleID") or item.get("ruleId") or "SEC-SECRET"),
                    )
                )
        ordered = _sort_findings(findings)
        status = "failed" if ordered else "passed"
        return ToolResult(tool="gitleaks", status=status, findings=ordered, note="")


def scan_bandit(root: Path = Path(".")) -> ToolResult:
    """Run bandit over the source trees and fail on HIGH findings."""
    root = Path(root)
    executable = shutil.which("bandit")
    if executable is None:
        return _unavailable("bandit")

    command = [executable, "-r", "src", "pipeline/mbse", "-f", "json", "-q"]
    completed, error = _invoke(command, root)
    if completed is None:
        return ToolResult(tool="bandit", status="error", note=f"bandit could not run: {error}")

    data = _load_json(completed.stdout)
    if data is None:
        if completed.returncode == 0:
            return ToolResult(tool="bandit", status="passed", note="")
        detail = _detail(completed) or "bandit produced no JSON report"
        return ToolResult(tool="bandit", status="error", note=f"bandit failed: {detail}")

    items = data.get("results") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return ToolResult(tool="bandit", status="error", note="bandit produced unexpected JSON")

    findings: list[SecurityFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        findings.append(
            SecurityFinding(
                tool="bandit",
                severity=_severity(item.get("issue_severity")),
                path=_display_path(item.get("filename"), root),
                line=_line(item.get("line_number")),
                message=str(item.get("issue_text") or "bandit finding"),
                rule=str(item.get("test_id") or "B000"),
            )
        )
    ordered = _sort_findings(findings)
    return ToolResult(
        tool="bandit",
        status=_status_for(findings, {"high", "critical"}),
        findings=ordered,
        note="",
    )


def scan_semgrep(root: Path = Path(".")) -> ToolResult:
    """Run semgrep static analysis and fail on HIGH-or-above findings."""
    root = Path(root)
    executable = shutil.which("semgrep")
    if executable is None:
        return _unavailable("semgrep")

    command = [executable, "scan", "--json", "--quiet", "--config", "auto"]
    completed, error = _invoke(command, root)
    if completed is None:
        return ToolResult(tool="semgrep", status="error", note=f"semgrep could not run: {error}")

    data = _load_json(completed.stdout)
    if data is None:
        if completed.returncode == 0:
            return ToolResult(tool="semgrep", status="passed", note="")
        detail = _detail(completed) or "semgrep produced no JSON report"
        return ToolResult(tool="semgrep", status="error", note=f"semgrep failed: {detail}")

    items = data.get("results") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return ToolResult(tool="semgrep", status="error", note="semgrep produced unexpected JSON")

    findings: list[SecurityFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        start = item.get("start") if isinstance(item.get("start"), dict) else {}
        findings.append(
            SecurityFinding(
                tool="semgrep",
                severity=_severity(extra.get("severity")),
                path=_display_path(item.get("path"), root),
                line=_line(start.get("line")),
                message=str(extra.get("message") or item.get("check_id") or "semgrep finding"),
                rule=str(item.get("check_id") or "semgrep"),
            )
        )
    ordered = _sort_findings(findings)
    return ToolResult(
        tool="semgrep",
        status=_status_for(findings, {"high", "critical"}),
        findings=ordered,
        note="",
    )


def scan_dependencies(root: Path = Path(".")) -> ToolResult:
    """Run pip-audit and treat every reported vulnerability as HIGH."""
    root = Path(root)
    executable = shutil.which("pip-audit")
    if executable is None:
        return _unavailable("pip-audit")

    command = [executable, "--format", "json"]
    completed, error = _invoke(command, root)
    if completed is None:
        return ToolResult(
            tool="pip-audit", status="error", note=f"pip-audit could not run: {error}"
        )

    data = _load_json(completed.stdout)
    if data is None:
        if completed.returncode == 0:
            return ToolResult(tool="pip-audit", status="passed", note="")
        detail = _detail(completed) or "pip-audit produced no JSON report"
        return ToolResult(tool="pip-audit", status="error", note=f"pip-audit failed: {detail}")

    if isinstance(data, list):
        dependencies = data
    elif isinstance(data, dict):
        dependencies = data.get("dependencies") or []
    else:
        dependencies = []
    if not isinstance(dependencies, list):
        return ToolResult(
            tool="pip-audit", status="error", note="pip-audit produced unexpected JSON"
        )

    findings: list[SecurityFinding] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        name = str(dependency.get("name") or "")
        version = str(dependency.get("version") or "")
        vulnerabilities = dependency.get("vulns") or dependency.get("vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            continue
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                continue
            aliases = vulnerability.get("aliases")
            alias_list = [str(alias) for alias in aliases] if isinstance(aliases, list) else []
            cve = next(
                (alias for alias in alias_list if alias.upper().startswith("CVE-")),
                None,
            )
            identifier = vulnerability.get("id") or (alias_list[0] if alias_list else None)
            identifier = str(identifier or "unknown")
            rule = cve or identifier
            description = " ".join(str(vulnerability.get("description") or "").split())
            message = f"{name} {version}: {rule}"
            if description:
                message = f"{message} {description}"
            findings.append(
                SecurityFinding(
                    tool="pip-audit",
                    severity="high",
                    path="pyproject.toml",
                    line=0,
                    message=message,
                    rule=rule,
                )
            )
    ordered = _sort_findings(findings)
    return ToolResult(
        tool="pip-audit",
        status="failed" if ordered else "passed",
        findings=ordered,
        note="",
    )


def scan_container(root: Path = Path(".")) -> ToolResult:
    """Run trivy filesystem scanning and fail on CRITICAL vulnerabilities."""
    root = Path(root)
    executable = shutil.which("trivy")
    if executable is None:
        return _unavailable("trivy")

    command = [executable, "fs", "--format", "json", "--quiet", "."]
    completed, error = _invoke(command, root)
    if completed is None:
        return ToolResult(tool="trivy", status="error", note=f"trivy could not run: {error}")

    data = _load_json(completed.stdout)
    if data is None:
        if completed.returncode == 0:
            return ToolResult(tool="trivy", status="passed", note="")
        detail = _detail(completed) or "trivy produced no JSON report"
        return ToolResult(tool="trivy", status="error", note=f"trivy failed: {detail}")

    results = data.get("Results") if isinstance(data, dict) else None
    findings: list[SecurityFinding] = []
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            target = str(result.get("Target") or "")
            vulnerabilities = result.get("Vulnerabilities") or []
            if not isinstance(vulnerabilities, list):
                continue
            for vulnerability in vulnerabilities:
                if not isinstance(vulnerability, dict):
                    continue
                package = str(vulnerability.get("PkgName") or "")
                installed = str(vulnerability.get("InstalledVersion") or "")
                title = str(
                    vulnerability.get("Title")
                    or vulnerability.get("Description")
                    or "vulnerability"
                )
                identifier = str(vulnerability.get("VulnerabilityID") or "unknown")
                findings.append(
                    SecurityFinding(
                        tool="trivy",
                        severity=_severity(vulnerability.get("Severity")),
                        path=_display_path(target, root),
                        line=0,
                        message=f"{package} {installed}: {title}".strip(),
                        rule=identifier,
                    )
                )
    ordered = _sort_findings(findings)
    return ToolResult(
        tool="trivy",
        status=_status_for(findings, {"critical"}),
        findings=ordered,
        note="",
    )


def scan_iac(root: Path = Path(".")) -> ToolResult:
    """Run checkov over ``infra/`` and fail on HIGH-or-above findings."""
    root = Path(root)
    executable = shutil.which("checkov")
    if executable is None:
        return _unavailable("checkov")

    command = [executable, "-d", "infra", "--output", "json", "--quiet"]
    completed, error = _invoke(command, root)
    if completed is None:
        return ToolResult(tool="checkov", status="error", note=f"checkov could not run: {error}")

    data = _load_json(completed.stdout)
    if data is None:
        if completed.returncode == 0:
            return ToolResult(tool="checkov", status="passed", note="")
        detail = _detail(completed) or "checkov produced no JSON report"
        return ToolResult(tool="checkov", status="error", note=f"checkov failed: {detail}")

    reports = data if isinstance(data, list) else [data]
    findings: list[SecurityFinding] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        results = report.get("results")
        failed_checks: list[Any] = []
        if isinstance(results, dict):
            failed_checks = results.get("failed_checks") or []
        elif isinstance(results, list):
            for entry in results:
                if isinstance(entry, dict):
                    failed_checks.extend(entry.get("failed_checks") or [])
        if not isinstance(failed_checks, list):
            continue
        for check in failed_checks:
            if not isinstance(check, dict):
                continue
            line_range = check.get("file_line_range")
            line = _line(line_range[0]) if isinstance(line_range, list) and line_range else 0
            findings.append(
                SecurityFinding(
                    tool="checkov",
                    severity=_severity(check.get("severity")),
                    path=_display_path(check.get("file_path"), root),
                    line=line,
                    message=str(check.get("check_name") or check.get("check_id") or "checkov"),
                    rule=str(check.get("check_id") or "CKV"),
                )
            )
    ordered = _sort_findings(findings)
    return ToolResult(
        tool="checkov",
        status=_status_for(findings, {"high", "critical"}),
        findings=ordered,
        note="",
    )


def check_security_requirements(root: Path = Path(".")) -> list[Finding]:
    """Report approved security requirements without requirement-tagged tests."""
    root = Path(root)
    test_tags = load_test_tags(root)
    findings: list[Finding] = []
    for requirement in load_requirements(root):
        if _normalise(requirement.status) != "approved":
            continue
        if _normalise(requirement.type) != "security":
            continue
        if test_tags.get(requirement.id):
            continue
        findings.append(
            Finding(
                path=requirement.path,
                rule="SEC-001",
                severity="error",
                message=(
                    f"{requirement.id} is an approved security requirement "
                    "but has no requirement-tagged test"
                ),
                requirement=requirement.id,
            )
        )
    return sort_findings(findings)


def run_all(root: Path = Path(".")) -> list[ToolResult]:
    """Run every scanner in a fixed order."""
    root = Path(root)
    scanners = (
        scan_secrets,
        scan_bandit,
        scan_semgrep,
        scan_dependencies,
        scan_container,
        scan_iac,
    )
    return [scanner(root) for scanner in scanners]


def _tool_index(tool: str) -> int:
    try:
        return _TOOL_ORDER.index(tool)
    except ValueError:
        return len(_TOOL_ORDER)


def _ordered_results(results: list[ToolResult]) -> list[ToolResult]:
    return sorted(results, key=lambda result: (_tool_index(result.tool), result.tool))


def gate_failed(results: list[ToolResult]) -> bool:
    """Return whether any scanner produced a finding that must block the gate."""
    gating_levels = {
        "bandit": {"high", "critical"},
        "semgrep": {"high", "critical"},
        "trivy": {"critical"},
        "checkov": {"high", "critical"},
    }
    for result in results:
        severities = {_severity(finding.severity) for finding in result.findings}
        if result.tool in {"gitleaks", "pip-audit"}:
            if result.findings:
                return True
        elif result.tool in gating_levels and severities & gating_levels[result.tool]:
            return True
    return False


def write_security_report(results: list[ToolResult], root: Path = Path(".")) -> Path:
    """Write ``build/reports/security.json`` and return its path."""
    root = Path(root)
    ordered = _ordered_results(results)

    by_severity = {severity: 0 for severity in _SEVERITIES}
    by_tool: dict[str, int] = {}
    tool_status: dict[str, str] = {}
    total = 0
    for result in ordered:
        by_tool[result.tool] = len(result.findings)
        tool_status[result.tool] = result.status
        total += len(result.findings)
        for finding in result.findings:
            by_severity[_severity(finding.severity)] += 1

    payload = {
        "summary": {
            "status": "failed" if gate_failed(results) else "passed",
            "total": total,
            "by_severity": by_severity,
            "by_tool": by_tool,
            "tool_status": tool_status,
        },
        "results": [
            {
                "tool": result.tool,
                "status": result.status,
                "note": result.note,
                "findings": [
                    {
                        "tool": finding.tool,
                        "severity": _severity(finding.severity),
                        "path": finding.path,
                        "line": finding.line,
                        "message": finding.message,
                        "rule": finding.rule,
                    }
                    for finding in result.findings
                ],
            }
            for result in ordered
        ],
    }

    report_directory = root / "build" / "reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    path = report_directory / "security.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_sarif(results: list[ToolResult], root: Path = Path(".")) -> Path:
    """Write ``build/reports/security.sarif`` (SARIF 2.1.0) and return its path."""
    root = Path(root)
    findings = [finding for result in _ordered_results(results) for finding in result.findings]
    findings.sort(
        key=lambda finding: (
            finding.tool,
            finding.rule,
            finding.path,
            finding.line,
            finding.message,
            finding.severity,
        )
    )

    rules: list[dict[str, Any]] = []
    seen_rules: set[str] = set()
    sarif_results: list[dict[str, Any]] = []
    for finding in findings:
        severity = _severity(finding.severity)
        if finding.rule not in seen_rules:
            seen_rules.add(finding.rule)
            rules.append({"id": finding.rule})
        level = (
            "error"
            if severity in {"critical", "high"}
            else ("warning" if severity == "medium" else "note")
        )
        sarif_results.append(
            {
                "ruleId": finding.rule,
                "level": level,
                "message": {"text": f"{finding.tool}: {finding.message}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.path or "<unknown>"},
                            "region": {"startLine": max(finding.line, 1)},
                        }
                    }
                ],
            }
        )

    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "mbse-security", "rules": rules}},
                "results": sarif_results,
            }
        ],
    }

    report_directory = root / "build" / "reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    path = report_directory / "security.sarif"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
