from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import mbse.cli as cli_module
import pytest
from click.testing import CliRunner
from mbse.cli import cli

TOP_LEVEL_COMMANDS = [
    "validate",
    "trace",
    "thread",
    "impact",
    "generate",
    "report",
    "reqcov",
    "security",
    "metrics",
    "baseline",
]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _requirement(text: str = "The system shall report its status.") -> str:
    return f"""\
    id: REQ-001
    title: Status reporting
    text: "{text}"
    type: functional
    priority: high
    owner: team-demo
    verification: test
    status: approved
    rationale: "Clients need the current state."
    """


def _model() -> str:
    return """\
    system: Demo
    version: 1.0.0
    elements:
      - id: BLK-demo
        kind: block
        name: DemoBlock
        satisfies: [REQ-001]
        allocated_to: src/demo.py
    relations: []
    """


def _schemas() -> dict[str, str]:
    schema = '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}\n'
    return {
        "models/schema/requirements.schema.json": schema,
        "models/schema/system.schema.json": schema,
    }


def _make_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "The system shall report its status.",
    with_test: bool = True,
    with_schemas: bool = True,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "requirements/REQ-001.yaml", _requirement(text))
    _write(tmp_path / "models/system.yaml", _model())
    _write(tmp_path / "src/demo.py", "# @implements REQ-001\n")
    if with_test:
        _write(
            tmp_path / "tests/test_demo.py",
            """\
            import pytest


            @pytest.mark.req("REQ-001")
            def test_status() -> None:
                assert True
            """,
        )
    if with_schemas:
        for relative, content in _schemas().items():
            _write(tmp_path / relative, content)


def test_help_lists_all_top_level_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in TOP_LEVEL_COMMANDS:
        assert command in result.output


def test_unknown_validate_mode_errors() -> None:
    result = CliRunner().invoke(cli, ["validate", "unknown"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output


def test_validate_broken_yaml_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    requirements = tmp_path / "requirements"
    requirements.mkdir()
    (requirements / "REQ-001.yaml").write_text("id: [unclosed\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["validate", "reqs"])

    assert result.exit_code == 1
    assert "REQ-001.yaml" in result.output
    assert "Traceback" not in result.output
    assert (
        "validated 1 requirement file(s), 0 model file(s), 1 error(s), 0 warning(s)"
        in result.output
    )


def test_validate_empty_project_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "all"])

    assert result.exit_code == 0
    assert (
        "validated 0 requirement file(s), 0 model file(s), 0 error(s), 0 warning(s)"
        in result.output
    )


def test_validate_all_valid_project_writes_quality_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["validate", "all"])

    assert result.exit_code == 0, result.output
    assert (
        "validated 1 requirement file(s), 1 model file(s), 0 error(s), 0 warning(s)"
        in result.output
    )
    assert (tmp_path / "build/reports/req_quality.json").is_file()


def test_validate_flags_ambiguous_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(
        tmp_path,
        monkeypatch,
        text="The system shall respond quickly.",
        with_test=False,
    )

    result = CliRunner().invoke(cli, ["validate", "reqs"])

    assert result.exit_code == 1
    assert "RQ-003" in result.output
    assert "1 error(s)" in result.output


def test_trace_check_complete_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_project(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["trace", "check"])

    assert result.exit_code == 0, result.output
    assert "traceability coverage:" in result.output
    assert "verification coverage:" in result.output


def test_trace_check_missing_test_fails_naming_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_project(tmp_path, monkeypatch, with_test=False)

    result = CliRunner().invoke(cli, ["trace", "check"])

    assert result.exit_code == 1
    assert "REQ-001" in result.output


def test_trace_rtm_writes_three_formats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_project(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["trace", "rtm"])

    assert result.exit_code == 0, result.output
    for name in ("rtm.csv", "rtm.md", "rtm.html"):
        assert (tmp_path / "build/reports" / name).is_file()
        assert f"build/reports/{name}" in result.output


def _tool(
    tool: str, status: str, findings: list[object] | None = None, note: str = ""
) -> SimpleNamespace:
    return SimpleNamespace(tool=tool, status=status, findings=list(findings or []), note=note)


def test_generate_all_dispatches_and_prints_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    written = tmp_path / "build/diagrams/block-definition.puml"
    calls: list[Path] = []

    def fake_generate_all(root: Path = Path(".")) -> list[Path]:
        calls.append(root)
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text("@startuml\n@enduml\n", encoding="utf-8")
        return [written]

    monkeypatch.setattr(cli_module, "generate_all", fake_generate_all)

    result = CliRunner().invoke(cli, ["generate", "all"])

    assert result.exit_code == 0, result.output
    assert calls == [Path(".")]
    assert "build/diagrams/block-definition.puml" in result.output


def test_generate_invalid_target_errors() -> None:
    result = CliRunner().invoke(cli, ["generate", "unknown"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output


def test_generate_value_error_becomes_click_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_generate_openapi(root: Path = Path(".")) -> Path:
        raise ValueError("GET /status missing")

    monkeypatch.setattr(cli_module, "generate_openapi", fake_generate_openapi)

    result = CliRunner().invoke(cli, ["generate", "openapi"])

    assert result.exit_code == 1
    assert "GET /status missing" in result.output
    assert "Traceback" not in result.output


def test_reqcov_passes_threshold_and_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: dict[str, object] = {}
    report = tmp_path / "build/reports/reqcov.json"

    def fake_compute(root: Path = Path("."), results_path: Path | None = None) -> dict:
        calls["root"] = root
        calls["results_path"] = results_path
        return {"summary": {"total": 2, "covered": 2, "coverage": 100.0}}

    def fake_write(coverage: dict, root: Path = Path(".")) -> Path:
        calls["threshold"] = coverage["summary"]["threshold"]
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{}\n", encoding="utf-8")
        return report

    monkeypatch.setattr(cli_module, "compute_requirements_coverage", fake_compute)
    monkeypatch.setattr(cli_module, "write_reqcov_report", fake_write)

    result = CliRunner().invoke(
        cli,
        [
            "reqcov",
            "--threshold",
            "50",
            "--results",
            "build/reports/req_results.json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "requirements coverage: 100.0% (2/2)" in result.output
    assert "build/reports/reqcov.json" in result.output
    assert calls["results_path"] == Path("build/reports/req_results.json")
    assert calls["threshold"] == 50.0
    assert report.is_file()


def test_reqcov_fails_below_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_compute(root: Path = Path("."), results_path: Path | None = None) -> dict:
        _ = (root, results_path)
        return {"total": 3, "covered": 2, "coverage": 66.7}

    def fake_write(coverage: dict, root: Path = Path(".")) -> Path:
        return root / "build/reports/reqcov.json"

    monkeypatch.setattr(cli_module, "compute_requirements_coverage", fake_compute)
    monkeypatch.setattr(cli_module, "write_reqcov_report", fake_write)

    result = CliRunner().invoke(cli, ["reqcov"])

    assert result.exit_code == 1
    assert "requirements coverage: 66.7% (2/3)" in result.output
    assert "build/reports/reqcov.json" in result.output


def test_security_passes_gate_and_prints_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    results = [
        _tool("gitleaks", "passed"),
        _tool("bandit", "unavailable", note="not installed"),
    ]
    report = tmp_path / "build/reports/security.json"
    sarif = tmp_path / "build/reports/security.sarif"

    monkeypatch.setattr(cli_module, "run_security_scan", lambda root=Path("."): results)
    monkeypatch.setattr(cli_module, "write_security_report", lambda results, root=Path("."): report)
    monkeypatch.setattr(cli_module, "write_security_sarif", lambda results, root=Path("."): sarif)
    monkeypatch.setattr(cli_module, "security_gate_failed", lambda results: False)

    result = CliRunner().invoke(cli, ["security"])

    assert result.exit_code == 0, result.output
    assert "gitleaks: passed" in result.output
    assert "bandit: unavailable - not installed" in result.output
    assert "build/reports/security.json" in result.output
    assert "build/reports/security.sarif" in result.output
    assert "gate passed" in result.output


def test_security_fails_gate_with_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    findings = [SimpleNamespace(severity="high", message="hardcoded secret")]
    results = [_tool("gitleaks", "failed", findings=findings)]

    monkeypatch.setattr(cli_module, "run_security_scan", lambda root=Path("."): results)
    monkeypatch.setattr(
        cli_module,
        "write_security_report",
        lambda results, root=Path("."): root / "build/reports/security.json",
    )
    monkeypatch.setattr(
        cli_module,
        "write_security_sarif",
        lambda results, root=Path("."): root / "build/reports/security.sarif",
    )
    monkeypatch.setattr(cli_module, "security_gate_failed", lambda results: True)

    result = CliRunner().invoke(cli, ["security"])

    assert result.exit_code == 1
    assert "gitleaks: failed (1 finding(s))" in result.output
    assert "1 finding(s), gate failed" in result.output
