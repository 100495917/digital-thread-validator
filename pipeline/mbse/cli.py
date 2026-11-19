"""Command line interface for the MBSE DevOps pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml


def _not_implemented(command: str, phase: int) -> None:
    """Fail clearly for commands scheduled for a later implementation phase."""
    raise click.ClickException(f"{command} is implemented in Phase {phase} of PLAN.md")


def _display_path(path: Path) -> str:
    """Return a stable, cwd-relative path for user-facing output."""
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _yaml_files() -> tuple[list[Path], list[Path]]:
    """Discover requirement and model YAML files in deterministic order."""
    requirement_files = sorted(Path("requirements").glob("*.yaml"))
    model_files = sorted(Path("models").rglob("*.yaml"))
    return requirement_files, model_files


def _parse_yaml_files(paths: list[Path]) -> tuple[int, list[tuple[str, str]]]:
    """Parse YAML files, returning the number read and ``(path, error)`` pairs."""
    errors: list[tuple[str, str]] = []
    for path in paths:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            message = " ".join(str(exc).split())
            errors.append((_display_path(path), message))
    return len(paths), errors


@click.group()
def cli() -> None:
    """Validate and trace MBSE artifacts for the Smart Thermostat Controller."""


@cli.command()
@click.argument(
    "mode",
    required=False,
    default="all",
    type=click.Choice(["schema", "reqs", "model", "all"], case_sensitive=False),
)
def validate(mode: str) -> None:
    """Parse requirements and model YAML artifacts.

    Phase 1 performs YAML parsing only; schema and rule checks arrive in Phase 3.
    """
    _ = mode  # Every mode currently performs the same Phase 1 parse check.
    requirement_files, model_files = _yaml_files()
    requirement_count, requirement_errors = _parse_yaml_files(requirement_files)
    model_count, model_errors = _parse_yaml_files(model_files)
    errors = sorted(requirement_errors + model_errors)

    for path, message in errors:
        click.echo(f"{path}: {message}")
    click.echo(
        f"validated {requirement_count} requirement file(s), "
        f"{model_count} model file(s), {len(errors)} error(s)"
    )

    if errors:
        sys.exit(1)


@cli.group()
def trace() -> None:
    """Traceability checks and requirement traceability matrix generation."""


@trace.command("check")
def trace_check() -> None:
    """Check that every requirement has a complete traceability chain."""
    _not_implemented("trace check", 4)


@trace.command("rtm")
def trace_rtm() -> None:
    """Generate the requirement traceability matrix."""
    _not_implemented("trace rtm", 4)


@cli.group()
def thread() -> None:
    """Build, update, and query the digital thread."""


@thread.command("build")
def thread_build() -> None:
    """Build the digital thread graph."""
    _not_implemented("thread build", 8)


@thread.command("update")
def thread_update() -> None:
    """Update the digital thread and record its diff."""
    _not_implemented("thread update", 8)


@thread.command("query")
def thread_query() -> None:
    """Query the digital thread."""
    _not_implemented("thread query", 8)


@cli.command()
@click.option("--base", "base_ref", metavar="REF", help="Base git reference.")
@click.option("--head", "head_ref", metavar="REF", help="Head git reference.")
def impact(base_ref: str | None, head_ref: str | None) -> None:
    """Analyse the impact of changes between two references."""
    _ = (base_ref, head_ref)
    _not_implemented("impact", 9)


@cli.command()
@click.argument(
    "target",
    required=False,
    default="all",
    type=click.Choice(
        ["diagrams", "docs", "openapi", "test-stubs", "sbom", "all"],
        case_sensitive=False,
    ),
)
def generate(target: str) -> None:
    """Generate diagrams, docs, OpenAPI, test stubs, and the SBOM."""
    _ = target
    _not_implemented("generate", 5)


@cli.command()
def report() -> None:
    """Produce the aggregate pipeline report."""
    _not_implemented("report", 10)


@cli.command()
def reqcov() -> None:
    """Compute and gate requirements coverage."""
    _not_implemented("reqcov", 6)


@cli.command()
def metrics() -> None:
    """Compute pipeline and delivery metrics."""
    _not_implemented("metrics", 13)


@cli.group()
def baseline() -> None:
    """Manage and compare release baselines."""


@baseline.command("diff")
@click.argument("old", required=False)
@click.argument("new", required=False)
def baseline_diff(old: str | None, new: str | None) -> None:
    """Show requirement, model, and test changes between two baselines."""
    _ = (old, new)
    _not_implemented("baseline diff", 11)


def main() -> None:
    """Console script entrypoint."""
    cli()


if __name__ == "__main__":
    main()
