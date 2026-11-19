"""Query helpers for the digital thread graph."""

from __future__ import annotations

import subprocess
from collections import deque
from pathlib import Path

from .thread import ThreadGraph, ThreadNode, load_graph


def resolve_node(graph: ThreadGraph, identifier: str) -> ThreadNode | None:
    """Resolve a node by exact id, test-id suffix, or requirement id."""
    if not identifier:
        return None
    for node in graph.nodes:
        if node.id == identifier:
            return node
    suffix = f"::{identifier}"
    matches = [
        node
        for node in graph.nodes
        if node.type == "Test" and (node.id.endswith(suffix) or node.id.endswith(identifier))
    ]
    if matches:
        return min(matches, key=lambda node: node.id)
    lowered = identifier.lower()
    for node in graph.nodes:
        if node.type == "Requirement" and node.id.lower() == lowered:
            return node
    return None


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


def _adjacency(graph: ThreadGraph, *, upstream: bool) -> dict[str, set[str]]:
    """Build a dependency adjacency, optionally traversing towards requirements."""
    result: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.type in _REVERSED_DEPENDENCY_EDGES:
            source, target = edge.target, edge.source
        else:
            source, target = edge.source, edge.target
        if upstream:
            source, target = target, source
        result.setdefault(source, set()).add(target)
    return result


def _walk(graph: ThreadGraph, identifier: str, *, upstream: bool) -> list[ThreadNode]:
    start = resolve_node(graph, identifier)
    if start is None:
        return []
    adjacency = _adjacency(graph, upstream=upstream)
    by_id = {node.id: node for node in graph.nodes}
    visited = {start.id}
    queue: deque[str] = deque([start.id])
    reached: list[ThreadNode] = []
    while queue:
        current = queue.popleft()
        for neighbour in sorted(adjacency.get(current, ())):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            node = by_id.get(neighbour)
            if node is not None:
                reached.append(node)
            queue.append(neighbour)
    return sorted(reached, key=lambda node: (node.type, node.id))


def downstream(graph: ThreadGraph, identifier: str) -> list[ThreadNode]:
    """Return nodes that depend on ``identifier``.

    Traversal follows dependency semantics: requirement -> model element ->
    code module -> test -> test result.  Edge types such as ``VERIFIES`` and
    ``RESULT_OF`` are stored in the opposite direction and are reversed here.
    """
    return _walk(graph, identifier, upstream=False)


def upstream(graph: ThreadGraph, identifier: str) -> list[ThreadNode]:
    """Return the artifacts ``identifier`` depends on."""
    return _walk(graph, identifier, upstream=True)


def _related(graph: ThreadGraph, node_id: str, edge_type: str) -> list[str]:
    related = {
        edge.target for edge in graph.edges if edge.source == node_id and edge.type == edge_type
    }
    related.update(
        edge.source for edge in graph.edges if edge.target == node_id and edge.type == edge_type
    )
    related.discard(node_id)
    return sorted(related)


def why_failed(graph: ThreadGraph, identifier: str) -> dict:
    """Explain why a test (or test result) failed."""
    node = resolve_node(graph, identifier)
    if node is None:
        return {
            "test": None,
            "result": None,
            "requirements": [],
            "code": [],
            "outcome": None,
        }

    by_id = {candidate.id: candidate for candidate in graph.nodes}
    result: ThreadNode | None = None
    test: ThreadNode | None = None

    if node.type == "TestResult":
        result = node
        parents = [
            edge.source
            for edge in graph.edges
            if edge.target == node.id and edge.type == "RESULT_OF"
        ]
        for test_id in sorted(parents):
            candidate = by_id.get(test_id)
            if candidate is not None and candidate.type == "Test":
                test = candidate
                break
        if test is None:
            parent = by_id.get(node.id.removeprefix("RESULT:"))
            if parent is not None and parent.type == "Test":
                test = parent
    elif node.type == "Test":
        test = node
        results = sorted(
            edge.source
            for edge in graph.edges
            if edge.target == node.id and edge.type == "RESULT_OF"
        )
        for result_id in results:
            candidate = by_id.get(result_id)
            if candidate is not None and candidate.type == "TestResult":
                result = candidate
                break
    else:
        test = node

    requirements = _related(graph, test.id, "VERIFIES") if test is not None else []
    code = _related(graph, test.id, "EXERCISES") if test is not None else []

    outcome = None
    if result is not None:
        outcome = result.attributes.get("outcome")
    if outcome is not None:
        outcome = str(outcome)

    return {
        "test": test,
        "result": result,
        "requirements": requirements,
        "code": code,
        "outcome": outcome,
    }


def history(root: Path | str, identifier: str) -> list[dict]:
    """Return git history entries for the node resolved from ``identifier``."""
    root_path = Path(root)
    graph = load_graph(root_path)
    node = resolve_node(graph, identifier)
    if node is None or not node.path:
        return []
    command = [
        "git",
        "log",
        "--follow",
        "--format=%H%x09%s",
        "--",
        node.path,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    entries: list[dict] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        commit, _, subject = line.partition("\t")
        entries.append({"commit": commit, "subject": subject})
    return entries
