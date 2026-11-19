"""Load requirement, system-model, code-tag, and test-tag artifacts."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CODE_TAG = re.compile(r"@implements\s+(REQ-\d{3})")


class LoadError(Exception):
    """Raised when an artifact cannot be read or parsed."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass
class Requirement:
    """A single requirement loaded from ``requirements/*.yaml``."""

    id: str
    title: str
    text: str
    type: str
    priority: str
    owner: str
    verification: str
    status: str
    rationale: str
    parent: str | None
    path: str
    raw: dict[str, Any]


@dataclass
class ModelElement:
    """A block, interface, behavior, or actor from the system model."""

    id: str
    kind: str
    name: str
    satisfies: tuple[str, ...]
    allocated_to: str | None
    raw: dict[str, Any]


@dataclass
class ModelRelation:
    """A directed relation between two model elements."""

    from_id: str
    to_id: str
    type: str
    raw: dict[str, Any]


@dataclass
class SystemModel:
    """The parsed ``models/system.yaml`` system model."""

    system: str
    version: str
    elements: list[ModelElement]
    relations: list[ModelRelation]
    path: str
    raw: dict[str, Any]


def _display_path(path: Path, root: Path) -> str:
    """Return a root-relative POSIX path for stable reporting."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _as_str(value: Any) -> str:
    """Coerce a scalar field to a string, treating ``None`` as empty."""
    if value is None:
        return ""
    return str(value)


def _read_yaml(path: Path, root: Path) -> dict[str, Any]:
    """Read a YAML mapping, raising :class:`LoadError` on any problem."""
    display = _display_path(path, root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LoadError(display, " ".join(str(exc).split())) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LoadError(display, " ".join(str(exc).split())) from exc
    if not isinstance(data, dict):
        raise LoadError(display, "expected a YAML mapping")
    return data


def _yaml_files(directory: Path) -> list[Path]:
    """Return the YAML files directly inside ``directory`` in sorted order."""
    if not directory.is_dir():
        return []
    return sorted(set(directory.glob("*.yaml")) | set(directory.glob("*.yml")))


def load_requirements(root: Path = Path(".")) -> list[Requirement]:
    """Load every requirement file under ``root/requirements`` sorted by ID."""
    root = Path(root)
    requirements: list[Requirement] = []
    for path in _yaml_files(root / "requirements"):
        raw = _read_yaml(path, root)
        parent_value = raw.get("parent")
        requirements.append(
            Requirement(
                id=_as_str(raw.get("id")),
                title=_as_str(raw.get("title")),
                text=_as_str(raw.get("text")),
                type=_as_str(raw.get("type")),
                priority=_as_str(raw.get("priority")),
                owner=_as_str(raw.get("owner")),
                verification=_as_str(raw.get("verification")),
                status=_as_str(raw.get("status")),
                rationale=_as_str(raw.get("rationale")),
                parent=_as_str(parent_value) if parent_value is not None else None,
                path=_display_path(path, root),
                raw=raw,
            )
        )
    return sorted(requirements, key=lambda requirement: requirement.id)


def _satisfies(value: Any) -> tuple[str, ...]:
    """Normalise a ``satisfies`` YAML value to a tuple of requirement IDs."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(_as_str(item) for item in value)
    return ()


def load_model(root: Path = Path(".")) -> SystemModel:
    """Load ``root/models/system.yaml``, the single source of truth for the model."""
    root = Path(root)
    path = root / "models" / "system.yaml"
    display = _display_path(path, root)
    if not path.is_file():
        raise LoadError(display, "system model not found")
    raw = _read_yaml(path, root)

    raw_elements = raw.get("elements")
    elements: list[ModelElement] = []
    if isinstance(raw_elements, list):
        for item in raw_elements:
            if not isinstance(item, dict):
                raise LoadError(display, "each element must be a mapping")
            allocated = item.get("allocated_to")
            elements.append(
                ModelElement(
                    id=_as_str(item.get("id")),
                    kind=_as_str(item.get("kind")),
                    name=_as_str(item.get("name")),
                    satisfies=_satisfies(item.get("satisfies")),
                    allocated_to=_as_str(allocated) if allocated is not None else None,
                    raw=item,
                )
            )

    raw_relations = raw.get("relations")
    relations: list[ModelRelation] = []
    if isinstance(raw_relations, list):
        for item in raw_relations:
            if not isinstance(item, dict):
                raise LoadError(display, "each relation must be a mapping")
            relations.append(
                ModelRelation(
                    from_id=_as_str(item.get("from")),
                    to_id=_as_str(item.get("to")),
                    type=_as_str(item.get("type")),
                    raw=item,
                )
            )

    return SystemModel(
        system=_as_str(raw.get("system")),
        version=_as_str(raw.get("version")),
        elements=elements,
        relations=relations,
        path=display,
        raw=raw,
    )


def load_code_tags(root: Path = Path(".")) -> dict[str, tuple[str, ...]]:
    """Map requirement IDs to sorted source paths containing ``@implements`` tags."""
    root = Path(root)
    source_root = root / "src"
    if not source_root.is_dir():
        return {}
    paths_by_id: dict[str, set[str]] = {}
    for path in sorted(source_root.rglob("*.py")):
        display = _display_path(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LoadError(display, " ".join(str(exc).split())) from exc
        for requirement_id in _CODE_TAG.findall(text):
            paths_by_id.setdefault(requirement_id, set()).add(display)
    return {
        requirement_id: tuple(sorted(paths))
        for requirement_id, paths in sorted(paths_by_id.items())
    }


def _is_req_marker(decorator: ast.expr) -> bool:
    """Return whether ``decorator`` calls ``mark.req`` or ``pytest.mark.req``."""
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    if not isinstance(func, ast.Attribute) or func.attr != "req":
        return False
    owner = func.value
    if isinstance(owner, ast.Name) and owner.id == "mark":
        return True
    return (
        isinstance(owner, ast.Attribute)
        and owner.attr == "mark"
        and isinstance(owner.value, ast.Name)
        and owner.value.id == "pytest"
    )


def _marker_ids(decorator: ast.Call) -> tuple[str, ...]:
    """Extract literal string requirement IDs from a ``mark.req`` call."""
    ids: list[str] = []
    for argument in decorator.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            ids.append(argument.value)
    return tuple(ids)


def load_test_tags(root: Path = Path(".")) -> dict[str, tuple[str, ...]]:
    """Map requirement IDs to sorted test paths using ``mark.req`` decorators."""
    root = Path(root)
    tests_root = root / "tests"
    if not tests_root.is_dir():
        return {}
    paths_by_id: dict[str, set[str]] = {}
    for path in sorted(tests_root.rglob("*.py")):
        display = _display_path(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LoadError(display, " ".join(str(exc).split())) from exc
        try:
            tree = ast.parse(text, filename=display)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            decorators = getattr(node, "decorator_list", ())
            for decorator in decorators:
                if _is_req_marker(decorator):
                    for requirement_id in _marker_ids(decorator):
                        paths_by_id.setdefault(requirement_id, set()).add(display)
    return {
        requirement_id: tuple(sorted(paths))
        for requirement_id, paths in sorted(paths_by_id.items())
    }
