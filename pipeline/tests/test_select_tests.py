"""Tests for selective test selection from the impact report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mbse.select_tests import main, select_tests


def _write_impact(root: Path, payload: object) -> None:
    path = root / "build" / "reports" / "impact.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _report(
    needs_retest: list[object] | None = None,
    directly_changed: list[object] | None = None,
) -> dict:
    return {
        "artifacts": {
            "needs_retest": needs_retest or [],
            "directly_changed": directly_changed or [],
            "impacted": [],
            "needs_review": [],
        }
    }


def test_needs_retest_is_selected_deduplicated_and_sorted(tmp_path: Path) -> None:
    _write_impact(
        tmp_path,
        _report(
            needs_retest=[
                {"id": "tests/test_b.py::test_two", "type": "Test"},
                {"id": "tests/test_a.py::test_one", "type": "Test"},
                {"id": "tests/test_a.py::test_one", "type": "Test"},
                {"id": "REQ-001", "type": "Requirement"},
                {"id": "src/module.py", "type": "CodeModule"},
                {"id": "tests/test_c.py::test_three"},
                "not-a-dict",
            ]
        ),
    )

    assert select_tests(tmp_path) == [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_two",
    ]


def test_directly_changed_tests_are_included(tmp_path: Path) -> None:
    _write_impact(
        tmp_path,
        _report(
            needs_retest=[{"id": "tests/test_a.py::test_one", "type": "Test"}],
            directly_changed=[
                {"id": "tests/test_a.py::test_one", "type": "Test"},
                {"id": "tests/test_z.py::test_late", "type": "Test"},
                {"id": "REQ-001", "type": "Requirement"},
            ],
        ),
    )

    assert select_tests(tmp_path) == [
        "tests/test_a.py::test_one",
        "tests/test_z.py::test_late",
    ]


def test_missing_report_returns_empty(tmp_path: Path) -> None:
    assert select_tests(tmp_path) == []


def test_empty_report_returns_empty(tmp_path: Path) -> None:
    _write_impact(tmp_path, _report())
    assert select_tests(tmp_path) == []


def test_impact_entries_without_test_artifacts_return_empty(tmp_path: Path) -> None:
    _write_impact(
        tmp_path,
        _report(
            needs_retest=[{"id": "REQ-001", "type": "Requirement"}],
            directly_changed=[{"id": "src/module.py", "type": "CodeModule"}],
        ),
    )
    assert select_tests(tmp_path) == []


def test_malformed_report_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "build" / "reports" / "impact.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert select_tests(tmp_path) == []


def test_non_object_report_returns_empty(tmp_path: Path) -> None:
    _write_impact(tmp_path, ["unexpected"])
    assert select_tests(tmp_path) == []


def test_main_prints_space_separated_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_impact(
        tmp_path,
        _report(
            needs_retest=[
                {"id": "tests/test_b.py::test_two", "type": "Test"},
                {"id": "tests/test_a.py::test_one", "type": "Test"},
            ]
        ),
    )
    monkeypatch.chdir(tmp_path)

    main()

    captured = capsys.readouterr()
    assert captured.out == "tests/test_a.py::test_one tests/test_b.py::test_two\n"
    assert captured.err == ""


def test_main_prints_nothing_without_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_impact(tmp_path, _report())
    monkeypatch.chdir(tmp_path)

    main()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
