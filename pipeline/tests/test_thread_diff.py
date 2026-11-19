"""Tests for digital thread diffing, staleness, snapshots, and reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mbse.thread import build_graph, graph_to_dict
from mbse.thread_diff import (
    apply_staleness,
    diff_graphs,
    update_thread,
    write_diff_report,
)

REQUIREMENT_ID = "REQ-001"
TEST_ID = "tests/unit/test_controller.py::test_control"
IMPLEMENTING_MODULE = "src/app.py"


def _write_requirement(root: Path, requirement_id: str = REQUIREMENT_ID) -> Path:
    """Write a minimal requirement artifact and return its path."""
    content = (
        f"id: {requirement_id}\n"
        'title: "Demo requirement"\n'
        'text: "The system shall satisfy the demo requirement."\n'
        "type: functional\n"
        "priority: high\n"
        "owner: team-demo\n"
        "verification: test\n"
        "status: approved\n"
        'rationale: "Keeps the demo traceable."\n'
    )
    path = root / "requirements" / f"{requirement_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_model(root: Path) -> Path:
    """Write a minimal system model allocated to the demo module."""
    content = (
        "system: DemoSystem\n"
        "version: 1.0.0\n"
        "elements:\n"
        "  - id: BLK-controller\n"
        "    kind: block\n"
        "    name: Controller\n"
        f"    satisfies: [{REQUIREMENT_ID}]\n"
        f"    allocated_to: {IMPLEMENTING_MODULE}\n"
        "relations: []\n"
    )
    path = root / "models" / "system.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_code(root: Path, requirement_id: str = REQUIREMENT_ID) -> Path:
    """Write a Python module tagged as implementing a requirement."""
    content = f"# @implements {requirement_id}\n\ndef demo() -> bool:\n    return True\n"
    path = root / IMPLEMENTING_MODULE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_test(root: Path, requirement_id: str = REQUIREMENT_ID) -> Path:
    """Write a requirement-tagged test module."""
    content = (
        "import pytest\n"
        "\n"
        f'@pytest.mark.req("{requirement_id}")\n'
        "def test_control() -> None:\n"
        "    assert True\n"
    )
    path = root / "tests" / "unit" / "test_controller.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a small project with a requirement, model, code, and test."""
    _write_requirement(tmp_path)
    _write_model(tmp_path)
    _write_code(tmp_path)
    _write_test(tmp_path)
    (tmp_path / "build" / "reports").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _node(graph, node_id: str):
    return next(node for node in graph.nodes if node.id == node_id)


def test_first_run_marks_everything_added_and_nothing_stale(project: Path) -> None:
    graph = build_graph(project)

    diff = diff_graphs({}, graph)

    assert diff["removed_nodes"] == []
    assert diff["removed_edges"] == []
    assert set(diff["added_nodes"]) == {node.id for node in graph.nodes}
    assert len(diff["added_edges"]) == len(graph.edges)
    assert apply_staleness(graph, {}, project) == []


def test_update_thread_writes_snapshot_thread_and_report(project: Path) -> None:
    result = update_thread(project)

    thread_path = project / "digital_thread" / "thread.json"
    history_directory = project / "digital_thread" / "history"
    report = project / "build" / "reports" / "thread_diff.md"

    assert result["stale"] == []
    assert result["thread"] == thread_path
    assert result["diff_report"] == report
    assert thread_path.is_file()
    assert report.is_file()

    snapshot = result["snapshot"]
    assert snapshot.parent == history_directory
    assert snapshot.suffix == ".json"
    assert snapshot.is_file()
    assert len(list(history_directory.glob("*.json"))) == 1
    assert result["diff"]["added_nodes"]

    written = json.loads(thread_path.read_text(encoding="utf-8"))
    assert {node["id"] for node in written["nodes"]} == {
        node_id for node_id in result["diff"]["added_nodes"]
    }

    text = report.read_text(encoding="utf-8")
    for heading in (
        "## Added nodes",
        "## Removed nodes",
        "## Modified nodes",
        "## Added edges",
        "## Removed edges",
        "## Stale nodes",
    ):
        assert heading in text
    assert "- none" in text


def test_requirement_change_marks_unchanged_downstream_test_stale(project: Path) -> None:
    previous = graph_to_dict(build_graph(project))
    requirement_path = project / "requirements" / f"{REQUIREMENT_ID}.yaml"
    requirement_path.write_text(
        requirement_path.read_text(encoding="utf-8") + "# reviewed change\n",
        encoding="utf-8",
    )

    current = build_graph(project)
    diff = diff_graphs(previous, current)

    assert REQUIREMENT_ID in diff["modified_nodes"]
    assert _node(current, TEST_ID).sha256 == next(
        node["sha256"] for node in previous["nodes"] if node["id"] == TEST_ID
    )

    stale = apply_staleness(current, previous, project)

    assert TEST_ID in stale
    assert IMPLEMENTING_MODULE in stale
    assert _node(current, TEST_ID).attributes.get("stale") is True
    assert _node(current, IMPLEMENTING_MODULE).attributes.get("stale") is True


def test_removed_test_yields_removed_nodes_and_edges(project: Path) -> None:
    previous = graph_to_dict(build_graph(project))
    test_path = project / "tests" / "unit" / "test_controller.py"
    test_path.write_text("def test_unrelated() -> None:\n    assert True\n", encoding="utf-8")

    current = build_graph(project)
    diff = diff_graphs(previous, current)

    assert TEST_ID in diff["removed_nodes"]
    removed = {(edge["source"], edge["target"], edge["type"]) for edge in diff["removed_edges"]}
    assert (TEST_ID, REQUIREMENT_ID, "VERIFIES") in removed


def test_added_implements_tag_yields_added_edge(project: Path) -> None:
    previous = graph_to_dict(build_graph(project))
    extra = project / "src" / "extra.py"
    extra.write_text(
        f"# @implements {REQUIREMENT_ID}\n\n\ndef extra() -> bool:\n    return True\n",
        encoding="utf-8",
    )

    current = build_graph(project)
    diff = diff_graphs(previous, current)

    assert "src/extra.py" in diff["added_nodes"]
    assert {
        "source": "src/extra.py",
        "target": REQUIREMENT_ID,
        "type": "IMPLEMENTS",
    } in diff["added_edges"]


def test_update_thread_second_run_reports_modified_and_stale(project: Path) -> None:
    update_thread(project)
    requirement_path = project / "requirements" / f"{REQUIREMENT_ID}.yaml"
    requirement_path.write_text(
        requirement_path.read_text(encoding="utf-8") + "# changed upstream\n",
        encoding="utf-8",
    )

    result = update_thread(project)

    assert REQUIREMENT_ID in result["diff"]["modified_nodes"]
    assert TEST_ID in result["stale"]
    report_text = Path(result["diff_report"]).read_text(encoding="utf-8")
    assert f"- {TEST_ID}" in report_text
    assert "- REQ-001" in report_text


def test_write_diff_report_is_deterministic(project: Path) -> None:
    diff = {
        "added_nodes": ["REQ-001"],
        "removed_nodes": [],
        "modified_nodes": [],
        "added_edges": [{"source": "tests/x.py::test_y", "target": "REQ-001", "type": "VERIFIES"}],
        "removed_edges": [],
    }

    first = write_diff_report(diff, ["tests/x.py::test_y"], project)
    first_text = first.read_text(encoding="utf-8")
    second = write_diff_report(diff, ["tests/x.py::test_y"], project)

    assert first == second
    assert second.read_text(encoding="utf-8") == first_text
    assert "- tests/x.py::test_y" in first_text
    assert "- tests/x.py::test_y -> REQ-001 (VERIFIES)" in first_text
