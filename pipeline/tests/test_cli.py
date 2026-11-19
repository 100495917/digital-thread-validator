from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import mbse.cli as cli_module
import pytest
from click.testing import CliRunner
from mbse.cli import cli
from mbse.findings import Finding
from mbse.thread import ThreadEdge, ThreadGraph, ThreadNode

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
    "changelog",
    "commits",
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


def _thread_node(node_id: str, node_type: str, **attributes: object) -> ThreadNode:
    return ThreadNode(
        id=node_id,
        type=node_type,
        path=attributes.get("path", f"path/{node_id}"),
        sha256="a" * 64,
        version="1.0",
        last_changed_commit="",
        attributes=dict(attributes),
    )


def _thread_graph() -> ThreadGraph:
    requirement = _thread_node("REQ-001", "Requirement", title="Status reporting")
    result = _thread_node(
        "RESULT:tests/test_demo.py::test_status",
        "TestResult",
        outcome="failed",
        duration=0.01,
    )
    edge = ThreadEdge(
        source="REQ-001",
        target="RESULT:tests/test_demo.py::test_status",
        type="RESULT_OF",
    )
    return ThreadGraph(metadata={}, nodes=[requirement, result], edges=[edge])


def _patch_thread_graph(monkeypatch: pytest.MonkeyPatch, graph: ThreadGraph) -> None:
    monkeypatch.setattr(cli_module.thread_module, "load_graph", lambda root=Path("."): graph)


def test_thread_build_prints_counts_and_written_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    graph = _thread_graph()
    thread_path = tmp_path / "digital_thread/thread.json"
    visual_paths = [tmp_path / "docs/thread.html", tmp_path / "docs/thread.md"]
    calls: dict[str, object] = {}

    def fake_build(root: Path = Path(".")) -> ThreadGraph:
        calls["build_root"] = root
        return graph

    def fake_write(value: ThreadGraph, root: Path = Path(".")) -> Path:
        calls["write_root"] = root
        calls["write_graph"] = value
        return thread_path

    def fake_visualize(value: ThreadGraph, root: Path = Path(".")) -> list[Path]:
        calls["visual_graph"] = value
        return visual_paths

    monkeypatch.setattr(cli_module.thread_module, "build_graph", fake_build)
    monkeypatch.setattr(cli_module.thread_module, "write_thread", fake_write)
    monkeypatch.setattr(cli_module.thread_visual_module, "generate_visualizations", fake_visualize)

    result = CliRunner().invoke(cli, ["thread", "build"])

    assert result.exit_code == 0, result.output
    assert "nodes: 2, edges: 1" in result.output
    assert "digital_thread/thread.json" in result.output
    assert "docs/thread.html" in result.output
    assert "docs/thread.md" in result.output
    assert calls["build_root"] == Path(".")
    assert calls["write_root"] == Path(".")
    assert calls["write_graph"] is graph
    assert calls["visual_graph"] is graph


def test_thread_update_prints_summary_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    graph = _thread_graph()
    thread_path = tmp_path / "digital_thread/thread.json"
    snapshot = tmp_path / "digital_thread/history/local.json"
    diff_report = tmp_path / "build/reports/thread_diff.md"

    def fake_update(root: Path = Path(".")) -> dict:
        _ = root
        return {
            "thread": thread_path,
            "snapshot": snapshot,
            "diff_report": diff_report,
            "diff": {
                "added_nodes": ["REQ-002"],
                "removed_nodes": [],
                "modified_nodes": ["REQ-001", "src/demo.py"],
                "added_edges": [{"source": "A", "target": "B", "type": "VERIFIES"}],
                "removed_edges": [],
            },
            "stale": ["REQ-001", "RESULT:tests/test_demo.py::test_status"],
        }

    monkeypatch.setattr(cli_module.thread_diff_module, "update_thread", fake_update)
    _patch_thread_graph(monkeypatch, graph)

    result = CliRunner().invoke(cli, ["thread", "update"])

    assert result.exit_code == 0, result.output
    assert "nodes: 2, edges: 1" in result.output
    assert "added: 1, removed: 0, modified: 2, stale: 2" in result.output
    assert "digital_thread/thread.json" in result.output
    assert "digital_thread/history/local.json" in result.output
    assert "build/reports/thread_diff.md" in result.output


def test_thread_query_downstream_lists_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    graph = _thread_graph()
    start = _thread_node("REQ-001", "Requirement")
    downstream_nodes = [
        _thread_node("REQ-002", "Requirement"),
        _thread_node(
            "RESULT:tests/test_demo.py::test_status",
            "TestResult",
            outcome="failed",
        ),
    ]

    _patch_thread_graph(monkeypatch, graph)
    monkeypatch.setattr(
        cli_module.thread_query_module, "resolve_node", lambda value, identifier: start
    )
    monkeypatch.setattr(
        cli_module.thread_query_module, "downstream", lambda value, identifier: downstream_nodes
    )

    result = CliRunner().invoke(cli, ["thread", "query", "--downstream", "REQ-001"])

    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert lines == [
        "Requirement REQ-002",
        "TestResult RESULT:tests/test_demo.py::test_status failed",
    ]


def test_thread_query_why_failed_prints_outcome_and_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    graph = _thread_graph()
    test = _thread_node("tests/test_demo.py::test_status", "Test")
    payload = {
        "test": test,
        "result": _thread_node(
            "RESULT:tests/test_demo.py::test_status", "TestResult", outcome="failed"
        ),
        "requirements": ["REQ-001"],
        "code": ["src/demo.py"],
        "outcome": "failed",
    }

    _patch_thread_graph(monkeypatch, graph)
    monkeypatch.setattr(
        cli_module.thread_query_module, "resolve_node", lambda value, identifier: test
    )
    monkeypatch.setattr(
        cli_module.thread_query_module, "why_failed", lambda value, identifier: payload
    )

    result = CliRunner().invoke(
        cli, ["thread", "query", "--why-failed", "tests/test_demo.py::test_status"]
    )

    assert result.exit_code == 0, result.output
    assert "outcome: failed" in result.output
    assert "requirements: REQ-001" in result.output
    assert "code: src/demo.py" in result.output


def test_thread_query_history_prints_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    graph = _thread_graph()
    node = _thread_node("REQ-001", "Requirement")
    entries = [
        {"commit": "abc1234", "subject": "Add status requirement"},
        {"commit": "def5678", "subject": "Initial import"},
    ]

    _patch_thread_graph(monkeypatch, graph)
    monkeypatch.setattr(
        cli_module.thread_query_module, "resolve_node", lambda value, identifier: node
    )
    monkeypatch.setattr(cli_module.thread_query_module, "history", lambda root, identifier: entries)

    result = CliRunner().invoke(cli, ["thread", "query", "--history", "REQ-001"])

    assert result.exit_code == 0, result.output
    assert "abc1234 Add status requirement" in result.output
    assert "def5678 Initial import" in result.output


def test_thread_query_json_emits_node_dicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    graph = _thread_graph()
    start = _thread_node("REQ-001", "Requirement")
    downstream_nodes = [
        _thread_node("REQ-002", "Requirement"),
        _thread_node("src/demo.py", "CodeModule"),
    ]

    _patch_thread_graph(monkeypatch, graph)
    monkeypatch.setattr(
        cli_module.thread_query_module, "resolve_node", lambda value, identifier: start
    )
    monkeypatch.setattr(
        cli_module.thread_query_module, "downstream", lambda value, identifier: downstream_nodes
    )

    result = CliRunner().invoke(cli, ["thread", "query", "--downstream", "REQ-001", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [item["id"] for item in payload] == ["REQ-002", "src/demo.py"]
    assert [item["type"] for item in payload] == ["Requirement", "CodeModule"]


def test_thread_query_unknown_node_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _patch_thread_graph(monkeypatch, _thread_graph())
    monkeypatch.setattr(
        cli_module.thread_query_module, "resolve_node", lambda value, identifier: None
    )

    result = CliRunner().invoke(cli, ["thread", "query", "--downstream", "REQ-999"])

    assert result.exit_code == 1
    assert "unknown node: REQ-999" in result.output


def test_thread_query_requires_exactly_one_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["thread", "query"])

    assert result.exit_code == 2
    assert "exactly one of --upstream, --downstream, --why-failed, --history" in result.output


def _impact_report() -> dict:
    return {
        "base": "origin/main",
        "head": "HEAD",
        "changed_files": ["requirements/req.yaml", "src/demo.py"],
        "artifacts": {
            "directly_changed": [
                {
                    "id": "REQ-001",
                    "type": "Requirement",
                    "path": "requirements/req.yaml",
                    "reasons": ["changed file"],
                },
            ],
            "impacted": [
                {
                    "id": "BLK-demo",
                    "type": "ModelElement",
                    "path": "models/system.yaml",
                    "reasons": ["downstream"],
                },
            ],
            "needs_review": [
                {
                    "id": "REQ-002",
                    "type": "Requirement",
                    "path": "requirements/req2.yaml",
                    "reasons": ["upstream"],
                },
            ],
            "needs_retest": [
                {
                    "id": "tests/test_demo.py::test_status",
                    "type": "Test",
                    "path": "tests/test_demo.py",
                    "reasons": ["downstream"],
                },
            ],
        },
        "summary": {
            "changed_files": 2,
            "directly_changed": 1,
            "impacted": 1,
            "needs_review": 1,
            "needs_retest": 1,
        },
        "risk": {
            "level": "high",
            "safety_requirements": 1,
            "security_requirements": 0,
            "depth": 3,
            "changed_files": 2,
        },
        "requirements": {"direct": ["REQ-001"], "affected": ["REQ-001", "REQ-002"]},
    }


def test_impact_prints_classification_counts_risk_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    report = _impact_report()
    impact_json = tmp_path / "build/reports/impact.json"
    impact_md = tmp_path / "build/reports/impact.md"
    rtm_diff = tmp_path / "build/reports/rtm_diff.md"
    calls: dict[str, object] = {}

    def fake_analyse(base: str, head: str = "HEAD", root: Path = Path(".")) -> dict:
        calls["analyse"] = (base, head, root)
        return report

    def fake_write(value: dict, root: Path = Path(".")) -> tuple[Path, Path]:
        calls["write"] = (value, root)
        return impact_json, impact_md

    def fake_rtm(base: str, head: str, root: Path = Path(".")) -> Path:
        calls["rtm"] = (base, head, root)
        return rtm_diff

    monkeypatch.setattr(cli_module.impact_module, "analyse_impact", fake_analyse)
    monkeypatch.setattr(cli_module.impact_module, "write_impact", fake_write)
    monkeypatch.setattr(cli_module.impact_module, "write_rtm_diff", fake_rtm)

    result = CliRunner().invoke(cli, ["impact", "--base", "origin/develop", "--head", "feature"])

    assert result.exit_code == 0, result.output
    assert "changed_files: 2" in result.output
    assert "directly_changed: 1" in result.output
    assert "impacted: 1" in result.output
    assert "needs_review: 1" in result.output
    assert "needs_retest: 1" in result.output
    assert "risk: high" in result.output
    assert "build/reports/impact.json" in result.output
    assert "build/reports/impact.md" in result.output
    assert "build/reports/rtm_diff.md" in result.output
    assert calls["analyse"] == ("origin/develop", "feature", Path("."))
    assert calls["write"] == (report, Path("."))
    assert calls["rtm"] == ("origin/develop", "feature", Path("."))


def test_impact_uses_default_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = _impact_report()
    base = tmp_path / "build/reports/impact.json"
    md = tmp_path / "build/reports/impact.md"
    rtm = tmp_path / "build/reports/rtm_diff.md"
    calls: dict[str, object] = {}

    def fake_analyse(base_ref: str, head_ref: str = "HEAD", root: Path = Path(".")) -> dict:
        calls["analyse"] = (base_ref, head_ref, root)
        return report

    monkeypatch.setattr(cli_module.impact_module, "analyse_impact", fake_analyse)
    monkeypatch.setattr(
        cli_module.impact_module, "write_impact", lambda value, root=Path("."): (base, md)
    )
    monkeypatch.setattr(
        cli_module.impact_module,
        "write_rtm_diff",
        lambda base_ref, head_ref, root=Path("."): rtm,
    )

    result = CliRunner().invoke(cli, ["impact"])

    assert result.exit_code == 0, result.output
    assert calls["analyse"] == ("origin/main", "HEAD", Path("."))


def test_impact_failure_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_analyse(base_ref: str, head_ref: str = "HEAD", root: Path = Path(".")) -> dict:
        raise OSError("impact report write failed")

    monkeypatch.setattr(cli_module.impact_module, "analyse_impact", fake_analyse)

    result = CliRunner().invoke(cli, ["impact"])

    assert result.exit_code == 1
    assert "impact report write failed" in result.output
    assert "Traceback" not in result.output


def test_report_prints_status_and_summary_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    summary_json = tmp_path / "build/reports/summary.json"
    summary_md = tmp_path / "build/reports/summary.md"
    site_page = tmp_path / "docs/generated/summary.md"
    copied = tmp_path / "docs/reports/impact.json"

    def fake_write_summary(root: Path = Path(".")) -> dict:
        _write(summary_json, '{"status": "pass"}')
        return {
            "summary_json": summary_json,
            "summary_md": summary_md,
            "site_pages": [site_page],
            "reports_copied": [copied],
        }

    monkeypatch.setattr(cli_module.reports_module, "write_summary", fake_write_summary)

    result = CliRunner().invoke(cli, ["report"])

    assert result.exit_code == 0, result.output
    assert "status: pass" in result.output
    assert "build/reports/summary.json" in result.output
    assert "build/reports/summary.md" in result.output
    assert "docs/generated/summary.md" in result.output


def test_help_lists_freeze_diff_and_commit_check() -> None:
    runner = CliRunner()

    baseline_help = runner.invoke(cli, ["baseline", "--help"])
    assert baseline_help.exit_code == 0
    assert "freeze" in baseline_help.output
    assert "diff" in baseline_help.output

    commits_help = runner.invoke(cli, ["commits", "--help"])
    assert commits_help.exit_code == 0
    assert "check" in commits_help.output


def test_baseline_freeze_writes_baseline_and_prints_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    baseline = tmp_path / "baselines/baseline-v1.0.0.json"
    calls: list[tuple[str, Path]] = []

    def fake_write(version: str, root: Path = Path(".")) -> Path:
        calls.append((version, root))
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text("{}\n", encoding="utf-8")
        return baseline

    monkeypatch.setattr(cli_module, "write_baseline", fake_write)

    result = CliRunner().invoke(cli, ["baseline", "freeze", "v1.0.0"])

    assert result.exit_code == 0, result.output
    assert "baselines/baseline-v1.0.0.json" in result.output
    assert calls == [("v1.0.0", Path("."))]
    assert baseline.is_file()


def _baseline_diff_payload() -> dict:
    return {
        "old": "v1.0.0",
        "new": "v1.1.0",
        "artifacts": {
            "added": ["src/new.py"],
            "removed": [],
            "changed": ["requirements/REQ-003.yaml", "models/system.yaml"],
        },
        "rtm": {"added": [], "removed": [], "changed": ["REQ-003"]},
        "thread": {"added": ["REQ-003"], "removed": [], "changed": []},
    }


def test_baseline_diff_prints_counts_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    diff = _baseline_diff_payload()
    json_path = tmp_path / "build/reports/baseline_diff.json"
    markdown_path = tmp_path / "build/reports/baseline_diff.md"
    calls: dict[str, object] = {}

    def fake_diff(old: str, new: str, root: Path = Path(".")) -> dict:
        calls["diff"] = (old, new, root)
        return diff

    def fake_write_diff(old: str, new: str, root: Path = Path(".")) -> tuple[Path, Path]:
        calls["write"] = (old, new, root)
        return json_path, markdown_path

    monkeypatch.setattr(cli_module, "diff_baselines", fake_diff)
    monkeypatch.setattr(cli_module, "write_baseline_diff", fake_write_diff)

    result = CliRunner().invoke(cli, ["baseline", "diff", "v1.0.0", "v1.1.0"])

    assert result.exit_code == 0, result.output
    assert "artifacts: 1 added, 0 removed, 2 changed" in result.output
    assert "rtm: 0 added, 0 removed, 1 changed" in result.output
    assert "thread: 1 added, 0 removed, 0 changed" in result.output
    assert "build/reports/baseline_diff.json" in result.output
    assert "build/reports/baseline_diff.md" in result.output
    assert calls["diff"] == ("v1.0.0", "v1.1.0", Path("."))
    assert calls["write"] == ("v1.0.0", "v1.1.0", Path("."))


def test_baseline_diff_missing_baseline_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_diff(old: str, new: str, root: Path = Path(".")) -> dict:
        raise FileNotFoundError(f"Baseline '{old}' not found: baselines/baseline-{old}.json")

    monkeypatch.setattr(cli_module, "diff_baselines", fake_diff)

    result = CliRunner().invoke(cli, ["baseline", "diff", "v9.9.9", "v1.0.0"])

    assert result.exit_code == 1
    assert "Baseline 'v9.9.9' not found" in result.output
    assert "Traceback" not in result.output


def test_changelog_uses_default_output_and_prints_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: dict[str, object] = {}

    def fake_write(version: str | None, output: Path | None = None, root: Path = Path(".")) -> Path:
        calls["write"] = (version, output, root)
        path = Path(output) if output is not None else root / "build/reports/changelog.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Changelog\n", encoding="utf-8")
        return path

    monkeypatch.setattr(cli_module, "write_changelog", fake_write)

    result = CliRunner().invoke(cli, ["changelog", "--version", "v1.0.0"])

    assert result.exit_code == 0, result.output
    assert "build/reports/changelog.md" in result.output
    assert calls["write"] == ("v1.0.0", Path("build/reports/changelog.md"), Path("."))
    assert (tmp_path / "build/reports/changelog.md").is_file()


def test_changelog_writes_custom_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    written = tmp_path / "docs/changelog.md"

    def fake_write(version: str | None, output: Path | None = None, root: Path = Path(".")) -> Path:
        _ = (version, root)
        path = Path(output) if output is not None else written
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Changelog\n", encoding="utf-8")
        return path

    monkeypatch.setattr(cli_module, "write_changelog", fake_write)

    result = CliRunner().invoke(
        cli, ["changelog", "--version", "v1.1.0", "--output", "docs/changelog.md"]
    )

    assert result.exit_code == 0, result.output
    assert "docs/changelog.md" in result.output
    assert written.is_file()


def _commit_finding(severity: str, path: str = "abc1234") -> Finding:
    return Finding(
        path=path,
        rule="CC-001",
        severity=severity,
        message='Commit subject is not a conventional commit: "update stuff"',
    )


def test_commits_check_clean_range_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: dict[str, object] = {}

    def fake_check(
        range_spec: str = "HEAD~1..HEAD",
        root: Path = Path("."),
        strict: bool = False,
    ) -> list[Finding]:
        calls["check"] = (range_spec, root, strict)
        return []

    monkeypatch.setattr(cli_module, "check_commits", fake_check)

    result = CliRunner().invoke(cli, ["commits", "check"])

    assert result.exit_code == 0, result.output
    assert "commits: 0 finding(s)" in result.output
    assert calls["check"] == ("HEAD~1..HEAD", Path("."), False)


def test_commits_check_reports_warnings_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    findings = [_commit_finding("warning")]
    calls: dict[str, object] = {}

    def fake_check(
        range_spec: str = "HEAD~1..HEAD",
        root: Path = Path("."),
        strict: bool = False,
    ) -> list[Finding]:
        calls["check"] = (range_spec, root, strict)
        return findings

    monkeypatch.setattr(cli_module, "check_commits", fake_check)

    result = CliRunner().invoke(cli, ["commits", "check", "--range", "main..HEAD"])

    assert result.exit_code == 0, result.output
    assert (
        'abc1234: CC-001 warning: Commit subject is not a conventional commit: "update stuff"'
        in result.output
    )
    assert "commits: 1 finding(s)" in result.output
    assert calls["check"] == ("main..HEAD", Path("."), False)


def test_commits_check_strict_error_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    findings = [_commit_finding("error")]
    calls: dict[str, object] = {}

    def fake_check(
        range_spec: str = "HEAD~1..HEAD",
        root: Path = Path("."),
        strict: bool = False,
    ) -> list[Finding]:
        calls["check"] = (range_spec, root, strict)
        return findings

    monkeypatch.setattr(cli_module, "check_commits", fake_check)

    result = CliRunner().invoke(cli, ["commits", "check", "--strict"])

    assert result.exit_code == 1
    assert "abc1234: CC-001 error:" in result.output
    assert calls["check"] == ("HEAD~1..HEAD", Path("."), True)


def _metrics_payload() -> dict:
    return {
        "deployment_frequency": {"releases": 6, "window_days": 30, "per_week": 1.4},
        "lead_time_hours": {"median": 12.5, "samples": 4},
        "change_failure_rate": {"failed": 1, "total": 5, "rate": 0.2},
        "mean_time_to_restore_hours": {"mean": 4.25, "incidents": 1},
        "pipeline": {
            "tests_total": 11,
            "tests_passed": 10,
            "tests_failed": 1,
            "flaky_tests": 2,
            "coverage_percent": 87.5,
        },
        "stages": [{"name": "build", "duration_seconds": 12.5}],
        "source": "git",
        "status": "ok",
    }


def test_metrics_prints_dora_pipeline_values_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    metrics_path = tmp_path / "build/reports/metrics.json"
    calls: list[Path] = []

    def fake_write(root: Path = Path(".")) -> Path:
        calls.append(root)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(_metrics_payload()), encoding="utf-8")
        return metrics_path

    monkeypatch.setattr(cli_module, "write_metrics", fake_write)

    result = CliRunner().invoke(cli, ["metrics"])

    assert result.exit_code == 0, result.output
    assert "deployment_frequency: 1.4/week (6 releases in 30 days)" in result.output
    assert "lead_time_median_hours: 12.5" in result.output
    assert "change_failure_rate: 20.0% (1/5)" in result.output
    assert "mttr_hours: 4.25" in result.output
    assert "tests: 10 passed, 1 failed, 2 flaky" in result.output
    assert "coverage: 87.5%" in result.output
    assert "build/reports/metrics.json" in result.output
    assert calls == [Path(".")]
