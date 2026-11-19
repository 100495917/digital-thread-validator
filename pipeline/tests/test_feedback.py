"""Tests for the requirement feedback loop and its CLI."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mbse import feedback

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "feedback.py"


def _write_requirement(root: Path, text: str, requirement_id: str = "REQ-013") -> None:
    directory = root / "requirements"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{requirement_id}.yaml").write_text(
        "\n".join(
            [
                f"id: {requirement_id}",
                'title: "Status endpoint latency"',
                f'text: "{text}"',
                "type: performance",
                "priority: medium",
                "owner: team-performance",
                "verification: test",
                "status: approved",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _load_script():
    spec = importlib.util.spec_from_file_location("feedback_cli", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_threshold_defaults_when_requirement_missing(tmp_path: Path) -> None:
    assert feedback.requirement_threshold_ms(tmp_path) == 100.0


def test_threshold_defaults_without_parseable_phrase(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "The system shall respond quickly.")
    assert feedback.requirement_threshold_ms(tmp_path) == 100.0


def test_threshold_is_parsed_from_requirement_text(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "The system shall respond in under 250 ms at p95.")
    assert feedback.requirement_threshold_ms(tmp_path) == 250.0


def test_threshold_parses_decimal_and_seconds(tmp_path: Path) -> None:
    _write_requirement(tmp_path, "The system shall respond in under 12.5 ms.")
    assert feedback.requirement_threshold_ms(tmp_path) == 12.5

    _write_requirement(tmp_path, "The system shall respond in under 2 seconds.")
    assert feedback.requirement_threshold_ms(tmp_path) == 2000.0


def test_evaluate_feedback_ok() -> None:
    report = feedback.evaluate_feedback(80.0, 100.0)
    assert report == {
        "requirement_id": "REQ-013",
        "observed_p95_ms": 80.0,
        "threshold_ms": 100.0,
        "status": "ok",
        "delta_ms": -20.0,
    }


def test_evaluate_feedback_violated() -> None:
    report = feedback.evaluate_feedback(125.5, 100.0, requirement_id="REQ-013")
    assert report["status"] == "violated"
    assert report["delta_ms"] == 25.5


def test_write_feedback_uses_report_path(tmp_path: Path) -> None:
    report = feedback.evaluate_feedback(120.0, 100.0)
    path = feedback.write_feedback(report, tmp_path)

    assert path == tmp_path / "build" / "reports" / "feedback.json"
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_open_or_update_issue_skips_satisfied_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - asserted by outcome
        raise AssertionError("gh must not run for a satisfied report")

    monkeypatch.setattr(feedback.subprocess, "run", fail)
    result = feedback.open_or_update_issue(feedback.evaluate_feedback(10.0, 100.0), tmp_path)
    assert result == {"action": "skipped", "reason": "requirement is satisfied"}


def test_open_or_update_issue_creates_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["issue", "list"]:
            return _completed("[]")
        return _completed("https://github.com/example/repo/issues/12\n")

    monkeypatch.setattr(feedback.subprocess, "run", fake_run)
    result = feedback.open_or_update_issue(feedback.evaluate_feedback(150.0, 100.0), tmp_path)

    assert result["action"] == "created"
    assert "issues/12" in result["reason"]
    assert commands[-1][1:3] == ["issue", "create"]
    assert "--title" in commands[-1]


def test_open_or_update_issue_updates_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["issue", "list"]:
            return _completed('[{"number": 7}]')
        return _completed("")

    monkeypatch.setattr(feedback.subprocess, "run", fake_run)
    result = feedback.open_or_update_issue(feedback.evaluate_feedback(150.0, 100.0), tmp_path)

    assert result["action"] == "updated"
    assert "#7" in result["reason"]
    assert commands[-1][1:3] == ["issue", "comment"]
    assert commands[-1][3] == "7"


def test_open_or_update_issue_skips_when_gh_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(feedback.subprocess, "run", fake_run)
    result = feedback.open_or_update_issue(feedback.evaluate_feedback(150.0, 100.0), tmp_path)

    assert result["action"] == "skipped"
    assert "unavailable" in result["reason"]


def test_open_or_update_issue_skips_when_create_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command, **kwargs):
        if command[1:3] == ["issue", "list"]:
            return _completed("[]")
        return _completed("", returncode=1, stderr="permission denied")

    monkeypatch.setattr(feedback.subprocess, "run", fake_run)
    result = feedback.open_or_update_issue(feedback.evaluate_feedback(150.0, 100.0), tmp_path)

    assert result["action"] == "skipped"
    assert "permission denied" in result["reason"]


def test_cli_exits_one_when_violated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_requirement(tmp_path, "The system shall respond in under 80 ms at p95.")
    module = _load_script()

    exit_code = module.main(["--observed-p95-ms", "120"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "violated"
    assert payload["requirement_id"] == "REQ-013"
    assert (tmp_path / "build" / "reports" / "feedback.json").is_file()


def test_cli_exits_zero_when_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_requirement(tmp_path, "The system shall respond in under 80 ms at p95.")
    module = _load_script()

    exit_code = module.main(["--observed-p95-ms", "20"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_cli_apply_invokes_issue_handling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_requirement(tmp_path, "The system shall respond in under 80 ms at p95.")
    module = _load_script()

    def fake_run(command, **kwargs):
        if command[1:3] == ["issue", "list"]:
            return _completed("[]")
        return _completed("https://github.com/example/repo/issues/3\n")

    monkeypatch.setattr(feedback.subprocess, "run", fake_run)

    exit_code = module.main(["--observed-p95-ms", "120", "--apply"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["issue"]["action"] == "created"
