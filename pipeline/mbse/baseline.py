"""Artifact baselines, snapshot comparison, and revision reports.

A baseline freezes the hashes of every tracked artifact together with the
current requirement traceability matrix (RTM) and the digital-thread snapshot.
Comparing two baselines yields a deterministic, human-reviewable summary of
what changed between two points in time.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .thread import load_thread, sha256_file

BASELINE_DIRECTORY = Path("baselines")
REPORT_DIRECTORY = Path("build") / "reports"
RTM_PATH = REPORT_DIRECTORY / "rtm.csv"
DIFF_JSON = REPORT_DIRECTORY / "baseline_diff.json"
DIFF_MARKDOWN = REPORT_DIRECTORY / "baseline_diff.md"

_ARTIFACT_PATTERNS = (
    "requirements/**/*",
    "models/**/*",
    "src/**/*.py",
    "tests/**/*.py",
)
_SKIP_PARTS = frozenset({"__pycache__"})


def _relative(path: Path, root: Path) -> str:
    """Return the root-relative POSIX path used as a baseline key."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def collect_artifacts(root: Path = Path(".")) -> dict[str, str]:
    """Hash every tracked requirements, models, source, and test artifact."""
    root = Path(root)
    artifacts: dict[str, str] = {}
    for pattern in _ARTIFACT_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            relative = _relative(path, root)
            if any(part in _SKIP_PARTS for part in Path(relative).parts[:-1]):
                continue
            artifacts[relative] = sha256_file(path)
    return {path: artifacts[path] for path in sorted(artifacts)}


def _rtm_rows(root: Path) -> list[dict[str, str]]:
    """Read the current RTM CSV as dictionaries, or ``[]`` when absent."""
    path = Path(root) / RTM_PATH
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []
    return sorted(rows, key=lambda row: str(row.get("Req ID", "")))


def create_baseline(version: str, root: Path = Path(".")) -> dict[str, Any]:
    """Build a baseline payload for ``version`` without writing it."""
    root = Path(root)
    # A baseline must embed an RTM; generate the current one when missing.
    if not (root / RTM_PATH).is_file():
        from .trace import write_rtm

        write_rtm(root)
    return {
        "version": str(version),
        "artifacts": collect_artifacts(root),
        "rtm": _rtm_rows(root),
        "thread": load_thread(root),
    }


def _baseline_path(version: str, root: Path) -> Path:
    return Path(root) / BASELINE_DIRECTORY / f"baseline-{version}.json"


def write_baseline(version: str, root: Path = Path(".")) -> Path:
    """Write ``baselines/baseline-<version>.json`` and return its path."""
    root = Path(root)
    path = _baseline_path(version, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(create_baseline(version, root), indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def load_baseline(version: str, root: Path = Path(".")) -> dict[str, Any]:
    """Load a previously written baseline, raising when it does not exist."""
    path = _baseline_path(version, Path(root))
    if not path.is_file():
        raise FileNotFoundError(f"Baseline '{version}' not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        # Malformed baseline JSON is part of the public ValueError contract.
        raise ValueError(  # noqa: TRY004
            f"Baseline '{version}' is not a JSON object: {path}"
        )
    return data


def _diff_mapping(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """Compare two string-keyed mappings, reporting added, removed, and changed keys."""
    previous_keys = set(previous)
    current_keys = set(current)
    return {
        "added": sorted(current_keys - previous_keys),
        "removed": sorted(previous_keys - current_keys),
        "changed": sorted(
            key for key in previous_keys & current_keys if previous[key] != current[key]
        ),
    }


def _rtm_index(baseline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index baseline RTM rows by requirement ID."""
    rows = baseline.get("rtm")
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return index
    for row in rows:
        if not isinstance(row, dict):
            continue
        requirement_id = str(row.get("Req ID", "")).strip()
        if requirement_id:
            index[requirement_id] = row
    return index


def _thread_index(baseline: dict[str, Any]) -> dict[str, str]:
    """Index baseline thread node hashes by node ID."""
    thread = baseline.get("thread")
    index: dict[str, str] = {}
    if not isinstance(thread, dict):
        return index
    nodes = thread.get("nodes")
    if not isinstance(nodes, list):
        return index
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "")).strip()
        if node_id:
            index[node_id] = str(node.get("sha256") or "")
    return index


def diff_baselines(old: str, new: str, root: Path = Path(".")) -> dict[str, Any]:
    """Compare two stored baselines and return a deterministic summary."""
    root = Path(root)
    previous = load_baseline(old, root)
    current = load_baseline(new, root)
    thread = _diff_mapping(_thread_index(previous), _thread_index(current))
    return {
        "old": str(old),
        "new": str(new),
        "artifacts": _diff_mapping(previous.get("artifacts") or {}, current.get("artifacts") or {}),
        "rtm": _diff_mapping(_rtm_index(previous), _rtm_index(current)),
        "thread": {
            "added": thread["added"],
            "removed": thread["removed"],
            "modified": thread["changed"],
        },
    }


def _table(title: str, change: str, values: list[str]) -> list[str]:
    """Render one Markdown table for a diff category."""
    lines = [f"### {title}", ""]
    if not values:
        lines.extend(["_None._", ""])
        return lines
    heading = "Path" if change == "artifacts" else ("Req ID" if change == "rtm" else "Node ID")
    lines.extend([f"| {heading} |", "| --- |"])
    lines.extend(f"| `{value}` |" for value in values)
    lines.append("")
    return lines


def _markdown(diff: dict[str, Any]) -> str:
    """Render the baseline diff as deterministic Markdown without timestamps."""
    lines = [f"# Baseline Diff: {diff['old']} -> {diff['new']}", ""]
    for section, title in (
        ("artifacts", "Artifacts"),
        ("rtm", "Requirements (RTM)"),
        ("thread", "Digital thread"),
    ):
        lines.extend([f"## {title}", ""])
        change_key = "modified" if section == "thread" else "changed"
        change_label = "Modified" if section == "thread" else "Changed"
        for label, key in (("Added", "added"), ("Removed", "removed"), (change_label, change_key)):
            lines.extend(_table(label, section, diff[section][key]))
    return "\n".join(lines).rstrip() + "\n"


def write_baseline_diff(old: str, new: str, root: Path = Path(".")) -> tuple[Path, Path]:
    """Write the JSON and Markdown baseline diff reports; return their paths."""
    root = Path(root)
    diff = diff_baselines(old, new, root)
    report_directory = root / REPORT_DIRECTORY
    report_directory.mkdir(parents=True, exist_ok=True)

    json_path = root / DIFF_JSON
    markdown_path = root / DIFF_MARKDOWN
    json_path.write_text(
        json.dumps(diff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(diff), encoding="utf-8")
    return json_path, markdown_path
