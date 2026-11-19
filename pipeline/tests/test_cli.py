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

    result = CliRunner().invoke(cli, ["validate"])

    assert result.exit_code == 1
    assert "REQ-001.yaml" in result.output
    assert "1 error(s)" in result.output


def test_validate_empty_project_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate"])

    assert result.exit_code == 0
    assert "validated 0 requirement file(s), 0 model file(s), 0 error(s)" in result.output
