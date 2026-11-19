"""Digital thread visualisations: GraphML, DOT/SVG, and an interactive HTML page.

All outputs are deterministic: nodes and edges are sorted before serialisation and
no timestamps are embedded outside the thread metadata.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import networkx as nx

from .thread import ThreadEdge, ThreadGraph, ThreadNode

_REPORT_DIRECTORY = Path("build") / "reports"
_DOCS_DIRECTORY = Path("docs")

_GRAPHML_PATH = _REPORT_DIRECTORY / "thread.graphml"
_DOT_PATH = _REPORT_DIRECTORY / "thread.dot"
_SVG_PATH = _REPORT_DIRECTORY / "thread.svg"
_HTML_PATH = _DOCS_DIRECTORY / "thread.html"
_MARKDOWN_PATH = _DOCS_DIRECTORY / "thread.md"

_NODE_COLORS = {
    "Requirement": "#4e79a7",
    "ModelElement": "#f28e2b",
    "CodeModule": "#59a14f",
    "Test": "#e15759",
    "TestResult": "#b07aa1",
    "Report": "#76b7b2",
    "Commit": "#9c755f",
    "Release": "#bab0ac",
}

_NODE_SHAPES = {
    "Requirement": "box",
    "ModelElement": "box3d",
    "CodeModule": "component",
    "Test": "ellipse",
    "TestResult": "note",
    "Report": "folder",
    "Commit": "ellipse",
    "Release": "doubleoctagon",
}

_D3_URL = "https://cdn.jsdelivr.net/npm/d3@7"


def _write_text(path: Path, content: str) -> Path:
    """Write ``content`` to ``path``, creating parents and ending with a newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _sorted_nodes(graph: ThreadGraph) -> list[ThreadNode]:
    return sorted(graph.nodes, key=lambda node: (node.type, node.id))


def _sorted_edges(graph: ThreadGraph) -> list[ThreadEdge]:
    return sorted(graph.edges, key=lambda edge: (edge.source, edge.target, edge.type))


def _node_label(node: ThreadNode) -> str:
    """Return a short display label for ``node``."""
    for key in ("title", "name", "version"):
        value = node.attributes.get(key)
        if value:
            return str(value)
    return node.id


def _json_attribute(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _dot_escape(value: str) -> str:
    return (
        str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", "\\n")
    )


def _graphml_graph(graph: ThreadGraph) -> nx.DiGraph:
    """Build a scalar-attribute-only networkx graph for GraphML export."""
    result = nx.DiGraph()
    result.graph["schema_version"] = str(graph.metadata.get("schema_version", ""))
    result.graph["node_count"] = str(len(graph.nodes))
    result.graph["edge_count"] = str(len(graph.edges))
    for node in _sorted_nodes(graph):
        result.add_node(
            node.id,
            type=node.type,
            label=_node_label(node),
            path=node.path,
            sha256=node.sha256,
            version=node.version,
            last_changed_commit=node.last_changed_commit,
            attributes=_json_attribute(node.attributes),
        )
    for edge in _sorted_edges(graph):
        result.add_edge(
            edge.source,
            edge.target,
            type=edge.type,
            label=edge.type,
        )
    return result


def export_graphml(graph: ThreadGraph, path: str | Path) -> Path:
    """Write ``graph`` as GraphML, readable by :func:`networkx.read_graphml`."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(_graphml_graph(graph), destination)
    return destination


def export_dot(graph: ThreadGraph, path: str | Path) -> Path:
    """Write deterministic Graphviz DOT with per-type colours and clusters."""
    destination = Path(path)
    lines = [
        "digraph digital_thread {",
        '  graph [fontname="Helvetica", rankdir="LR"];',
        '  node [fontname="Helvetica", style="filled", color="#333333"];',
        '  edge [fontname="Helvetica", color="#666666"];',
    ]
    by_type: dict[str, list[ThreadNode]] = {}
    for node in _sorted_nodes(graph):
        by_type.setdefault(node.type, []).append(node)
    for node_type in sorted(by_type):
        colour = _NODE_COLORS.get(node_type, "#cccccc")
        shape = _NODE_SHAPES.get(node_type, "box")
        lines.append(f'  subgraph "cluster_{_dot_escape(node_type)}" {{')
        lines.append(f'    label="{_dot_escape(node_type)}";')
        for node in by_type[node_type]:
            attributes = ", ".join(
                (
                    f'label="{_dot_escape(_node_label(node))}"',
                    f'group="{_dot_escape(node_type)}"',
                    f'fillcolor="{colour}"',
                    f'shape="{shape}"',
                    'tooltip="' + _dot_escape(f"{node.type} {node.id}") + '"',
                )
            )
            lines.append(f'    "{_dot_escape(node.id)}" [{attributes}];')
        lines.append("  }")
    for edge in _sorted_edges(graph):
        lines.append(
            f'  "{_dot_escape(edge.source)}" -> "{_dot_escape(edge.target)}" '
            f'[label="{_dot_escape(edge.type)}"];'
        )
    lines.append("}")
    return _write_text(destination, "\n".join(lines))


def render_svg(dot_path: str | Path, svg_path: str | Path) -> Path | None:
    """Render ``dot_path`` to ``svg_path`` with Graphviz, if it is installed."""
    executable = shutil.which("dot")
    if executable is None:
        return None
    source = Path(dot_path)
    destination = Path(svg_path)
    if not source.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [executable, "-Tsvg", str(source), "-o", str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not destination.exists():
        return None
    return destination


def _graph_payload(graph: ThreadGraph) -> dict[str, list[dict[str, str]]]:
    return {
        "nodes": [
            {"id": node.id, "type": node.type, "label": _node_label(node)}
            for node in _sorted_nodes(graph)
        ],
        "edges": [
            {"source": edge.source, "target": edge.target, "type": edge.type}
            for edge in _sorted_edges(graph)
        ],
    }


def _json_for_script(value: object) -> str:
    """Return compact JSON safe to embed inside an inline ``<script>`` block."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Digital Thread</title>
<style>
  body {{ font-family: Helvetica, Arial, sans-serif; margin: 0; padding: 1rem 2rem; color: #222; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .5rem; }}
  #legend {{ display: flex; flex-wrap: wrap; gap: .75rem; font-size: .8rem; margin-bottom: .5rem; }}
  #legend span {{ display: inline-flex; align-items: center; gap: .3rem; }}
  #legend i {{ width: .8rem; height: .8rem; border-radius: .2rem; display: inline-block; }}
  svg {{ width: 100%; height: 720px; border: 1px solid #ddd; background: #fff; }}
  .link {{ stroke: #777; stroke-width: 1.2px; fill: none; }}
  .node text {{ font-size: 10px; pointer-events: none; }}
</style>
</head>
<body>
<h1>Digital Thread</h1>
<div id="legend"></div>
<svg id="thread" viewBox="0 0 1200 720" role="img" aria-label="Digital thread graph"></svg>
<script src="{d3_url}"></script>
<script>
const graph = {payload};
const colors = {colors};

const legend = d3.select("#legend");
const types = Array.from(new Set(graph.nodes.map((node) => node.type))).sort();
types.forEach((type) => {{
  legend.append("span")
    .html('<i style="background:' + (colors[type] || "#cccccc") + '"></i>' + type);
}});

const svg = d3.select("#thread");
const width = 1200;
const height = 720;
svg.attr("viewBox", "0 0 " + width + " " + height);

const simulation = d3.forceSimulation(graph.nodes)
  .force("link", d3.forceLink(graph.edges).id((node) => node.id).distance(90))
  .force("charge", d3.forceManyBody().strength(-260))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collide", d3.forceCollide(28));

svg.append("defs").append("marker")
  .attr("id", "arrow")
  .attr("viewBox", "0 -5 10 10")
  .attr("refX", 12)
  .attr("refY", 0)
  .attr("markerWidth", 6)
  .attr("markerHeight", 6)
  .attr("orient", "auto")
  .append("path")
  .attr("d", "M0,-5L10,0L0,5")
  .attr("fill", "#777");

const link = svg.append("g")
  .selectAll("line")
  .data(graph.edges)
  .join("line")
  .attr("class", "link")
  .attr("marker-end", "url(#arrow)");

const node = svg.append("g")
  .selectAll("g")
  .data(graph.nodes)
  .join("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", (event, d) => {{
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }})
    .on("drag", (event, d) => {{
      d.fx = event.x;
      d.fy = event.y;
    }})
    .on("end", (event, d) => {{
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }}));

node.append("circle")
  .attr("r", 6)
  .attr("fill", (d) => colors[d.type] || "#cccccc")
  .attr("stroke", "#333");

node.append("text")
  .attr("x", 9)
  .attr("y", 3)
  .text((d) => d.label ? d.label + " (" + d.id + ")" : d.id);

node.append("title").text((d) => d.type + " " + d.id);

simulation.on("tick", () => {{
  link
    .attr("x1", (d) => d.source.x)
    .attr("y1", (d) => d.source.y)
    .attr("x2", (d) => d.target.x)
    .attr("y2", (d) => d.target.y);
  node.attr("transform", (d) => "translate(" + d.x + "," + d.y + ")");
}});
</script>
</body>
</html>
"""


def write_interactive(graph: ThreadGraph, root: str | Path = Path(".")) -> list[Path]:
    """Write ``docs/thread.html`` and ``docs/thread.md`` under ``root``."""
    base = Path(root)
    payload = _graph_payload(graph)
    html_text = _HTML_TEMPLATE.format(
        d3_url=_D3_URL,
        payload=_json_for_script(payload),
        colors=json.dumps(_NODE_COLORS, sort_keys=True),
    )
    html_path = _write_text(base / _HTML_PATH, html_text)

    counts: dict[str, int] = {}
    for node in graph.nodes:
        counts[node.type] = counts.get(node.type, 0) + 1
    table = ["| Type | Count |", "| --- | --- |"]
    for node_type in sorted(counts):
        table.append(f"| {node_type} | {counts[node_type]} |")
    markdown = "\n".join(
        [
            "# Digital Thread",
            "",
            "Interactive graph of requirements, model elements, code, tests, and reports.",
            "",
            (
                '<iframe src="thread.html" title="Digital thread graph" '
                'width="100%" height="720" style="border:1px solid #ddd;"></iframe>'
            ),
            "",
            "## Summary",
            "",
            f"- Nodes: {len(graph.nodes)}",
            f"- Edges: {len(graph.edges)}",
            "",
            *table,
            "",
        ]
    )
    markdown_path = _write_text(base / _MARKDOWN_PATH, markdown)
    return sorted([html_path, markdown_path])


def generate_visualizations(graph: ThreadGraph, root: str | Path = Path(".")) -> list[Path]:
    """Write GraphML, DOT, optional SVG, and the interactive page under ``root``."""
    base = Path(root)
    written: list[Path] = []
    written.append(export_graphml(graph, base / _GRAPHML_PATH))
    written.append(export_dot(graph, base / _DOT_PATH))
    svg_path = render_svg(base / _DOT_PATH, base / _SVG_PATH)
    if svg_path is not None:
        written.append(svg_path)
    written.extend(write_interactive(graph, base))
    return sorted(path for path in written if path.exists())
