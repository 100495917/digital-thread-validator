"""Digital thread diffing, staleness propagation, and snapshot persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .thread import ThreadGraph, build_graph, graph_to_dict, load_thread, write_thread

REPORT_DIRECTORY = Path("build") / "reports"
DIFF_REPORT_PATH = REPORT_DIRECTORY / "thread_diff.md"
THREAD_DIRECTORY = Path("digital_thread")
HISTORY_DIRECTORY = THREAD_DIRECTORY / "history"

# Edge types whose stored direction points from the dependent artifact to the
# artifact it depends on.  Staleness has to look at the reverse orientation.
_REVERSED_DEPENDENCY_EDGES = frozenset(
    {
        "DERIVES_FROM",
        "SATISFIES",
        "IMPLEMENTS",
        "VERIFIES",
        "EXERCISES",
        "RESULT_OF",
    }
)

_STALE_DOWNSTREAM_TYPES = frozenset({"Test", "CodeModule", "TestResult"})


def _previous_nodes(previous: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the raw previous snapshot by node id, ignoring malformed entries."""
    nodes = previous.get("nodes") if isinstance(previous, dict) else None
    indexed: dict[str, dict[str, Any]] = {}
    for node in nodes or []:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            indexed[node["id"]] = node
    return indexed


def _attributes_key(attributes: Any) -> str:
    """Serialize attributes deterministically for equality checks."""
    if not isinstance(attributes, dict):
        attributes = {}
    return json.dumps(attributes, sort_keys=True, default=str, separators=(",", ":"))


def _edge_key(edge: Any) -> tuple[str, str, str] | None:
    """Return the ``(source, target, type)`` identity of a raw edge."""
    if not isinstance(edge, dict):
        return None
    source = edge.get("source")
    target = edge.get("target")
    edge_type = edge.get("type")
    if isinstance(source, str) and isinstance(target, str) and isinstance(edge_type, str):
        return source, target, edge_type
    return None


def diff_graphs(previous: dict[str, Any], current: ThreadGraph) -> dict[str, Any]:
    """Compare a raw previous snapshot with the current thread graph."""
    previous_nodes = _previous_nodes(previous)
    current_nodes = {node.id: node for node in current.nodes}

    added_nodes = sorted(set(current_nodes) - set(previous_nodes))
    removed_nodes = sorted(set(previous_nodes) - set(current_nodes))
    modified_nodes = sorted(
        node_id
        for node_id in set(current_nodes) & set(previous_nodes)
        if current_nodes[node_id].sha256 != previous_nodes[node_id].get("sha256")
        or _attributes_key(current_nodes[node_id].attributes)
        != _attributes_key(previous_nodes[node_id].get("attributes"))
    )

    previous_edges = {key for key in map(_edge_key, previous.get("edges") or []) if key is not None}
    current_edges = {(edge.source, edge.target, edge.type) for edge in current.edges}

    added_edges = [
        {"source": source, "target": target, "type": edge_type}
        for source, target, edge_type in sorted(current_edges - previous_edges)
    ]
    removed_edges = [
        {"source": source, "target": target, "type": edge_type}
        for source, target, edge_type in sorted(previous_edges - current_edges)
    ]

    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "modified_nodes": modified_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
    }


def _dependency_pairs(current: ThreadGraph) -> list[tuple[str, str]]:
    """Return ``(upstream, downstream)`` pairs following dependency semantics."""
    pairs: list[tuple[str, str]] = []
    for edge in current.edges:
        if edge.type in _REVERSED_DEPENDENCY_EDGES:
            pairs.append((edge.target, edge.source))
        else:
            pairs.append((edge.source, edge.target))
    return pairs


def apply_staleness(
    current: ThreadGraph, previous: dict[str, Any], root: Path = Path(".")
) -> list[str]:
    """Flag artifacts whose upstream changed while their own content did not."""
    del root  # accepted for a uniform update API; no filesystem access is needed
    previous_nodes = _previous_nodes(previous)
    current_nodes = {node.id: node for node in current.nodes}
    stale: set[str] = set()

    for upstream_id, downstream_id in _dependency_pairs(current):
        upstream = current_nodes.get(upstream_id)
        downstream = current_nodes.get(downstream_id)
        if upstream is None or downstream is None:
            continue
        previous_upstream = previous_nodes.get(upstream_id)
        previous_downstream = previous_nodes.get(downstream_id)
        if previous_upstream is None or previous_downstream is None:
            continue
        if downstream.type not in _STALE_DOWNSTREAM_TYPES:
            continue
        if upstream.sha256 == previous_upstream.get("sha256"):
            continue
        if downstream.sha256 != previous_downstream.get("sha256"):
            continue
        stale.add(downstream.id)

    # A stale test makes the result produced by it stale as well.
    for edge in current.edges:
        if edge.type != "RESULT_OF":
            continue
        result = current_nodes.get(edge.source)
        test = current_nodes.get(edge.target)
        if result is None or test is None:
            continue
        if test.id in stale and test.type == "Test" and result.type == "TestResult":
            stale.add(result.id)

    for node_id in sorted(stale):
        current_nodes[node_id].attributes["stale"] = True
    return sorted(stale)


def _node_lines(node_ids: list[str]) -> list[str]:
    return [f"- {node_id}" for node_id in node_ids] or ["- none"]


def _edge_lines(edges: list[dict[str, str]]) -> list[str]:
    return [f"- {edge['source']} -> {edge['target']} ({edge['type']})" for edge in edges] or [
        "- none"
    ]


def write_diff_report(diff: dict[str, Any], stale: list[str], root: Path = Path(".")) -> Path:
    """Write the deterministic Markdown diff report under ``build/reports``."""
    path = Path(root) / DIFF_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Digital thread diff",
        "",
        "## Added nodes",
        *_node_lines(diff.get("added_nodes", [])),
        "",
        "## Removed nodes",
        *_node_lines(diff.get("removed_nodes", [])),
        "",
        "## Modified nodes",
        *_node_lines(diff.get("modified_nodes", [])),
        "",
        "## Added edges",
        *_edge_lines(diff.get("added_edges", [])),
        "",
        "## Removed edges",
        *_edge_lines(diff.get("removed_edges", [])),
        "",
        "## Stale nodes",
        *_node_lines(stale),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def update_thread(root: Path = Path(".")) -> dict[str, Any]:
    """Build, diff, mark stale, persist a snapshot, and rewrite the thread."""
    root = Path(root)
    previous = load_thread(root)
    current = build_graph(root)

    diff = diff_graphs(previous, current)
    stale = apply_staleness(current, previous, root)

    metadata = current.metadata if isinstance(current.metadata, dict) else {}
    snapshot_name = str(metadata.get("commit_sha") or "local")
    history_directory = root / HISTORY_DIRECTORY
    history_directory.mkdir(parents=True, exist_ok=True)
    snapshot = history_directory / f"{snapshot_name}.json"
    snapshot.write_text(
        json.dumps(graph_to_dict(current), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    thread_path = write_thread(current, root)
    diff_report = write_diff_report(diff, stale, root)

    return {
        "thread": thread_path,
        "snapshot": snapshot,
        "diff_report": diff_report,
        "diff": diff,
        "stale": stale,
    }
