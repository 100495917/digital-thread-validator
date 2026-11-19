"""Structural validation for the system model (Phase 3.3)."""

from __future__ import annotations

import re
from pathlib import Path

from .findings import Finding, sort_findings
from .loaders import ModelElement, SystemModel, load_requirements

MODEL_PATH = "models/system.yaml"

KIND_PREFIXES = {
    "block": "BLK-",
    "interface": "IF-",
    "behavior": "BHV-",
    "action": "ACT-",
}

PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _finding(rule: str, message: str) -> Finding:
    return Finding(path=MODEL_PATH, rule=rule, severity="error", message=message)


def _duplicate_ids(elements: list[ModelElement]) -> set[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for element in elements:
        if element.id in seen and element.id not in duplicates:
            duplicates.append(element.id)
        seen.add(element.id)
    return set(duplicates)


def _check_duplicate_ids(elements: list[ModelElement]) -> list[Finding]:
    return [
        _finding("MDL-001", f"{element_id}: duplicate element id")
        for element_id in sorted(_duplicate_ids(elements))
    ]


def _check_naming(elements: list[ModelElement]) -> list[Finding]:
    findings: list[Finding] = []
    for element in elements:
        prefix = KIND_PREFIXES.get(element.kind)
        if prefix is None:
            findings.append(
                _finding(
                    "MDL-002",
                    f"{element.id}: unsupported element kind '{element.kind}'",
                )
            )
        elif not element.id.startswith(prefix):
            findings.append(
                _finding(
                    "MDL-002",
                    f"{element.id}: id for kind '{element.kind}' must start with '{prefix}'",
                )
            )
        if element.kind == "block" and not PASCAL_CASE.match(element.name):
            findings.append(
                _finding(
                    "MDL-002",
                    f"{element.id}: block name '{element.name}' must be PascalCase",
                )
            )
    return findings


def _check_satisfies(elements: list[ModelElement], requirement_ids: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for element in elements:
        for requirement_id in element.satisfies:
            if requirement_id not in requirement_ids:
                findings.append(
                    _finding(
                        "MDL-003",
                        f"{element.id}: satisfies unknown requirement '{requirement_id}'",
                    )
                )
    return findings


def _check_allocations(elements: list[ModelElement], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for element in elements:
        allocated_to = element.allocated_to
        if allocated_to and not (root / allocated_to).exists():
            findings.append(
                _finding(
                    "MDL-004",
                    f"{element.id}: allocated_to path '{allocated_to}' does not exist",
                )
            )
    return findings


def _check_orphans(elements: list[ModelElement], relations: list[tuple[str, str]]) -> list[Finding]:
    connected = {element_id for relation in relations for element_id in relation}
    findings: list[Finding] = []
    for element in elements:
        if element.kind == "block" and element.id not in connected and not element.satisfies:
            findings.append(
                _finding(
                    "MDL-005",
                    f"{element.id}: block has no relations and satisfies no requirement",
                )
            )
    return findings


def _check_relations(
    elements: list[ModelElement], relations: list[tuple[str, str]]
) -> list[Finding]:
    element_ids = {element.id for element in elements}
    findings: list[Finding] = []
    for from_id, to_id in relations:
        if from_id not in element_ids:
            findings.append(
                _finding(
                    "MDL-006",
                    f"{from_id}: relation source '{from_id}' does not exist",
                )
            )
        if to_id not in element_ids:
            findings.append(
                _finding(
                    "MDL-006",
                    f"{from_id}: relation target '{to_id}' does not exist",
                )
            )
    return findings


def _check_interfaces(
    elements: list[ModelElement], relations: list[tuple[str, str]]
) -> list[Finding]:
    kinds = {element.id: element.kind for element in elements}
    findings: list[Finding] = []
    for element in elements:
        if element.kind != "interface":
            continue
        blocks = {
            other
            for from_id, to_id in relations
            if element.id in (from_id, to_id)
            for other in (from_id, to_id)
            if other != element.id and kinds.get(other) == "block"
        }
        if len(blocks) < 2:
            findings.append(
                _finding(
                    "MDL-007",
                    f"{element.id}: interface connects to {len(blocks)} block(s); "
                    "expected at least 2",
                )
            )
    return findings


def validate_model(
    model: SystemModel,
    root: Path = Path("."),
    requirement_ids: set[str] | None = None,
) -> list[Finding]:
    """Return structural findings for ``model`` sorted by path, rule, and message."""
    if requirement_ids is None:
        requirement_ids = {requirement.id for requirement in load_requirements(root)}

    elements = list(model.elements)
    relations = [(relation.from_id, relation.to_id) for relation in model.relations]

    findings: list[Finding] = []
    findings.extend(_check_duplicate_ids(elements))
    findings.extend(_check_naming(elements))
    findings.extend(_check_satisfies(elements, requirement_ids))
    findings.extend(_check_allocations(elements, root))
    findings.extend(_check_orphans(elements, relations))
    findings.extend(_check_relations(elements, relations))
    findings.extend(_check_interfaces(elements, relations))
    return sort_findings(findings)
