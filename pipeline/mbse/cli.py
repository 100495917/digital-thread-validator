"""Command line interface for the MBSE DevOps pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import trace as trace_module
from . import validate_model, validate_reqs, validate_schema
from .findings import Finding, sort_findings
from .loaders import LoadError, Requirement, load_model, load_requirements


def _not_implemented(command: str, phase: int) -> None:
    """Fail clearly for commands scheduled for a later implementation phase."""
    raise click.ClickException(f"{command} is implemented in Phase {phase} of PLAN.md")


def _display_path(path: Path) -> str:
    """Return a stable, cwd-relative path for user-facing output."""
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _artifact_counts(root: Path) -> tuple[int, int]:
    """Count requirement and model YAML files in deterministic order."""
    requirement_files = sorted((root / "requirements").glob("*.yaml"))
    model_files = sorted((root / "models").rglob("*.yaml"))
    return len(requirement_files), len(model_files)


def _load_error_finding(exc: LoadError) -> Finding:
    """Convert a YAML load failure into a normal finding for reporting."""
    message = getattr(exc, "message", None) or str(exc)
    return Finding(path=exc.path, rule="LOAD-001", severity="error", message=message)


def _requirement_findings(
    root: Path,
) -> tuple[list[Finding], list[Requirement] | None]:
    """Load requirements, run quality rules, and write the quality report."""
    try:
        requirements = load_requirements(root)
    except LoadError as exc:
        return [_load_error_finding(exc)], None
    findings = validate_reqs.validate_requirements(requirements)
    validate_reqs.write_quality_report(requirements, findings, root=root)
    return findings, requirements


def _model_findings(root: Path, requirement_ids: set[str] | None = None) -> list[Finding]:
    """Load the system model and run model rules."""
    if not (root / "models" / "system.yaml").is_file():
        return []
    try:
        model = load_model(root)
        if requirement_ids is None:
            requirement_ids = {requirement.id for requirement in load_requirements(root)}
        return validate_model.validate_model(model, root=root, requirement_ids=requirement_ids)
    except LoadError as exc:
        return [_load_error_finding(exc)]


def _emit_findings(findings: list[Finding]) -> tuple[int, int]:
    """Print findings in deterministic order and return error/warning counts."""
    ordered = sort_findings(findings)
    for finding in ordered:
        click.echo(f"{finding.path}: {finding.rule} {finding.severity}: {finding.message}")
    errors = sum(1 for finding in ordered if finding.severity == "error")
    warnings = sum(1 for finding in ordered if finding.severity == "warning")
    return errors, warnings


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
    """Validate requirements, the system model, or their JSON schemas."""
    root = Path(".")
    requirement_count, model_count = _artifact_counts(root)

    findings: list[Finding] = []
    requirements: list[Requirement] | None = None
    if mode in {"schema", "all"} and (root / "models" / "schema").is_dir():
        findings.extend(validate_schema.validate_schemas(root=root))
    if mode in {"reqs", "all"}:
        requirement_findings, requirements = _requirement_findings(root)
        findings.extend(requirement_findings)
    if mode == "model":
        findings.extend(_model_findings(root))
    elif mode == "all" and requirements is not None:
        findings.extend(_model_findings(root, {item.id for item in requirements}))

    errors, warnings = _emit_findings(findings)
    click.echo(
        f"validated {requirement_count} requirement file(s), "
        f"{model_count} model file(s), {errors} error(s), {warnings} warning(s)"
    )

    if errors:
        sys.exit(1)


@cli.group()
def trace() -> None:
    """Traceability checks and requirement traceability matrix generation."""


@trace.command("check")
def trace_check() -> None:
    """Check that every requirement has a complete traceability chain."""
    root = Path(".")
    try:
        links = trace_module.build_links(root=root)
        findings = trace_module.check_traceability(root=root)
        metrics = trace_module.compute_metrics(links, root=root)
    except LoadError as exc:
        _emit_findings([_load_error_finding(exc)])
        sys.exit(1)
        return

    errors, _ = _emit_findings(findings)
    click.echo(f"traceability coverage: {metrics['traceability_coverage']:.1f}%")
    click.echo(f"verification coverage: {metrics['verification_coverage']:.1f}%")

    if errors:
        sys.exit(1)


@trace.command("rtm")
def trace_rtm() -> None:
    """Generate the requirement traceability matrix."""
    root = Path(".")
    try:
        paths = trace_module.write_rtm(root=root)
    except LoadError as exc:
        _emit_findings([_load_error_finding(exc)])
        sys.exit(1)
        return

    for path in paths:
        click.echo(_display_path(Path(path)))


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
