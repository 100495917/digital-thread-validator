"""DORA and pipeline metrics computed from git history and build reports.

The collector is deliberately read-only and tolerant: a missing git
repository or report degrades the affected section to zeros instead of
raising.  Output contains no timestamps so repeated runs over unchanged
inputs produce byte-identical JSON.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

REPORT_DIRECTORY = Path("build") / "reports"
METRICS_PATH = REPORT_DIRECTORY / "metrics.json"

_DEPLOYMENT_WINDOW_DAYS = 30
_TAG_PATTERN = "refs/tags/v*"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _git(root: Path, *arguments: str) -> str | None:
    """Run git in ``root`` and return stdout, or ``None`` on any failure."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp, normalising it to UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_json_list(path: Path) -> list[Any]:
    """Read a JSON list, returning ``[]`` for missing or malformed files."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return raw if isinstance(raw, list) else []


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _tags(root: Path) -> list[tuple[str, datetime]]:
    """Return ``v*`` tags sorted by creation date, then name.

    Lightweight tags report the tagged commit's date, annotated tags report
    their tagger date, which is what ``creatordate`` exposes.
    """
    output = _git(
        root,
        "for-each-ref",
        "--sort=refname",
        "--sort=creatordate",
        "--format=%(refname:short)%09%(creatordate:iso-strict)",
        _TAG_PATTERN,
    )
    if output is None:
        return []
    tags: list[tuple[str, datetime]] = []
    for line in output.splitlines():
        name, separator, raw_date = line.partition("\t")
        if not separator or not name.startswith("v"):
            continue
        created = _parse_timestamp(raw_date.strip())
        if created is not None:
            tags.append((name, created))
    return tags


def _commit_dates(root: Path, revision_range: str) -> list[datetime]:
    """Return committer timestamps for the commits in ``revision_range``."""
    output = _git(root, "log", "--format=%cI", revision_range)
    if output is None:
        return []
    dates: list[datetime] = []
    for line in output.splitlines():
        parsed = _parse_timestamp(line.strip())
        if parsed is not None:
            dates.append(parsed)
    return dates


def _median_hours(dates: list[datetime], reference: datetime | None) -> list[float]:
    """Return hours from each commit date to ``reference`` (default: that date)."""
    if reference is None:
        return []
    hours = [max((reference - date).total_seconds() / 3600.0, 0.0) for date in dates]
    return hours


def _deployment_frequency(tags: list[tuple[str, datetime]], now: datetime) -> dict[str, Any]:
    cutoff = now - timedelta(days=_DEPLOYMENT_WINDOW_DAYS)
    releases = sum(1 for _, created in tags if created >= cutoff)
    per_week = releases * 7.0 / _DEPLOYMENT_WINDOW_DAYS
    return {
        "releases": releases,
        "window_days": _DEPLOYMENT_WINDOW_DAYS,
        "per_week": round(per_week, 2),
    }


def _lead_time(tags: list[tuple[str, datetime]], root: Path, now: datetime) -> dict[str, Any]:
    if tags:
        latest_name, latest_created = tags[-1]
        if len(tags) >= 2:
            revision_range = f"{tags[-2][0]}..{latest_name}"
        else:
            revision_range = latest_name
        dates = _commit_dates(root, revision_range)
        samples = _median_hours(dates, latest_created)
    else:
        cutoff = (now - timedelta(days=_DEPLOYMENT_WINDOW_DAYS)).isoformat()
        output = _git(root, "log", f"--since={cutoff}", "--format=%cI", "HEAD")
        dates = []
        if output is not None:
            for line in output.splitlines():
                parsed = _parse_timestamp(line.strip())
                if parsed is not None:
                    dates.append(parsed)
        samples = _median_hours(dates, now)
    median = round(statistics.median(samples), 2) if samples else 0.0
    return {"median": median, "samples": len(samples)}


def _change_failure_rate(root: Path) -> dict[str, Any]:
    runs = _read_json_list(root / REPORT_DIRECTORY / "pipeline_runs.json")
    statuses = [
        entry.get("status")
        for entry in runs
        if isinstance(entry, dict) and entry.get("status") in {"pass", "fail"}
    ]
    total = len(statuses)
    failed = sum(1 for status in statuses if status == "fail")
    rate = round(failed / total, 3) if total else 0.0
    return {"failed": failed, "total": total, "rate": rate}


def _mean_time_to_restore(root: Path) -> dict[str, Any]:
    incidents = _read_json_list(root / REPORT_DIRECTORY / "incidents.json")
    restores: list[float] = []
    for entry in incidents:
        if not isinstance(entry, dict):
            continue
        opened = _parse_timestamp(entry.get("opened"))
        restored = _parse_timestamp(entry.get("restored"))
        if opened is None or restored is None:
            continue
        restores.append(max((restored - opened).total_seconds() / 3600.0, 0.0))
    mean = round(statistics.mean(restores), 2) if restores else 0.0
    return {"mean": mean, "incidents": len(restores)}


def _junit_pipeline(root: Path) -> dict[str, Any]:
    path = root / REPORT_DIRECTORY / "junit.xml"
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        suite_root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        suite_root = None
    if suite_root is not None:
        suites = (
            [suite_root] if suite_root.tag == "testsuite" else list(suite_root.iter("testsuite"))
        )
        for suite in suites:
            for key in totals:
                try:
                    totals[key] += int(suite.get(key, "0"))
                except (TypeError, ValueError):
                    continue
    failed = totals["failures"] + totals["errors"]
    total = totals["tests"]
    passed = max(total - failed - totals["skipped"], 0)

    flaky_entries = _read_json_list(root / REPORT_DIRECTORY / "flaky.json")
    return {
        "tests_total": total,
        "tests_passed": passed,
        "tests_failed": failed,
        "flaky_tests": len(flaky_entries),
        "coverage_percent": _coverage_percent(root / REPORT_DIRECTORY / "coverage.xml"),
    }


def _coverage_percent(path: Path) -> float:
    """Return line coverage percent from a Cobertura ``coverage.xml``."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return 0.0
    line_rate = _number(root.get("line-rate"), default=-1.0)
    if line_rate >= 0.0:
        return round(line_rate * 100.0, 1)
    valid = _number(root.get("lines-valid"))
    covered = _number(root.get("lines-covered"))
    if valid:
        return round(100.0 * covered / valid, 1)
    return 0.0


def _stages(root: Path) -> list[dict[str, Any]]:
    timings = _read_json_list(root / REPORT_DIRECTORY / "timings.json")
    stages: list[dict[str, Any]] = []
    for entry in timings:
        if not isinstance(entry, dict):
            continue
        stages.append(
            {
                "name": str(entry.get("name", "")),
                "duration_seconds": round(_number(entry.get("duration_seconds")), 3),
            }
        )
    return stages


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_metrics(root: Path = Path(".")) -> dict[str, Any]:
    """Collect DORA and pipeline metrics rooted at ``root``."""
    root = Path(root)
    now = datetime.now(UTC)
    has_git = _git(root, "rev-parse", "--git-dir") is not None
    tags = _tags(root) if has_git else []
    lead_time = _lead_time(tags, root, now) if has_git else {"median": 0.0, "samples": 0}
    return {
        "deployment_frequency": _deployment_frequency(tags, now),
        "lead_time_hours": lead_time,
        "change_failure_rate": _change_failure_rate(root),
        "mean_time_to_restore_hours": _mean_time_to_restore(root),
        "pipeline": _junit_pipeline(root),
        "stages": _stages(root),
        "source": "git",
        "status": "ok" if has_git else "partial",
    }


def write_metrics(root: Path = Path(".")) -> Path:
    """Write deterministic metrics JSON to ``build/reports/metrics.json``."""
    root = Path(root)
    path = root / METRICS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(collect_metrics(root), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path
