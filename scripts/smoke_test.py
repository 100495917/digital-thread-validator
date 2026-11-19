#!/usr/bin/env python3
"""Run the Smart Thermostat API smoke checks and print a JSON summary."""

from __future__ import annotations

import argparse
import json
import os
import sys

from mbse.smoke import run_smoke

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TOKEN = "dev-token"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for the smoke runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("THERMOSTAT_API_TOKEN", DEFAULT_TOKEN),
        help="Bearer token for authenticated requests (default: THERMOSTAT_API_TOKEN or dev-token)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Execute the smoke suite, print the JSON report, and return an exit code."""
    args = _parse_args(argv)
    report = run_smoke(args.base_url, args.token)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
