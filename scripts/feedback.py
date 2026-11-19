#!/usr/bin/env python3
"""Evaluate the REQ-013 latency feedback loop and print a JSON summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PIPELINE_ROOT = _REPO_ROOT / "pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

from mbse.feedback import (
    evaluate_feedback,
    open_or_update_issue,
    requirement_threshold_ms,
    write_feedback,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare an observed p95 latency with a requirement threshold.",
    )
    parser.add_argument(
        "--observed-p95-ms",
        type=float,
        required=True,
        help="Observed p95 latency of GET /status in milliseconds.",
    )
    parser.add_argument(
        "--requirement",
        default="REQ-013",
        help="Requirement ID whose threshold is evaluated (default: REQ-013).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Open or update a GitHub issue when the threshold is violated.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the feedback loop and return a process exit code."""
    args = _build_parser().parse_args(argv)

    threshold = requirement_threshold_ms(requirement_id=args.requirement)
    report = evaluate_feedback(
        args.observed_p95_ms,
        threshold,
        requirement_id=args.requirement,
    )
    path = write_feedback(report)

    summary = dict(report)
    summary["report"] = path.as_posix()
    if args.apply:
        summary["issue"] = open_or_update_issue(report)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if report["status"] == "violated" else 0


if __name__ == "__main__":
    raise SystemExit(main())
