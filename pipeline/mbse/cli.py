"""Command line interface for the MBSE DevOps pipeline."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import click

from . import thread as thread_module
from . import thread_diff as thread_diff_module
from . import thread_query as thread_query_module
from . import thread_visual as thread_visual_module
from . import trace as trace_module
from . import validate_model, validate_reqs, validate_schema
from .findings import Finding, sort_findings
from .generate import (
    generate_all,
    generate_diagrams,
    generate_docs,
    generate_openapi,
    generate_sbom,
    generate_test_stubs,
)
from .loaders import LoadError, Requirement, load_model, load_requirements
from .reqcov import compute_requirements_coverage, write_reqcov_report
from .security import gate_failed as security_gate_failed
from .security import run_all as run_security_scan
from .security import write_sarif as write_security_sarif
from .security import write_security_report


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


def _node_dict(node: object) -> dict:
    """Return a JSON-safe dictionary for a thread node."""
    return dataclasses.asdict(node)  # type: ignore[arg-type]


def _echo_json(payload: object) -> None:
    """Print a deterministic JSON document."""
    click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _echo_node(node: object) -> None:
    """Print one query result line."""
    line = f"{node.type} {node.id}"  # type: ignore[attr-defined]
    if node.type == "TestResult":  # type: ignore[attr-defined]
        outcome = node.attributes.get("outcome", "unknown")  # type: ignore[attr-defined]
        line += f" {outcome}"
    click.echo(line)


def _why_failed_payload(payload: dict) -> dict:
    """Convert a why-failed result into JSON-safe data."""
    test = payload.get("test")
    result = payload.get("result")
    return {
        "test": _node_dict(test) if test is not None else None,
        "result": _node_dict(result) if result is not None else None,
        "requirements": list(payload.get("requirements", [])),
        "code": list(payload.get("code", [])),
        "outcome": payload.get("outcome"),
    }


@thread.command("build")
def thread_build() -> None:
    """Build the digital thread graph."""
    root = Path(".")
    graph = thread_module.build_graph(root=root)
    thread_path = thread_module.write_thread(graph, root=root)
    visual_paths = thread_visual_module.generate_visualizations(graph, root=root)

    click.echo(f"nodes: {len(graph.nodes)}, edges: {len(graph.edges)}")
    for path in [thread_path, *_as_paths(visual_paths)]:
        click.echo(_display_path(Path(path)))


@thread.command("update")
def thread_update() -> None:
    """Update the digital thread and record its diff."""
    root = Path(".")
    result = thread_diff_module.update_thread(root=root)
    graph = thread_module.load_graph(root=root)
    visual_paths = thread_visual_module.generate_visualizations(graph, root=root)
    diff = result.get("diff", {})
    stale = result.get("stale", [])

    click.echo(f"nodes: {len(graph.nodes)}, edges: {len(graph.edges)}")
    click.echo(
        f"added: {len(diff.get('added_nodes', []))}, "
        f"removed: {len(diff.get('removed_nodes', []))}, "
        f"modified: {len(diff.get('modified_nodes', []))}, "
        f"stale: {len(stale)}"
    )
    for key in ("thread", "snapshot", "diff_report"):
        path = result.get(key)
        if path:
            click.echo(_display_path(Path(path)))
    for path in _as_paths(visual_paths):
        click.echo(_display_path(Path(path)))


@thread.command("query")
@click.option("--upstream", "upstream_id", metavar="ID", help="Show upstream nodes.")
@click.option("--downstream", "downstream_id", metavar="ID", help="Show downstream nodes.")
@click.option("--why-failed", "why_failed_id", metavar="ID", help="Explain a test result.")
@click.option("--history", "history_id", metavar="ID", help="Show git history for a node.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def thread_query(
    upstream_id: str | None,
    downstream_id: str | None,
    why_failed_id: str | None,
    history_id: str | None,
    as_json: bool,
) -> None:
    """Query the digital thread."""
    selected = [
        (name, value)
        for name, value in (
            ("upstream", upstream_id),
            ("downstream", downstream_id),
            ("why_failed", why_failed_id),
            ("history", history_id),
        )
        if value is not None
    ]
    if len(selected) != 1:
        raise click.UsageError(
            "exactly one of --upstream, --downstream, --why-failed, --history is required"
        )

    mode, identifier = selected[0]
    root = Path(".")
    graph = thread_module.load_graph(root=root)
    node = thread_query_module.resolve_node(graph, identifier)
    if node is None:
        raise click.ClickException(f"unknown node: {identifier}")

    if mode == "upstream":
        nodes = thread_query_module.upstream(graph, identifier)
        if as_json:
            _echo_json([_node_dict(item) for item in nodes])
        else:
            for item in nodes:
                _echo_node(item)
        return

    if mode == "downstream":
        nodes = thread_query_module.downstream(graph, identifier)
        if as_json:
            _echo_json([_node_dict(item) for item in nodes])
        else:
            for item in nodes:
                _echo_node(item)
        return

    if mode == "why_failed":
        payload = thread_query_module.why_failed(graph, identifier)
        if as_json:
            _echo_json(_why_failed_payload(payload))
        else:
            click.echo(f"outcome: {payload.get('outcome') or 'none'}")
            requirements = ", ".join(payload.get("requirements", [])) or "none"
            code = ", ".join(payload.get("code", [])) or "none"
            click.echo(f"requirements: {requirements}")
            click.echo(f"code: {code}")
        return

    entries = thread_query_module.history(root, identifier)
    if as_json:
        _echo_json(entries)
    else:
        for entry in entries:
            click.echo(f"{entry.get('commit', '')} {entry.get('subject', '')}")


@cli.command()
@click.option("--base", "base_ref", metavar="REF", help="Base git reference.")
@click.option("--head", "head_ref", metavar="REF", help="Head git reference.")
def impact(base_ref: str | None, head_ref: str | None) -> None:
    """Analyse the impact of changes between two references."""
    _ = (base_ref, head_ref)
    _not_implemented("impact", 9)


_GENERATE_TARGETS = {
    "diagrams": lambda root: generate_diagrams(root=root),
    "docs": lambda root: generate_docs(root=root),
    "openapi": lambda root: generate_openapi(root=root),
    "test-stubs": lambda root: generate_test_stubs(root=root),
    "sbom": lambda root: generate_sbom(root=root),
    "all": lambda root: generate_all(root=root),
}


def _as_paths(result: object) -> list[Path]:
    """Normalise a generator return value to a list of paths."""
    if isinstance(result, Path):
        return [result]
    return [Path(path) for path in result]  # type: ignore[union-attr]


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
    root = Path(".")
    function = _GENERATE_TARGETS[target]
    try:
        written = function(root)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    for path in _as_paths(written):
        click.echo(_display_path(path))


@cli.command()
def report() -> None:
    """Produce the aggregate pipeline report."""
    _not_implemented("report", 10)


@cli.command()
@click.option(
    "--threshold",
    type=click.FloatRange(min=0.0, max=100.0),
    default=90.0,
    show_default=True,
    help="Minimum requirements coverage percentage.",
)
@click.option(
    "--results",
    "results_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to the req_results.json produced by the test run.",
)
def reqcov(threshold: float, results_path: Path | None) -> None:
    """Compute and gate requirements coverage."""
    root = Path(".")
    coverage = compute_requirements_coverage(root=root, results_path=results_path)
    summary = coverage.get("summary", coverage)
    summary["threshold"] = threshold
    report = write_reqcov_report(coverage, root=root)

    total = int(summary.get("total", 0))
    covered = int(summary.get("covered", 0))
    percentage = float(summary.get("coverage", 0.0))

    click.echo(f"requirements coverage: {percentage:.1f}% ({covered}/{total})")
    click.echo(_display_path(Path(report)))

    if percentage < threshold:
        sys.exit(1)


@cli.command()
def security() -> None:
    """Run the security scanners and gate their findings."""
    root = Path(".")
    results = run_security_scan(root=root)
    report = write_security_report(results, root=root)
    sarif = write_security_sarif(results, root=root)

    for result in results:
        line = f"{result.tool}: {result.status}"
        if result.findings:
            line += f" ({len(result.findings)} finding(s))"
        if result.note:
            line += f" - {result.note}"
        click.echo(line)

    click.echo(_display_path(Path(report)))
    click.echo(_display_path(Path(sarif)))

    total = sum(len(result.findings) for result in results)
    failed = security_gate_failed(results)
    status = "failed" if failed else "passed"
    click.echo(f"security: {len(results)} tool(s), {total} finding(s), gate {status}")

    if failed:
        sys.exit(1)


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
