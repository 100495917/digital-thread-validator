"""Digital-thread graph construction, serialization, and test-tag metadata.

The thread is a deterministic, file-hash based traceability graph.  Node IDs
mirror the identifiers used by the other ``mbse`` modules (requirement IDs,
model element IDs, root-relative POSIX paths, and ``file::Class::test`` test
IDs) so snapshots can be diffed across builds.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .loaders import (
    LoadError,
    SystemModel,
    _is_req_marker,
    _marker_ids,
    load_code_tags,
    load_model,
    load_requirements,
)

SCHEMA_VERSION = "1.0"

NODE_TYPES = (
    "Requirement",
    "ModelElement",
    "CodeModule",
    "Test",
    "TestResult",
    "Report",
    "Commit",
    "Release",
    "Deployment",
)

EDGE_TYPES = (
    "DERIVES_FROM",
    "SATISFIES",
    "ALLOCATED_TO",
    "IMPLEMENTS",
    "VERIFIES",
    "EXERCISES",
    "RESULT_OF",
    "CHANGED_IN",
    "INCLUDED_IN",
    "DEPLOYED_AS",
)

REPORT_PATHS = (
    "build/reports/rtm.csv",
    "build/reports/rtm.md",
    "build/reports/rtm.html",
    "build/reports/req_quality.json",
    "build/reports/junit.xml",
    "build/reports/coverage.xml",
    "build/reports/reqcov.json",
    "build/reports/security.json",
    "build/reports/security.sarif",
    "build/reports/sbom.json",
    "build/reports/thread_diff.md",
)

_SKIP_PARTS = frozenset({"__pycache__", ".git", ".venv", "venv", "build"})


@dataclass
class ThreadNode:
    """A single artifact or execution record in the digital thread."""

    id: str
    type: str
    path: str
    sha256: str
    version: str
    last_changed_commit: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class ThreadEdge:
    """A directed, typed relation between two thread nodes."""

    source: str
    target: str
    type: str


@dataclass
class ThreadGraph:
    """The complete digital-thread snapshot."""

    metadata: dict[str, Any]
    nodes: list[ThreadNode]
    edges: list[ThreadEdge]


# ---------------------------------------------------------------------------
# Filesystem and git helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``, or ``""`` when unreadable."""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _display_path(path: Path, root: Path) -> str:
    """Return a root-relative POSIX path for graph identifiers."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _python_files(root: Path, directory: Path) -> list[Path]:
    """Return sorted ``*.py`` files below ``directory``, skipping build noise."""
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(directory.rglob("*.py")):
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in _SKIP_PARTS for part in parts[:-1]):
            continue
        files.append(path)
    return files


def _git(root: Path, *arguments: str) -> str:
    """Run ``git`` with ``check=False`` and return stripped stdout or ``""``."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _git_last_changed(root: Path, path: str, cache: dict[str, str]) -> str:
    """Return the full commit SHA that last touched ``path`` (cached per build)."""
    if path in cache:
        return cache[path]
    sha = _git(root, "log", "-1", "--format=%H", "--", path)
    cache[path] = sha
    return sha


def _iso_utc(value: str) -> str:
    """Normalise a git ISO-8601 timestamp to an explicit UTC string."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _networkx_version() -> str:
    """Return the installed networkx version, or ``"unknown"``."""
    try:
        import networkx

        return str(networkx.__version__)
    except ImportError:  # pragma: no cover - optional dependency absent
        return "unknown"


def collect_metadata(root: Path = Path(".")) -> dict[str, Any]:
    """Collect commit, workflow, and tool metadata for one thread snapshot."""
    root = Path(root)
    env = os.environ
    commit_sha = env.get("GITHUB_SHA", "").strip() or _git(root, "rev-parse", "HEAD")
    if not commit_sha:
        commit_sha = "local"

    author = _git(root, "log", "-1", "--format=%an")
    if not author:
        author = env.get("GITHUB_ACTOR", "").strip()

    timestamp = _iso_utc(_git(root, "log", "-1", "--format=%cI"))
    branch = env.get("GITHUB_REF_NAME", "").strip()
    if not branch:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    workflow_run_id = env.get("GITHUB_RUN_ID", "").strip()

    return {
        "commit_sha": commit_sha,
        "author": author,
        "timestamp": timestamp,
        "workflow_run_id": workflow_run_id,
        "branch": branch,
        "tool_versions": {
            "python": platform.python_version(),
            "networkx": _networkx_version(),
            "mbse": str(__version__),
        },
    }


# ---------------------------------------------------------------------------
# AST test discovery
# ---------------------------------------------------------------------------


def _decorated_requirement_ids(node: ast.AST) -> tuple[str, ...]:
    """Return sorted unique requirement IDs from all ``mark.req`` decorators."""
    ids: set[str] = set()
    for decorator in getattr(node, "decorator_list", ()):
        if _is_req_marker(decorator):
            ids.update(_marker_ids(decorator))
    return tuple(sorted(ids))


def _walk_tests(
    node: ast.AST,
    prefix: tuple[str, ...],
    found: dict[str, tuple[str, ...]],
    *,
    in_function: bool = False,
) -> None:
    """Recursively collect requirement-tagged module functions and class methods."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            _walk_tests(child, prefix + (child.name,), found, in_function=in_function)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not in_function:
                ids = _decorated_requirement_ids(child)
                if ids:
                    found["::".join(prefix + (child.name,))] = ids
            _walk_tests(child, prefix + (child.name,), found, in_function=True)
        elif isinstance(child, (ast.If, ast.Try)) and not in_function:
            _walk_tests(child, prefix, found)


def test_ids(root: Path = Path(".")) -> dict[str, tuple[str, ...]]:
    """Map ``tests/...::Class::test`` IDs to their requirement markers."""
    root = Path(root)
    tests_root = root / "tests"
    found: dict[str, tuple[str, ...]] = {}
    for path in _python_files(root, tests_root):
        display = _display_path(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(text, filename=display)
        except SyntaxError:
            continue
        relative: dict[str, tuple[str, ...]] = {}
        _walk_tests(tree, (), relative)
        for name, ids in relative.items():
            found[f"{display}::{name}"] = ids
    return dict(sorted(found.items()))


# ---------------------------------------------------------------------------
# Result loading
# ---------------------------------------------------------------------------


def _load_req_results(root: Path) -> dict[str, dict[str, Any]]:
    """Load ``req_results.json`` into a test-ID keyed result mapping."""
    path = root / "build" / "reports" / "req_results.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    results: dict[str, dict[str, Any]] = {}
    for entries in data.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            test_id = entry.get("test")
            if not isinstance(test_id, str) or not test_id:
                continue
            attributes = results.setdefault(test_id, {})
            if "outcome" in entry:
                attributes["outcome"] = str(entry["outcome"])
            if "duration" in entry:
                attributes["duration"] = entry["duration"]
    return results


def _junit_outcome(case: Any) -> str:
    """Derive a pytest-style outcome from a JUnit ``testcase`` element."""
    for child in case:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in {"failure", "error"}:
            return "failed" if tag == "failure" else "error"
        if tag == "skipped":
            return "skipped"
    return "passed"


def _junit_test_id(classname: str, name: str, known: set[str]) -> str:
    """Convert a JUnit classname/name pair to a known test node ID."""
    base_name = name.split("[", 1)[0]
    module = classname.replace(".", "/") + ".py"
    plain = f"{module}::{base_name}"
    if plain in known or not classname:
        return plain
    parent, _, klass = classname.rpartition(".")
    if parent and klass:
        candidate = f"{parent.replace('.', '/')}.py::{klass}::{base_name}"
        if candidate in known:
            return candidate
    return plain


def _load_junit(root: Path, known: set[str]) -> dict[str, dict[str, Any]]:
    """Load ``junit.xml`` results, resolving cases against known test IDs."""
    from xml.etree import ElementTree

    path = root / "build" / "reports" / "junit.xml"
    try:
        tree = ElementTree.parse(path)
    except (OSError, ElementTree.ParseError):
        return {}
    results: dict[str, dict[str, Any]] = {}
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        if not name:
            continue
        test_id = _junit_test_id(classname, name, known)
        attributes: dict[str, Any] = {"outcome": _junit_outcome(case)}
        time_value = case.get("time")
        if time_value is not None:
            try:
                attributes["duration"] = float(time_value)
            except ValueError:
                pass
        results.setdefault(test_id, attributes)
    return results


def _merge_results(root: Path, known: set[str]) -> dict[str, dict[str, Any]]:
    """Merge ``req_results.json`` with the JUnit fallback for known tests."""
    merged: dict[str, dict[str, Any]] = {}
    for test_id, attributes in _load_req_results(root).items():
        if test_id in known:
            merged[test_id] = dict(attributes)
    for test_id, attributes in _load_junit(root, known).items():
        if test_id in known:
            merged.setdefault(test_id, dict(attributes))
    return merged


def _result_for(test_id: str, results: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Return the exact result or the first parametrized variant for ``test_id``."""
    if test_id in results:
        return results[test_id]
    prefix = f"{test_id}["
    for candidate in sorted(results):
        if candidate.startswith(prefix):
            return results[candidate]
    return None


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _safe_requirements(root: Path) -> list[Any]:
    try:
        return load_requirements(root)
    except LoadError:
        return []


def _safe_model(root: Path) -> SystemModel | None:
    try:
        return load_model(root)
    except LoadError:
        return None


def _safe_code_tags(root: Path) -> dict[str, tuple[str, ...]]:
    try:
        return load_code_tags(root)
    except LoadError:
        return {}


def _json_safe(value: Any) -> Any:
    """Convert common Python containers into deterministic JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value)]
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_graph(root: Path = Path(".")) -> ThreadGraph:
    """Build the complete deterministic digital-thread graph for a project."""
    root = Path(root)
    metadata = collect_metadata(root)
    git_cache: dict[str, str] = {}
    nodes: list[ThreadNode] = []
    edges: set[tuple[str, str, str]] = set()

    def node(
        node_id: str,
        node_type: str,
        path: str,
        version: str,
        attributes: dict[str, Any],
        *,
        sha: str | None = None,
    ) -> ThreadNode:
        file_sha = sha256_file(root / path) if sha is None and path else (sha or "")
        return ThreadNode(
            id=node_id,
            type=node_type,
            path=path,
            sha256=file_sha,
            version=str(version or "1.0"),
            last_changed_commit=_git_last_changed(root, path, git_cache) if path else "",
            attributes=_json_safe(attributes),
        )

    requirements = _safe_requirements(root)
    requirement_ids = {requirement.id for requirement in requirements}
    for requirement in requirements:
        version = str(requirement.raw.get("version", "1.0") or "1.0")
        nodes.append(
            node(
                requirement.id,
                "Requirement",
                requirement.path,
                version,
                {
                    "title": requirement.title,
                    "type": requirement.type,
                    "status": requirement.status,
                    "priority": requirement.priority,
                    "verification": requirement.verification,
                    "parent": requirement.parent,
                },
            )
        )
        if requirement.parent and requirement.parent in requirement_ids:
            edges.add((requirement.id, requirement.parent, "DERIVES_FROM"))

    model = _safe_model(root)
    model_sha = ""
    release_version = ""
    if model is not None:
        model_sha = sha256_file(root / model.path)
        release_version = str(model.version or "1.0")
        for element in model.elements:
            nodes.append(
                node(
                    element.id,
                    "ModelElement",
                    model.path,
                    release_version,
                    {
                        "kind": element.kind,
                        "name": element.name,
                        "satisfies": list(element.satisfies),
                        "allocated_to": element.allocated_to,
                    },
                    sha=model_sha,
                )
            )
            for requirement_id in element.satisfies:
                if requirement_id in requirement_ids:
                    edges.add((element.id, requirement_id, "SATISFIES"))

    code_tags = _safe_code_tags(root)
    code_modules: dict[str, list[str]] = {}
    for path in _python_files(root, root / "src"):
        display = _display_path(path, root)
        implements = sorted(
            requirement_id for requirement_id, paths in code_tags.items() if display in paths
        )
        code_modules[display] = implements
        nodes.append(
            node(
                display,
                "CodeModule",
                display,
                "1.0",
                {"implements": implements},
            )
        )
        for requirement_id in implements:
            if requirement_id in requirement_ids:
                edges.add((display, requirement_id, "IMPLEMENTS"))

    if model is not None:
        for element in model.elements:
            allocated = element.allocated_to
            if allocated and allocated in code_modules:
                edges.add((element.id, allocated, "ALLOCATED_TO"))

    tags = test_ids(root)
    known_tests = set(tags)
    results = _merge_results(root, known_tests)

    for test_id, requirement_tag_ids in sorted(tags.items()):
        test_path = test_id.split("::", 1)[0]
        attributes: dict[str, Any] = {"requirements": list(requirement_tag_ids)}
        result = _result_for(test_id, results)
        if result is not None:
            attributes.update(result)
        nodes.append(
            node(
                test_id,
                "Test",
                test_path,
                "1.0",
                attributes,
            )
        )
        for requirement_id in requirement_tag_ids:
            if requirement_id in requirement_ids:
                edges.add((test_id, requirement_id, "VERIFIES"))
        for requirement_id in requirement_tag_ids:
            for code_path, implements in sorted(code_modules.items()):
                if requirement_id in implements:
                    edges.add((test_id, code_path, "EXERCISES"))
        if result is not None:
            result_id = f"RESULT:{test_id}"
            nodes.append(
                node(
                    result_id,
                    "TestResult",
                    test_path,
                    "1.0",
                    dict(result),
                )
            )
            edges.add((result_id, test_id, "RESULT_OF"))

    for report_path in REPORT_PATHS:
        if (root / report_path).is_file():
            nodes.append(
                node(
                    report_path,
                    "Report",
                    report_path,
                    "1.0",
                    {},
                )
            )

    commit_sha = str(metadata["commit_sha"])
    commit_message = _git(root, "log", "-1", "--format=%s")
    short_sha = commit_sha[:7] if commit_sha != "local" else "local"
    nodes.append(
        ThreadNode(
            id=commit_sha,
            type="Commit",
            path="",
            sha256="",
            version="1.0",
            last_changed_commit=commit_sha,
            attributes=_json_safe(
                {
                    "author": metadata["author"],
                    "message": commit_message,
                    "short_sha": short_sha,
                }
            ),
        )
    )

    deployment_environment = os.environ.get("DEPLOY_ENVIRONMENT", "").strip()
    if deployment_environment:
        image_tag = os.environ.get("DEPLOY_IMAGE_TAG", "").strip() or commit_sha
        deployment_sha = (
            hashlib.sha256(commit_sha.encode("utf-8")).hexdigest() if commit_sha != "local" else ""
        )
        commit_identifier = commit_sha if commit_sha != "local" else "local"
        deployment_id = f"deployment-{deployment_environment}-{commit_identifier}"
        nodes.append(
            ThreadNode(
                id=deployment_id,
                type="Deployment",
                path="",
                sha256=deployment_sha,
                version=deployment_environment,
                last_changed_commit=commit_sha if commit_sha != "local" else "",
                attributes=_json_safe(
                    {
                        "environment": deployment_environment,
                        "image_tag": image_tag,
                        "commit_sha": commit_sha,
                    }
                ),
            )
        )
        edges.add((commit_sha, deployment_id, "DEPLOYED_AS"))
        metadata["deployment"] = {
            "environment": deployment_environment,
            "image_tag": image_tag,
            "commit_sha": commit_sha,
        }

    if model is not None:
        release_id = f"release-{release_version}"
        nodes.append(
            node(
                release_id,
                "Release",
                model.path,
                release_version,
                {"version": release_version},
                sha=model_sha,
            )
        )
        edges.add((commit_sha, release_id, "INCLUDED_IN"))

    for thread_node in nodes:
        if (
            thread_node.type in {"Requirement", "ModelElement", "CodeModule", "Test"}
            and thread_node.last_changed_commit
        ):
            edges.add((thread_node.id, commit_sha, "CHANGED_IN"))

    graph = ThreadGraph(metadata=metadata, nodes=nodes, edges=[ThreadEdge(*edge) for edge in edges])
    return _sorted_graph(graph)


def _sorted_graph(graph: ThreadGraph) -> ThreadGraph:
    """Return a copy with deterministic node and edge ordering."""
    nodes = sorted(graph.nodes, key=lambda item: (item.type, item.id))
    edges = sorted(graph.edges, key=lambda item: (item.source, item.target, item.type))
    return ThreadGraph(metadata=dict(graph.metadata), nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Serialization and persistence
# ---------------------------------------------------------------------------


def graph_to_dict(graph: ThreadGraph) -> dict:
    """Serialize a graph deterministically, with timestamps only in metadata."""
    nodes = [
        {
            "id": item.id,
            "type": item.type,
            "path": item.path,
            "sha256": item.sha256,
            "version": item.version,
            "last_changed_commit": item.last_changed_commit,
            "attributes": _json_safe(item.attributes),
        }
        for item in sorted(graph.nodes, key=lambda value: (value.type, value.id))
    ]
    edges = [
        {"source": item.source, "target": item.target, "type": item.type}
        for item in sorted(graph.edges, key=lambda value: (value.source, value.target, value.type))
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": _json_safe(graph.metadata),
        "nodes": nodes,
        "edges": edges,
    }


def graph_from_dict(data: dict) -> ThreadGraph:
    """Deserialize a graph produced by :func:`graph_to_dict`."""
    if not isinstance(data, dict):
        return ThreadGraph(metadata={}, nodes=[], edges=[])
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    nodes: list[ThreadNode] = []
    for item in data.get("nodes") or []:
        if not isinstance(item, dict):
            continue
        attributes = item.get("attributes")
        nodes.append(
            ThreadNode(
                id=str(item.get("id", "")),
                type=str(item.get("type", "")),
                path=str(item.get("path", "")),
                sha256=str(item.get("sha256", "")),
                version=str(item.get("version", "")),
                last_changed_commit=str(item.get("last_changed_commit", "")),
                attributes=dict(attributes) if isinstance(attributes, dict) else {},
            )
        )
    edges: list[ThreadEdge] = []
    for item in data.get("edges") or []:
        if not isinstance(item, dict):
            continue
        edges.append(
            ThreadEdge(
                source=str(item.get("source", "")),
                target=str(item.get("target", "")),
                type=str(item.get("type", "")),
            )
        )
    return _sorted_graph(ThreadGraph(metadata=dict(metadata), nodes=nodes, edges=edges))


def write_thread(graph: ThreadGraph, root: Path = Path(".")) -> Path:
    """Write ``digital_thread/thread.json`` and return the written path."""
    path = Path(root) / "digital_thread" / "thread.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph_to_dict(graph), indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def load_thread(root: Path = Path(".")) -> dict:
    """Load the raw thread dictionary, returning ``{}`` when absent or invalid."""
    path = Path(root) / "digital_thread" / "thread.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_graph(root: Path = Path(".")) -> ThreadGraph:
    """Load the persisted thread as a :class:`ThreadGraph`."""
    return graph_from_dict(load_thread(root))
