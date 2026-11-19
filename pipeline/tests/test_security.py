"""Tests for security scanners, gating, and security report generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from mbse import security
from mbse.security import (
    SecurityFinding,
    ToolResult,
    check_security_requirements,
    gate_failed,
    scan_bandit,
    scan_container,
    scan_dependencies,
    scan_iac,
    scan_secrets,
    scan_semgrep,
    write_sarif,
    write_security_report,
)

# Secrets are assembled at runtime so this test module does not itself look
# like a secret fixture to the fallback scanner.
_AWS_KEY = "AKIA" + "".join(chr(ord("A") + index) for index in range(16))
_GITHUB_TOKEN = "gh" + "p_" + "A" * 36
_PRIVATE_KEY_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
_ASSIGNMENT = "api_key" + " = " + "'" + "x" * 16 + "'"


def _force_tool(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    payload: object,
    *,
    returncode: int = 1,
) -> None:
    monkeypatch.setattr(
        security.shutil,
        "which",
        lambda tool: f"/usr/bin/{tool}" if tool == name else None,
    )
    completed = subprocess.CompletedProcess(
        args=[name],
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr="",
    )
    monkeypatch.setattr(security.subprocess, "run", lambda *args, **kwargs: completed)


def _write_requirement(
    root: Path,
    requirement_id: str,
    *,
    requirement_type: str = "security",
    status: str = "approved",
) -> None:
    directory = root / "requirements"
    directory.mkdir(parents=True, exist_ok=True)
    content = (
        f"id: {requirement_id}\n"
        'title: "Security requirement"\n'
        'text: "The system shall stay secure."\n'
        f"type: {requirement_type}\n"
        "priority: high\n"
        "owner: team-security\n"
        "verification: test\n"
        f"status: {status}\n"
    )
    (directory / f"{requirement_id}.yaml").write_text(content, encoding="utf-8")


def test_secret_fallback_detects_keys_and_skips_generated_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security.shutil, "which", lambda tool: None)
    config = tmp_path / "config"
    config.mkdir()
    (config / "secrets.txt").write_text(
        "\n".join(
            [
                f"aws = {_AWS_KEY}",
                "",
                f"github = {_GITHUB_TOKEN}",
                "",
                _PRIVATE_KEY_HEADER,
                "",
                _ASSIGNMENT,
                "",
            ]
        ),
        encoding="utf-8",
    )
    for skipped in ("build", ".venv"):
        directory = tmp_path / skipped
        directory.mkdir()
        (directory / "leak.txt").write_text(f"aws = {_AWS_KEY}\n", encoding="utf-8")

    result = scan_secrets(tmp_path)

    assert result.tool == "gitleaks"
    assert result.status == "failed"
    paths = {finding.path for finding in result.findings}
    assert paths == {"config/secrets.txt"}
    assert all(finding.path != "build/leak.txt" for finding in result.findings)
    assert all(finding.path != ".venv/leak.txt" for finding in result.findings)
    by_rule = {finding.rule: finding for finding in result.findings}
    assert by_rule["SEC-SECRET-AWS"].severity == "critical"
    assert by_rule["SEC-SECRET-AWS"].line == 1
    assert by_rule["SEC-SECRET-GITHUB"].severity == "critical"
    assert by_rule["SEC-SECRET-GITHUB"].line == 3
    assert by_rule["SEC-SECRET-PRIVATE-KEY"].severity == "critical"
    assert by_rule["SEC-SECRET-PRIVATE-KEY"].line == 5
    assert by_rule["SEC-SECRET-ASSIGNMENT"].severity == "high"
    assert by_rule["SEC-SECRET-ASSIGNMENT"].line == 7


def test_secret_fallback_passes_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security.shutil, "which", lambda tool: None)
    (tmp_path / "README.md").write_text("nothing sensitive here\n", encoding="utf-8")

    result = scan_secrets(tmp_path)

    assert result.status == "passed"
    assert result.findings == ()


@pytest.mark.parametrize(
    "scanner,tool",
    [
        (scan_bandit, "bandit"),
        (scan_semgrep, "semgrep"),
        (scan_dependencies, "pip-audit"),
        (scan_container, "trivy"),
        (scan_iac, "checkov"),
    ],
)
def test_missing_external_tools_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scanner,
    tool: str,
) -> None:
    monkeypatch.setattr(security.shutil, "which", lambda name: None)

    result = scanner(tmp_path)

    assert result.tool == tool
    assert result.status == "unavailable"
    assert result.findings == ()
    assert tool in result.note


def test_bandit_high_finding_is_parsed_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tool(
        monkeypatch,
        "bandit",
        {
            "results": [
                {
                    "filename": "src/app.py",
                    "line_number": 7,
                    "issue_severity": "HIGH",
                    "issue_text": "use of eval",
                    "test_id": "B307",
                }
            ]
        },
    )

    result = scan_bandit(tmp_path)

    assert result.status == "failed"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "high"
    assert finding.path == "src/app.py"
    assert finding.line == 7
    assert finding.rule == "B307"


def test_pip_audit_vulnerabilities_are_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_tool(
        monkeypatch,
        "pip-audit",
        {
            "dependencies": [
                {
                    "name": "click",
                    "version": "8.0.0",
                    "vulns": [{"id": "CVE-2024-0001", "description": "bad click"}],
                }
            ]
        },
    )

    result = scan_dependencies(tmp_path)

    assert result.status == "failed"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "high"
    assert finding.rule == "CVE-2024-0001"
    assert "click" in finding.message
    assert gate_failed([result]) is True


def test_trivy_critical_finding_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _force_tool(
        monkeypatch,
        "trivy",
        {
            "Results": [
                {
                    "Target": "image:demo",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2024-0002",
                            "PkgName": "openssl",
                            "InstalledVersion": "1.0.0",
                            "Severity": "CRITICAL",
                            "Title": "remote execution",
                        }
                    ],
                }
            ]
        },
    )

    result = scan_container(tmp_path)

    assert result.status == "failed"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "critical"
    assert finding.rule == "CVE-2024-0002"
    assert finding.path == "image:demo"
    assert gate_failed([result]) is True


def _finding(tool: str, severity: str, line: int = 0, rule: str = "R-1") -> SecurityFinding:
    return SecurityFinding(
        tool=tool,
        severity=severity,
        path="src/app.py",
        line=line,
        message=f"{tool} finding",
        rule=rule,
    )


def test_gate_semantics_per_tool() -> None:
    def result(tool: str, *findings: SecurityFinding) -> ToolResult:
        return ToolResult(tool=tool, status="passed", findings=findings)

    assert gate_failed([result("gitleaks", _finding("gitleaks", "medium"))]) is True
    assert gate_failed([result("bandit", _finding("bandit", "medium"))]) is False
    assert gate_failed([result("bandit", _finding("bandit", "high"))]) is True
    assert gate_failed([result("semgrep", _finding("semgrep", "critical"))]) is True
    assert gate_failed([result("pip-audit", _finding("pip-audit", "low"))]) is True
    assert gate_failed([result("trivy", _finding("trivy", "high"))]) is False
    assert gate_failed([result("trivy", _finding("trivy", "critical"))]) is True
    assert gate_failed([result("checkov", _finding("checkov", "medium"))]) is False
    assert gate_failed([result("checkov", _finding("checkov", "high"))]) is True
    assert gate_failed([result("bandit")]) is False


def test_security_report_and_sarif_shapes(tmp_path: Path) -> None:
    critical = _finding("gitleaks", "critical", line=3, rule="SEC-SECRET-AWS")
    medium = _finding("bandit", "medium", line=0, rule="B101")
    results = [
        ToolResult(tool="bandit", status="passed", findings=(medium,), note=""),
        ToolResult(tool="gitleaks", status="failed", findings=(critical,), note=""),
    ]

    report_path = write_security_report(results, tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report_path == tmp_path / "build" / "reports" / "security.json"
    summary = report["summary"]
    assert summary["status"] == "failed"
    assert summary["total"] == 2
    assert summary["by_severity"] == {
        "critical": 1,
        "high": 0,
        "medium": 1,
        "low": 0,
    }
    assert summary["by_tool"] == {"gitleaks": 1, "bandit": 1}
    assert [entry["tool"] for entry in report["results"]] == ["gitleaks", "bandit"]
    assert report["results"][0]["findings"][0]["rule"] == "SEC-SECRET-AWS"

    sarif_path = write_sarif(results, tmp_path)
    sarif = json.loads(sarif_path.read_text(encoding="utf-8"))

    assert sarif_path == tmp_path / "build" / "reports" / "security.sarif"
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "mbse-security"
    assert {rule["id"] for rule in run["tool"]["driver"]["rules"]} == {
        "SEC-SECRET-AWS",
        "B101",
    }
    levels = {entry["ruleId"]: entry["level"] for entry in run["results"]}
    assert levels == {"SEC-SECRET-AWS": "error", "B101": "warning"}
    locations = {
        entry["ruleId"]: entry["locations"][0]["physicalLocation"]["region"]["startLine"]
        for entry in run["results"]
    }
    assert locations == {"SEC-SECRET-AWS": 3, "B101": 1}

    first = sarif_path.read_bytes()
    write_sarif(results, tmp_path)
    assert sarif_path.read_bytes() == first


def test_security_requirement_missing_test_is_flagged(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-011")

    findings = check_security_requirements(tmp_path)

    assert [finding.rule for finding in findings] == ["SEC-001"]
    assert findings[0].requirement == "REQ-011"
    assert findings[0].severity == "error"
    assert findings[0].path == "requirements/REQ-011.yaml"


def test_security_requirement_with_test_is_not_flagged(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "REQ-011")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_auth.py").write_text(
        'import pytest\n\n@pytest.mark.req("REQ-011")\ndef test_auth() -> None:\n    assert True\n',
        encoding="utf-8",
    )

    assert check_security_requirements(tmp_path) == []
