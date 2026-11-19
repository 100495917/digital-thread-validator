"""Tests for digital-thread construction, hashing, and serialization."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from mbse.thread import (
    EDGE_TYPES,
    NODE_TYPES,
    SCHEMA_VERSION,
    build_graph,
    collect_metadata,
    graph_from_dict,
    graph_to_dict,
    load_graph,
    load_thread,
    sha256_file,
    test_ids,
    write_thread,
)

REQUIREMENT_001 = """\
id: REQ-001
title: "Hold the temperature"
text: "The system shall hold the temperature near the setpoint."
type: functional
priority: high
owner: team-demo
verification: test
status: approved
rationale: "Comfort."
"""
REQUIREMENT_002 = """\
id: REQ-002
title: "Derived reporting"
text: "The system shall report the held temperature."
type: interface
priority: medium
owner: team-demo
verification: test
status: approved
rationale: "Observability."
parent: REQ-001
"""
MODEL = """\
system: DemoSystem
version: 1.0.0
elements:
  - id: BLK-controller
    kind: block
    name: Controller
    satisfies: [REQ-001, REQ-002]
    allocated_to: src/app.py
relations: []
"""
CODE = """\
# @implements REQ-002
# @implements REQ-001


def control() -> float:
    return 21.0
"""
TESTS = """\
import pytest


@pytest.mark.req("REQ-001", "REQ-002")
def test_demo() -> None:
    assert True


@pytest.mark.req("REQ-002")
def test_junit() -> None:
    assert True


class TestGroup:
    @pytest.mark.req("REQ-002")
    def test_method(self) -> None:
        assert True
"""
REQ_RESULTS = {
    "REQ-001": [
        {
            "test": "tests/test_app.py::test_demo",
            "outcome": "passed",
            "duration": 0.01,
        }
    ],
    "REQ-002": [
        {
            "test": "tests/test_app.py::TestGroup::test_method",
            "outcome": "failed",
            "duration": 0.02,
        }
    ],
}
JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="1">
    <testcase classname="tests.test_app" name="test_junit" time="0.03" />
  </testsuite>
</testsuites>
"""


@pytest.fixture(autouse=True)
def _clear_ci_environment(monkeypatch) -> None:
    """Keep git-based metadata assertions independent of the CI environment."""
    for name in (
        "GITHUB_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_REF_NAME",
        "GITHUB_ACTOR",
        "DEPLOY_ENVIRONMENT",
        "DEPLOY_IMAGE_TAG",
    ):
        monkeypatch.delenv(name, raising=False)


def _write_project(root: Path, *, with_git: bool, with_reports: bool = True) -> str:
    """Create a small project and optionally commit it to a temporary git repo."""
    requirements = root / "requirements"
    requirements.mkdir(parents=True, exist_ok=True)
    (requirements / "REQ-001.yaml").write_text(REQUIREMENT_001, encoding="utf-8")
    (requirements / "REQ-002.yaml").write_text(REQUIREMENT_002, encoding="utf-8")

    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "system.yaml").write_text(MODEL, encoding="utf-8")

    source = root / "src"
    source.mkdir(parents=True, exist_ok=True)
    (source / "app.py").write_text(CODE, encoding="utf-8")

    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_app.py").write_text(TESTS, encoding="utf-8")

    if with_reports:
        reports = root / "build" / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "req_results.json").write_text(json.dumps(REQ_RESULTS), encoding="utf-8")
        (reports / "junit.xml").write_text(JUNIT, encoding="utf-8")
        (reports / "rtm.md").write_text("# RTM\n", encoding="utf-8")

    if not with_git:
        return "local"

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Thread Tester"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "thread@example.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "Initial digital thread fixture",
        ],
        cwd=root,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _nodes(graph) -> dict:
    return {node.id: node for node in graph.nodes}


def test_build_graph_contains_every_node_and_edge_type(tmp_path: Path) -> None:
    commit_sha = _write_project(tmp_path, with_git=True)

    graph = build_graph(tmp_path)
    nodes = _nodes(graph)
    edge_set = {(edge.source, edge.target, edge.type) for edge in graph.edges}

    assert {node.type for node in graph.nodes} == set(NODE_TYPES) - {"Deployment"}
    assert {edge.type for edge in graph.edges} == set(EDGE_TYPES) - {"DEPLOYED_AS"}

    requirement_one = nodes["REQ-001"]
    requirement_two = nodes["REQ-002"]
    assert requirement_one.type == "Requirement"
    assert requirement_one.path == "requirements/REQ-001.yaml"
    assert (
        requirement_one.sha256
        == hashlib.sha256((tmp_path / "requirements" / "REQ-001.yaml").read_bytes()).hexdigest()
    )
    assert requirement_one.version == "1.0"
    assert requirement_one.last_changed_commit == commit_sha
    assert requirement_one.attributes == {
        "title": "Hold the temperature",
        "type": "functional",
        "status": "approved",
        "priority": "high",
        "verification": "test",
        "parent": None,
    }
    assert requirement_two.attributes["parent"] == "REQ-001"

    element = nodes["BLK-controller"]
    assert element.type == "ModelElement"
    assert element.path == "models/system.yaml"
    assert element.version == "1.0.0"
    assert element.sha256 == sha256_file(tmp_path / "models" / "system.yaml")
    assert element.attributes["satisfies"] == ["REQ-001", "REQ-002"]
    assert element.attributes["allocated_to"] == "src/app.py"

    code = nodes["src/app.py"]
    assert code.type == "CodeModule"
    assert code.sha256 == sha256_file(tmp_path / "src" / "app.py")
    assert code.attributes["implements"] == ["REQ-001", "REQ-002"]

    test_demo = nodes["tests/test_app.py::test_demo"]
    assert test_demo.type == "Test"
    assert test_demo.path == "tests/test_app.py"
    assert test_demo.sha256 == sha256_file(tmp_path / "tests" / "test_app.py")
    assert test_demo.attributes["requirements"] == ["REQ-001", "REQ-002"]
    assert test_demo.attributes["outcome"] == "passed"
    assert test_demo.attributes["duration"] == 0.01

    test_junit = nodes["tests/test_app.py::test_junit"]
    assert test_junit.attributes["outcome"] == "passed"
    assert test_junit.attributes["duration"] == 0.03

    test_method = nodes["tests/test_app.py::TestGroup::test_method"]
    assert test_method.attributes["requirements"] == ["REQ-002"]
    assert test_method.attributes["outcome"] == "failed"

    result = nodes["RESULT:tests/test_app.py::test_demo"]
    assert result.type == "TestResult"
    assert result.path == "tests/test_app.py"
    assert result.attributes == {"outcome": "passed", "duration": 0.01}

    report = nodes["build/reports/rtm.md"]
    assert report.type == "Report"
    assert report.sha256 == sha256_file(tmp_path / "build" / "reports" / "rtm.md")

    commit = nodes[commit_sha]
    assert commit.type == "Commit"
    assert commit.attributes["author"] == "Thread Tester"
    assert commit.attributes["short_sha"] == commit_sha[:7]
    assert commit.attributes["message"] == "Initial digital thread fixture"

    release = nodes["release-1.0.0"]
    assert release.type == "Release"
    assert release.attributes == {"version": "1.0.0"}

    expected_edges = {
        ("REQ-002", "REQ-001", "DERIVES_FROM"),
        ("BLK-controller", "REQ-001", "SATISFIES"),
        ("BLK-controller", "REQ-002", "SATISFIES"),
        ("BLK-controller", "src/app.py", "ALLOCATED_TO"),
        ("src/app.py", "REQ-001", "IMPLEMENTS"),
        ("src/app.py", "REQ-002", "IMPLEMENTS"),
        ("tests/test_app.py::test_demo", "REQ-001", "VERIFIES"),
        ("tests/test_app.py::test_demo", "REQ-002", "VERIFIES"),
        ("tests/test_app.py::test_demo", "src/app.py", "EXERCISES"),
        ("tests/test_app.py::TestGroup::test_method", "src/app.py", "EXERCISES"),
        (
            "RESULT:tests/test_app.py::test_demo",
            "tests/test_app.py::test_demo",
            "RESULT_OF",
        ),
        ("REQ-001", commit_sha, "CHANGED_IN"),
        ("src/app.py", commit_sha, "CHANGED_IN"),
        ("tests/test_app.py::test_demo", commit_sha, "CHANGED_IN"),
        (commit_sha, "release-1.0.0", "INCLUDED_IN"),
    }
    assert expected_edges <= edge_set


def test_deployment_environment_adds_node_edge_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit_sha = _write_project(tmp_path, with_git=True)
    monkeypatch.setenv("DEPLOY_ENVIRONMENT", "staging")
    monkeypatch.setenv("DEPLOY_IMAGE_TAG", "ghcr.io/demo/app:abc123")

    graph = build_graph(tmp_path)
    nodes = _nodes(graph)
    edge_set = {(edge.source, edge.target, edge.type) for edge in graph.edges}

    deployment_id = f"deployment-staging-{commit_sha}"
    deployment = nodes[deployment_id]
    assert deployment.type == "Deployment"
    assert deployment.path == ""
    assert deployment.version == "staging"
    assert deployment.sha256 == hashlib.sha256(commit_sha.encode("utf-8")).hexdigest()
    assert deployment.last_changed_commit == commit_sha
    assert deployment.attributes == {
        "environment": "staging",
        "image_tag": "ghcr.io/demo/app:abc123",
        "commit_sha": commit_sha,
    }
    assert (commit_sha, deployment_id, "DEPLOYED_AS") in edge_set
    assert graph.metadata["deployment"] == {
        "environment": "staging",
        "image_tag": "ghcr.io/demo/app:abc123",
        "commit_sha": commit_sha,
    }


def test_deployment_environment_absent_leaves_graph_unchanged(tmp_path: Path) -> None:
    _write_project(tmp_path, with_git=True)

    graph = build_graph(tmp_path)

    assert "Deployment" not in {node.type for node in graph.nodes}
    assert "DEPLOYED_AS" not in {edge.type for edge in graph.edges}
    assert "deployment" not in graph.metadata


def test_metadata_contains_commit_and_tool_information(tmp_path: Path) -> None:
    commit_sha = _write_project(tmp_path, with_git=True)

    metadata = collect_metadata(tmp_path)

    assert set(metadata) == {
        "commit_sha",
        "author",
        "timestamp",
        "workflow_run_id",
        "branch",
        "tool_versions",
    }
    assert metadata["commit_sha"] == commit_sha
    assert metadata["author"] == "Thread Tester"
    timestamp = datetime.fromisoformat(metadata["timestamp"])
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset().total_seconds() == 0
    assert set(metadata["tool_versions"]) == {"python", "networkx", "mbse"}


def test_serialization_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    _write_project(tmp_path, with_git=True)
    graph = build_graph(tmp_path)

    payload = graph_to_dict(graph)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["nodes"] == sorted(payload["nodes"], key=lambda item: (item["type"], item["id"]))
    assert payload["edges"] == sorted(
        payload["edges"], key=lambda item: (item["source"], item["target"], item["type"])
    )

    restored = graph_from_dict(payload)
    assert graph_to_dict(restored) == payload
    assert len(restored.nodes) == len(graph.nodes)
    assert len(restored.edges) == len(graph.edges)

    written = write_thread(graph, tmp_path)
    assert written == tmp_path / "digital_thread" / "thread.json"
    assert written.is_file()
    assert load_thread(tmp_path) == payload

    loaded = load_graph(tmp_path)
    assert graph_to_dict(loaded) == payload


def test_successive_builds_are_stable(tmp_path: Path) -> None:
    _write_project(tmp_path, with_git=True)

    first = graph_to_dict(build_graph(tmp_path))
    second = graph_to_dict(build_graph(tmp_path))

    assert first == second


def test_test_ids_supports_multiple_markers_and_class_methods(tmp_path: Path) -> None:
    _write_project(tmp_path, with_git=False)

    ids = test_ids(tmp_path)

    assert ids["tests/test_app.py::test_demo"] == ("REQ-001", "REQ-002")
    assert ids["tests/test_app.py::test_junit"] == ("REQ-002",)
    assert ids["tests/test_app.py::TestGroup::test_method"] == ("REQ-002",)


def test_missing_git_and_reports_degrade_gracefully(tmp_path: Path) -> None:
    _write_project(tmp_path, with_git=False, with_reports=False)

    assert load_thread(tmp_path) == {}
    assert load_graph(tmp_path).nodes == []

    graph = build_graph(tmp_path)
    nodes = _nodes(graph)
    edge_set = {(edge.source, edge.target, edge.type) for edge in graph.edges}

    assert graph.metadata["commit_sha"] == "local"
    assert nodes["local"].type == "Commit"
    assert nodes["local"].attributes["short_sha"] == "local"
    assert nodes["local"].attributes["message"] == ""
    assert "TestResult" not in {node.type for node in graph.nodes}
    assert "Report" not in {node.type for node in graph.nodes}
    assert all(node.last_changed_commit == "" for node in graph.nodes if node.type != "Commit")
    assert not any(edge_type == "CHANGED_IN" for _, _, edge_type in edge_set)
