"""Tests for digital-thread graph queries."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mbse.thread import (
    ThreadEdge,
    ThreadGraph,
    ThreadNode,
    sha256_file,
    write_thread,
)
from mbse.thread_query import (
    downstream,
    history,
    resolve_node,
    upstream,
    why_failed,
)

TEST_ID = "tests/test_app.py::test_demo"
RESULT_ID = f"RESULT:{TEST_ID}"


def _node(
    node_id: str,
    node_type: str,
    *,
    path: str = "",
    sha: str = "",
    version: str = "1.0",
    last_changed_commit: str = "",
    **attributes: object,
) -> ThreadNode:
    return ThreadNode(
        id=node_id,
        type=node_type,
        path=path,
        sha256=sha,
        version=version,
        last_changed_commit=last_changed_commit,
        attributes=dict(attributes),
    )


def _graph() -> ThreadGraph:
    nodes = [
        _node(
            "REQ-001",
            "Requirement",
            path="requirements/REQ-001.yaml",
            sha="a" * 64,
            title="Hold temperature",
            type="functional",
            status="approved",
            priority="high",
            verification="test",
            parent=None,
        ),
        _node(
            "BLK-controller",
            "ModelElement",
            path="models/system.yaml",
            sha="b" * 64,
            version="1.0.0",
            kind="block",
            name="Controller",
            satisfies=["REQ-001"],
            allocated_to="src/app.py",
        ),
        _node(
            "src/app.py",
            "CodeModule",
            path="src/app.py",
            sha="c" * 64,
            implements=["REQ-001"],
        ),
        _node(
            TEST_ID,
            "Test",
            path="tests/test_app.py",
            sha="d" * 64,
            requirements=["REQ-001"],
            outcome="failed",
            duration=0.25,
        ),
        _node(
            RESULT_ID,
            "TestResult",
            path="tests/test_app.py",
            sha="d" * 64,
            outcome="failed",
            duration=0.25,
        ),
    ]
    edges = [
        ThreadEdge(source="BLK-controller", target="REQ-001", type="SATISFIES"),
        ThreadEdge(source="BLK-controller", target="src/app.py", type="ALLOCATED_TO"),
        ThreadEdge(source="src/app.py", target="REQ-001", type="IMPLEMENTS"),
        ThreadEdge(source=TEST_ID, target="REQ-001", type="VERIFIES"),
        ThreadEdge(source=TEST_ID, target="src/app.py", type="EXERCISES"),
        ThreadEdge(source=RESULT_ID, target=TEST_ID, type="RESULT_OF"),
    ]
    return ThreadGraph(metadata={"commit_sha": "local"}, nodes=nodes, edges=edges)


def test_resolve_node_supports_ids_suffixes_and_case() -> None:
    graph = _graph()

    assert resolve_node(graph, "REQ-001") is not None
    assert resolve_node(graph, "req-001").id == "REQ-001"  # type: ignore[union-attr]
    assert resolve_node(graph, "test_demo").id == TEST_ID  # type: ignore[union-attr]
    assert resolve_node(graph, "test_app.py::test_demo").id == TEST_ID  # type: ignore[union-attr]
    assert resolve_node(graph, "RESULT:" + TEST_ID).id == RESULT_ID  # type: ignore[union-attr]
    assert resolve_node(graph, "unknown") is None


def test_downstream_from_requirement_reaches_artifacts_in_dependency_order() -> None:
    graph = _graph()

    reached = downstream(graph, "REQ-001")

    assert [node.id for node in reached] == [
        "src/app.py",
        "BLK-controller",
        TEST_ID,
        RESULT_ID,
    ]
    assert [(node.type) for node in reached] == [
        "CodeModule",
        "ModelElement",
        "Test",
        "TestResult",
    ]


def test_upstream_from_test_reaches_requirement_and_code() -> None:
    graph = _graph()

    reached = upstream(graph, "test_demo")

    assert [node.id for node in reached] == ["src/app.py", "BLK-controller", "REQ-001"]
    assert "REQ-001" in {node.id for node in reached}
    assert RESULT_ID not in {node.id for node in reached}


def test_unknown_identifier_yields_empty_traversals() -> None:
    graph = _graph()

    assert downstream(graph, "missing") == []
    assert upstream(graph, "missing") == []


def test_why_failed_reports_outcome_requirements_and_code() -> None:
    graph = _graph()

    explanation = why_failed(graph, "test_demo")

    assert explanation["test"].id == TEST_ID
    assert explanation["result"].id == RESULT_ID
    assert explanation["outcome"] == "failed"
    assert explanation["requirements"] == ["REQ-001"]
    assert explanation["code"] == ["src/app.py"]


def test_why_failed_accepts_result_id() -> None:
    graph = _graph()

    explanation = why_failed(graph, RESULT_ID)

    assert explanation["test"].id == TEST_ID
    assert explanation["result"].id == RESULT_ID
    assert explanation["outcome"] == "failed"
    assert explanation["requirements"] == ["REQ-001"]


def test_why_failed_without_result_has_no_outcome() -> None:
    graph = ThreadGraph(
        metadata={},
        nodes=[
            _node("REQ-001", "Requirement", path="requirements/REQ-001.yaml"),
            _node(
                TEST_ID,
                "Test",
                path="tests/test_app.py",
                requirements=["REQ-001"],
            ),
        ],
        edges=[ThreadEdge(source=TEST_ID, target="REQ-001", type="VERIFIES")],
    )

    explanation = why_failed(graph, "test_demo")

    assert explanation["result"] is None
    assert explanation["outcome"] is None
    assert explanation["requirements"] == ["REQ-001"]


def test_why_failed_unknown_node() -> None:
    explanation = why_failed(_graph(), "nope")

    assert explanation["test"] is None
    assert explanation["outcome"] is None
    assert explanation["requirements"] == []


def _write_thread(root: Path) -> dict:
    graph = _graph()
    requirement = root / "requirements" / "REQ-001.yaml"
    requirement.parent.mkdir(parents=True, exist_ok=True)
    requirement.write_text("id: REQ-001\n", encoding="utf-8")
    for node in graph.nodes:
        if node.path and (root / node.path).exists():
            node.sha256 = sha256_file(root / node.path)
    thread_path = write_thread(graph, root)
    return json.loads(thread_path.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_history_returns_commits_from_a_git_repository(tmp_path: Path) -> None:
    _write_thread(tmp_path)
    requirement = tmp_path / "requirements" / "REQ-001.yaml"
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "add", "."],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "Update requirement",
        ],
        cwd=tmp_path,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    entries = history(tmp_path, "REQ-001")

    assert entries
    assert entries[0] == {"commit": commit, "subject": "Update requirement"}
    assert requirement.exists()


def test_history_without_git_returns_empty(tmp_path: Path) -> None:
    _write_thread(tmp_path)

    assert history(tmp_path, "REQ-001") == []
    assert history(tmp_path, "unknown") == []
