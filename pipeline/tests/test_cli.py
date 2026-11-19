from __future__ import annotations

import textwrap
from pathlib import Path

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
