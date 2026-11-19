"""Tests for the digital thread visualisation artifacts."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import networkx as nx
import pytest
from mbse import thread, thread_visual


def _node(
    node_id: str,
    node_type: str,
    path: str,
    *,
    version: str = "1.0",
    attributes: dict[str, object] | None = None,
) -> thread.ThreadNode:
    return thread.ThreadNode(
        id=node_id,
        type=node_type,
        path=path,
        sha256="a" * 64,
        version=version,
        last_changed_commit="0" * 40,
        attributes=dict(attributes or {}),
    )


def _graph() -> thread.ThreadGraph:
    nodes = [
        _node("REQ-001", "Requirement", "requirements/REQ-001.yaml", attributes={"title": "Heat"}),
        _node("REQ-002", "Requirement", "requirements/REQ-002.yaml", attributes={"title": "Cool"}),
        _node(
            "BLK-controller",
            "ModelElement",
            "models/system.yaml",
            attributes={"name": "Controller"},
        ),
        _node(
            "src/thermostat/controller.py",
            "CodeModule",
            "src/thermostat/controller.py",
            attributes={"implements": ["REQ-001"]},
        ),
        _node(
            "tests/unit/test_controller.py::test_heat",
            "Test",
            "tests/unit/test_controller.py",
            attributes={"requirements": ["REQ-001"]},
        ),
        _node(
            "RESULT:tests/unit/test_controller.py::test_heat",
            "TestResult",
            "tests/unit/test_controller.py",
            attributes={"outcome": "passed", "duration": 0.01},
        ),
        _node("build/reports/rtm.md", "Report", "build/reports/rtm.md"),
        _node("deadbeef", "Commit", "deadbeef", attributes={"short_sha": "deadbeef"}),
        _node("release-1.0", "Release", "release-1.0", version="1.0"),
    ]
    edges = [
        thread.ThreadEdge("REQ-002", "REQ-001", "DERIVES_FROM"),
        thread.ThreadEdge("BLK-controller", "REQ-001", "SATISFIES"),
        thread.ThreadEdge("BLK-controller", "src/thermostat/controller.py", "ALLOCATED_TO"),
        thread.ThreadEdge("src/thermostat/controller.py", "REQ-001", "IMPLEMENTS"),
        thread.ThreadEdge("tests/unit/test_controller.py::test_heat", "REQ-001", "VERIFIES"),
        thread.ThreadEdge(
            "tests/unit/test_controller.py::test_heat",
            "src/thermostat/controller.py",
            "EXERCISES",
        ),
        thread.ThreadEdge(
            "RESULT:tests/unit/test_controller.py::test_heat",
            "tests/unit/test_controller.py::test_heat",
            "RESULT_OF",
        ),
        thread.ThreadEdge("REQ-001", "deadbeef", "CHANGED_IN"),
        thread.ThreadEdge("deadbeef", "release-1.0", "INCLUDED_IN"),
    ]
    return thread.ThreadGraph(metadata={"commit_sha": "deadbeef"}, nodes=nodes, edges=edges)


def test_export_graphml_round_trips(tmp_path: Path) -> None:
    graph = _graph()
    path = thread_visual.export_graphml(graph, tmp_path / "thread.graphml")

    parsed = nx.read_graphml(path)
    assert parsed.number_of_nodes() == len(graph.nodes)
    assert parsed.number_of_edges() == len(graph.edges)
    assert parsed.nodes["REQ-001"]["type"] == "Requirement"
    assert parsed.nodes["REQ-001"]["label"] == "Heat"
    assert json.loads(parsed.nodes["REQ-001"]["attributes"]) == {"title": "Heat"}
    assert parsed.edges["REQ-002", "REQ-001"]["type"] == "DERIVES_FROM"


def test_export_dot_contains_nodes_and_styling(tmp_path: Path) -> None:
    graph = _graph()
    path = thread_visual.export_dot(graph, tmp_path / "thread.dot")

    text = path.read_text(encoding="utf-8")
    assert text.startswith("digraph digital_thread {")
    for node in graph.nodes:
        assert f'"{node.id}"' in text
    assert "fillcolor" in text
    assert "subgraph" in text
    assert '"REQ-002" -> "REQ-001" [label="DERIVES_FROM"]' in text


@pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz dot is not installed")
def test_render_svg_is_valid_xml(tmp_path: Path) -> None:
    graph = _graph()
    dot_path = thread_visual.export_dot(graph, tmp_path / "thread.dot")
    svg_path = thread_visual.render_svg(dot_path, tmp_path / "thread.svg")

    assert svg_path is not None
    assert svg_path.exists()
    root = ET.parse(svg_path).getroot()
    assert root.tag.endswith("svg")


def test_render_svg_without_dot_returns_none(tmp_path: Path, monkeypatch) -> None:
    graph = _graph()
    dot_path = thread_visual.export_dot(graph, tmp_path / "thread.dot")
    monkeypatch.setattr(thread_visual.shutil, "which", lambda name: None)

    assert thread_visual.render_svg(dot_path, tmp_path / "thread.svg") is None
    assert not (tmp_path / "thread.svg").exists()


def test_write_interactive_embeds_graph(tmp_path: Path) -> None:
    graph = _graph()
    paths = thread_visual.write_interactive(graph, tmp_path)

    assert paths == sorted(paths)
    assert all(path.exists() for path in paths)
    assert [path.name for path in paths] == ["thread.html", "thread.md"]

    html_text = (tmp_path / "docs" / "thread.html").read_text(encoding="utf-8")
    for node in graph.nodes:
        assert json.dumps(node.id) in html_text
    assert 'src="https://cdn.jsdelivr.net/npm/d3@7"' in html_text
    assert '"edges"' in html_text
    assert '"nodes"' in html_text

    markdown = (tmp_path / "docs" / "thread.md").read_text(encoding="utf-8")
    assert "thread.html" in markdown
    assert f"Nodes: {len(graph.nodes)}" in markdown
    assert f"Edges: {len(graph.edges)}" in markdown


def test_visualisations_are_deterministic(tmp_path: Path) -> None:
    graph = _graph()
    first = thread_visual.generate_visualizations(graph, tmp_path / "first")
    second = thread_visual.generate_visualizations(graph, tmp_path / "second")

    assert [path.relative_to(tmp_path / "first") for path in first] == [
        path.relative_to(tmp_path / "second") for path in second
    ]
    for left, right in zip(first, second, strict=True):
        assert left.read_bytes() == right.read_bytes(), left.name

    thread_visual.write_interactive(graph, tmp_path / "first")
    html_first = (tmp_path / "first" / "docs" / "thread.html").read_bytes()
    thread_visual.write_interactive(graph, tmp_path / "first")
    assert (tmp_path / "first" / "docs" / "thread.html").read_bytes() == html_first


def test_generate_visualizations_returns_sorted_existing_paths(tmp_path: Path) -> None:
    graph = _graph()
    paths = thread_visual.generate_visualizations(graph, tmp_path)

    assert paths == sorted(paths)
    assert all(path.exists() for path in paths)
    assert tmp_path / "build" / "reports" / "thread.graphml" in paths
    assert tmp_path / "build" / "reports" / "thread.dot" in paths
    assert tmp_path / "docs" / "thread.html" in paths
    assert tmp_path / "docs" / "thread.md" in paths
    if shutil.which("dot") is None:
        assert tmp_path / "build" / "reports" / "thread.svg" not in paths
    else:
        assert tmp_path / "build" / "reports" / "thread.svg" in paths
