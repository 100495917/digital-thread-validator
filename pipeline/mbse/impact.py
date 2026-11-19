"""Impact analysis for changed artifacts and selective test selection.

The module maps changed files onto digital-thread nodes, walks the dependency
graph in both directions, and classifies the reached artifacts into direct
changes, impacted artifacts, review candidates, and tests that need rerunning.
It also produces a requirement traceability matrix diff between two git
revisions.  Git, report, and thread failures degrade gracefully and never raise
out of the public helpers.
"""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

from .loaders import LoadError
from .thread import ThreadGraph, ThreadNode, build_graph, load_graph

REPORT_DIRECTORY = Path("build") / "reports"
IMPACT_JSON = REPORT_DIRECTORY / "impact.json"
IMPACT_MARKDOWN = REPORT_DIRECTORY / "impact.md"
RTM_DIFF_MARKDOWN = REPORT_DIRECTORY / "rtm_diff.md"
RTM_CSV = REPORT_DIRECTORY / "rtm.csv"

_CLASSIFIABLE_TYPES = frozenset({"Requirement", "ModelElement", "CodeModule", "Test"})
_CLASSIFICATION_KEYS = ("directly_changed", "impacted", "needs_review", "needs_retest")
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
_BASE_TREE_PREFIXES = ("requirements/", "models/", "src/", "tests/")


# ---------------------------------------------------------------------------
# Git helpers -- always return ``None``/empty on failure.
# ---------------------------------------------------------------------------


def _git_output(root: Path, *arguments: str) -> bytes | None:
    """Run git in ``root`` and return raw stdout, or ``None`` on any failure."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str | None:
    """Run git in ``root`` and return decoded stdout, or ``None`` on failure."""
    output = _git_output(root, *arguments)
    if output is None:
        return None
    return output.decode("utf-8", errors="replace")


def _changed_files(base: str, head: str, root: Path) -> list[str]:
    """Return changed paths between ``base`` and ``head``, sorted and unique."""
    output = _git_text(root, "diff", "--name-only", f"{base}...{head}")
    if output is None:
        output = _git_text(root, "diff", "--name-only", base, head)
    if output is None:
        return []
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


# ---------------------------------------------------------------------------
# Graph loading and changed-file mapping
# ---------------------------------------------------------------------------


def _graph_for(root: Path) -> ThreadGraph:
    """Load the persisted thread when available, otherwise build it in memory."""
    try:
        graph = load_graph(root)
    except (
        LoadError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):  # pragma: no cover - defensive against malformed snapshots
        graph = None
    if graph is not None and graph.nodes:
        return graph
    try:
        return build_graph(root)
    except (
        LoadError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):  # pragma: no cover - a broken project must not abort a report
        return ThreadGraph(metadata={}, nodes=[], edges=[])


def _is_mapped(node: ThreadNode, changed: str) -> bool:
    """Return whether ``changed`` directly maps onto ``node``."""
    if node.path != changed:
        return False
    if changed.startswith("requirements/") and changed.endswith((".yaml", ".yml")):
        return node.type == "Requirement"
    if changed == "models/system.yaml":
        return node.type == "ModelElement"
    if changed.startswith("src/") and changed.endswith(".py"):
        return node.type == "CodeModule"
    if changed.startswith("tests/") and changed.endswith(".py"):
        return node.type == "Test"
    return False


def _direct_mapping(graph: ThreadGraph, changed_files: list[str]) -> dict[str, set[str]]:
    """Map changed files onto node ids, collecting one reason per file."""
    mapping: dict[str, set[str]] = {}
    nodes = [node for node in graph.nodes if node.type in _CLASSIFIABLE_TYPES]
    for changed in changed_files:
        for node in nodes:
            if _is_mapped(node, changed):
                mapping.setdefault(node.id, set()).add(f"changed file: {changed}")
    return mapping


# ---------------------------------------------------------------------------
# Dependency traversal
# ---------------------------------------------------------------------------


def _adjacency(graph: ThreadGraph, *, upstream: bool) -> dict[str, set[str]]:
    """Build an adjacency keyed by logical flow, honouring reversed edges."""
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


def _bfs(adjacency: dict[str, set[str]], starts: list[str]) -> dict[str, int]:
    """Return the shortest depth from any start to every reachable node."""
    distance: dict[str, int] = {start: 0 for start in starts}
    queue: deque[str] = deque(sorted(distance))
    while queue:
        current = queue.popleft()
        for neighbour in sorted(adjacency.get(current, ())):
            if neighbour in distance:
                continue
            distance[neighbour] = distance[current] + 1
            queue.append(neighbour)
    return distance


def _merge(*runs: dict[str, int]) -> dict[str, int]:
    """Merge BFS runs keeping the minimum depth for each node."""
    merged: dict[str, int] = {}
    for run in runs:
        for node_id, depth in run.items():
            merged[node_id] = min(depth, merged.get(node_id, depth))
    return merged


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyse_impact(base: str, head: str = "HEAD", root: Path = Path(".")) -> dict:
    """Analyse the impact of ``base..head`` and return the report dictionary."""
    root = Path(root)
    changed = _changed_files(base, head, root)
    graph = _graph_for(root)
    by_id = {node.id: node for node in graph.nodes}

    direct_map = _direct_mapping(graph, changed)
    direct = {node_id for node_id in direct_map if node_id in by_id}
    reasons: dict[str, set[str]] = {node_id: set(values) for node_id, values in direct_map.items()}

    changed_requirements = [n for n in direct if by_id[n].type == "Requirement"]
    changed_models = [n for n in direct if by_id[n].type == "ModelElement"]
    changed_code = [n for n in direct if by_id[n].type == "CodeModule"]
    changed_tests = [n for n in direct if by_id[n].type == "Test"]

    downstream = _adjacency(graph, upstream=False)
    upstream = _adjacency(graph, upstream=True)

    req_down = _bfs(downstream, sorted(changed_requirements))
    model_down = _bfs(downstream, sorted(changed_models))
    code_down = _bfs(downstream, sorted(changed_code))
    test_down = _bfs(downstream, sorted(changed_tests))
    upstream_reach = _bfs(upstream, sorted(changed_code + changed_tests))

    # Record human-readable provenance for every reached artifact.
    for origins, reach in (
        (changed_requirements, req_down),
        (changed_models, model_down),
        (changed_code, code_down),
        (changed_tests, test_down),
    ):
        for origin in origins:
            for node_id in reach:
                if node_id != origin:
                    reasons.setdefault(node_id, set()).add(f"downstream of {origin}")
    for origin in sorted(changed_code + changed_tests):
        for node_id in upstream_reach:
            if node_id != origin:
                reasons.setdefault(node_id, set()).add(f"upstream of {origin}")

    reached = _merge(req_down, model_down, code_down, test_down, upstream_reach)
    for node_id in direct:
        reached[node_id] = 0

    def nodes_of(reach: dict[str, int], node_type: str) -> set[str]:
        return {
            node_id
            for node_id in reach
            if node_id in by_id and by_id[node_id].type == node_type and node_id not in direct
        }

    needs_retest = nodes_of(req_down, "Test") | nodes_of(model_down, "Test")
    needs_retest |= nodes_of(code_down, "Test") | nodes_of(test_down, "Test")
    needs_retest |= set(changed_tests)

    needs_review = nodes_of(req_down, "ModelElement")
    needs_review |= nodes_of(upstream_reach, "Requirement")
    needs_review |= nodes_of(req_down, "Requirement")

    claimed = direct | needs_retest | needs_review
    impacted = {
        node_id
        for node_id in reached
        if node_id in by_id
        and by_id[node_id].type in _CLASSIFIABLE_TYPES
        and node_id not in claimed
    }

    def entries(ids: set[str]) -> list[dict[str, Any]]:
        return [
            {
                "id": node_id,
                "type": by_id[node_id].type,
                "path": by_id[node_id].path,
                "reasons": sorted(reasons.get(node_id, set())),
            }
            for node_id in sorted(ids)
        ]

    artifacts = {
        "directly_changed": entries(direct),
        "impacted": entries(impacted),
        "needs_review": entries(needs_review),
        "needs_retest": entries(needs_retest),
    }
    summary = {"changed_files": len(changed)}
    for key in _CLASSIFICATION_KEYS:
        summary[key] = len(artifacts[key])

    direct_requirements = sorted(
        node_id for node_id in direct if by_id[node_id].type == "Requirement"
    )
    affected_requirements = sorted(
        {
            node_id
            for node_id in list(reached) + list(direct)
            if node_id in by_id and by_id[node_id].type == "Requirement"
        }
    )
    requirement_types = {
        str(by_id[node_id].attributes.get("type", "")).strip().lower()
        for node_id in affected_requirements
    }
    safety = sum(
        1
        for node_id in affected_requirements
        if str(by_id[node_id].attributes.get("type", "")).strip().lower() == "safety"
    )
    security = sum(
        1
        for node_id in affected_requirements
        if str(by_id[node_id].attributes.get("type", "")).strip().lower() == "security"
    )
    max_depth = max(
        (
            depth
            for node_id, depth in reached.items()
            if node_id in by_id and by_id[node_id].type in _CLASSIFIABLE_TYPES
        ),
        default=0,
    )
    affected_artifacts = len(direct) + len(impacted) + len(needs_review) + len(needs_retest)

    if {"safety", "security"} & requirement_types or len(needs_retest) > 8:
        level = "high"
    elif len(changed) > 3 or affected_artifacts > 10:
        level = "medium"
    else:
        level = "low"

    return {
        "base": base,
        "head": head,
        "changed_files": changed,
        "artifacts": artifacts,
        "summary": summary,
        "risk": {
            "level": level,
            "safety_requirements": safety,
            "security_requirements": security,
            "depth": max_depth,
            "changed_files": len(changed),
        },
        "requirements": {"direct": direct_requirements, "affected": affected_requirements},
    }


# ---------------------------------------------------------------------------
# Impact report
# ---------------------------------------------------------------------------


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _classification_table(entries: list[dict[str, Any]]) -> list[str]:
    lines = ["| ID | Type | Path | Reasons |", "| --- | --- | --- | --- |"]
    for entry in entries:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    entry["id"],
                    entry["type"],
                    entry["path"],
                    ", ".join(entry["reasons"]),
                )
            )
            + " |"
        )
    return lines


def _report_markdown(report: dict, root: Path) -> str:
    summary = report["summary"]
    risk = report["risk"]
    lines = [
        "# Impact Analysis",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Base | {_markdown_cell(report['base'])} |",
        f"| Head | {_markdown_cell(report['head'])} |",
    ]
    for label, key in (
        ("Changed files", "changed_files"),
        ("Directly changed", "directly_changed"),
        ("Impacted", "impacted"),
        ("Needs review", "needs_review"),
        ("Needs retest", "needs_retest"),
    ):
        lines.append(f"| {label} | {summary[key]} |")

    lines.extend(
        [
            "",
            "## Risk",
            "",
            "| Risk | Value |",
            "| --- | --- |",
            f"| Level | {risk['level']} |",
            f"| Safety requirements | {risk['safety_requirements']} |",
            f"| Security requirements | {risk['security_requirements']} |",
            f"| Depth | {risk['depth']} |",
            f"| Changed files | {risk['changed_files']} |",
            "",
        ]
    )

    for title, key in (
        ("Directly changed", "directly_changed"),
        ("Impacted", "impacted"),
        ("Needs review", "needs_review"),
        ("Needs retest", "needs_retest"),
    ):
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(_classification_table(report["artifacts"][key]))
        lines.append("")

    lines.extend(["## Changed files", ""])
    if report["changed_files"]:
        lines.extend(f"- {path}" for path in report["changed_files"])
    else:
        lines.append("None.")
    lines.append("")

    report_directory = root / REPORT_DIRECTORY
    for title, filename in (("RTM Diff", "rtm_diff.md"), ("Thread Diff", "thread_diff.md")):
        path = report_directory / filename
        try:
            content = path.read_text(encoding="utf-8").rstrip()
        except (OSError, UnicodeDecodeError):
            continue
        if not content:
            continue
        lines.extend([f"## {title}", "", content, ""])

    return "\n".join(lines).rstrip() + "\n"


def write_impact(report: dict, root: Path = Path(".")) -> tuple[Path, Path]:
    """Write ``impact.json`` and ``impact.md``; return both paths."""
    root = Path(root)
    report_directory = root / REPORT_DIRECTORY
    report_directory.mkdir(parents=True, exist_ok=True)

    json_path = root / IMPACT_JSON
    markdown_path = root / IMPACT_MARKDOWN
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_report_markdown(report, root), encoding="utf-8")
    return json_path, markdown_path


# ---------------------------------------------------------------------------
# RTM diff
# ---------------------------------------------------------------------------


def _selected_base_paths(base: str, root: Path) -> list[str] | None:
    """List base revision files that participate in traceability."""
    output = _git_text(root, "ls-tree", "-r", "--name-only", base)
    if output is None:
        return None
    return [path for path in output.splitlines() if path.startswith(_BASE_TREE_PREFIXES)]


def _materialise_tree(base: str, root: Path, destination: Path) -> bool:
    """Copy base revision artifacts into ``destination``; return success."""
    paths = _selected_base_paths(base, root)
    if not paths:
        return False
    for path in paths:
        content = _git_output(root, "show", f"{base}:{path}")
        if content is None:
            return False
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return True


def _read_rtm(path: Path) -> dict[str, dict[str, str]] | None:
    """Read an RTM CSV into a row mapping keyed by Req ID."""
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows: dict[str, dict[str, str]] = {}
            for row in reader:
                requirement_id = (row.get("Req ID") or "").strip()
                if requirement_id:
                    rows[requirement_id] = {
                        str(key): str(value or "") for key, value in row.items() if key
                    }
        return rows
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def _unavailable_rtm_diff(base: str, head: str, reason: str) -> str:
    return f"# RTM Diff\n\nBase: `{base}`\n\nHead: `{head}`\n\nRTM diff unavailable: {reason}.\n"


def _compare_rtm(
    base_rows: dict[str, dict[str, str]],
    head_rows: dict[str, dict[str, str]],
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Return added, removed, and changed requirement ids with changed fields."""
    added = sorted(set(head_rows) - set(base_rows))
    removed = sorted(set(base_rows) - set(head_rows))
    changed: dict[str, list[str]] = {}
    for requirement_id in sorted(set(base_rows) & set(head_rows)):
        fields = sorted(
            key
            for key in set(base_rows[requirement_id]) | set(head_rows[requirement_id])
            if base_rows[requirement_id].get(key, "") != head_rows[requirement_id].get(key, "")
        )
        if fields:
            changed[requirement_id] = fields
    return added, removed, changed


def write_rtm_diff(base: str, head: str, root: Path = Path(".")) -> Path:
    """Write ``build/reports/rtm_diff.md`` comparing the base and current RTM."""
    root = Path(root)
    report_directory = root / REPORT_DIRECTORY
    path = root / RTM_DIFF_MARKDOWN
    try:
        report_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return path

    def unavailable(reason: str) -> Path:
        try:
            path.write_text(_unavailable_rtm_diff(base, head, reason), encoding="utf-8")
        except OSError:
            pass
        return path

    try:
        from .trace import write_rtm

        write_rtm(root)
    except (LoadError, OSError, ValueError, KeyError, TypeError):
        return unavailable("could not build the current requirement traceability matrix")

    head_rows = _read_rtm(root / RTM_CSV)
    if head_rows is None:
        return unavailable("current rtm.csv is missing or unreadable")

    with tempfile.TemporaryDirectory(prefix="mbse-rtm-") as temporary:
        base_root = Path(temporary)
        if not _materialise_tree(base, root, base_root):
            return unavailable(f"base revision {base!r} could not be read from git")
        try:
            write_rtm(base_root)
        except (LoadError, OSError, ValueError, KeyError, TypeError):
            return unavailable("could not build the base requirement traceability matrix")
        base_rows = _read_rtm(base_root / RTM_CSV)
        if base_rows is None:
            return unavailable("base rtm.csv is missing or unreadable")

        added, removed, changed = _compare_rtm(base_rows, head_rows)

        lines = [
            "# RTM Diff",
            "",
            f"Base: `{base}`",
            "",
            f"Head: `{head}`",
            "",
            "## Added requirements",
            "",
        ]
        if added:
            lines.extend(["| Req ID | Title |", "| --- | --- |"])
            lines.extend(
                f"| {_markdown_cell(requirement_id)} | "
                f"{_markdown_cell(head_rows[requirement_id].get('Title', ''))} |"
                for requirement_id in added
            )
        else:
            lines.append("None.")
        lines.extend(["", "## Removed requirements", ""])
        if removed:
            lines.extend(["| Req ID | Title |", "| --- | --- |"])
            lines.extend(
                f"| {_markdown_cell(requirement_id)} | "
                f"{_markdown_cell(base_rows[requirement_id].get('Title', ''))} |"
                for requirement_id in removed
            )
        else:
            lines.append("None.")
        lines.extend(["", "## Changed requirements", ""])
        if changed:
            lines.extend(["| Req ID | Changed fields |", "| --- | --- |"])
            lines.extend(
                f"| {_markdown_cell(requirement_id)} | {_markdown_cell(', '.join(fields))} |"
                for requirement_id, fields in changed.items()
            )
        else:
            lines.append("None.")
        lines.append("")

        try:
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            return path
    return path
