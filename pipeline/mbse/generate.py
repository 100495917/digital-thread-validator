"""Deterministic artifact generation: documentation, diagrams, OpenAPI, stubs, SBOM."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .loaders import load_code_tags, load_model, load_requirements, load_test_tags

_TEMPLATE_DIRECTORY = Path(__file__).resolve().parent / "templates"

_DOCS_DIRECTORY = Path("docs") / "generated"
_DIAGRAM_DIRECTORY = Path("build") / "diagrams"
_REPORT_DIRECTORY = Path("build") / "reports"
_STUB_DIRECTORY = Path("build") / "stubs"
_OPENAPI_PATH = Path("build") / "openapi.json"
_RESULTS_PATH = _REPORT_DIRECTORY / "req_results.json"

_RUNTIME_DEPENDENCIES = ("click", "fastapi", "pyyaml", "uvicorn")

_PASSED_OUTCOMES = {"passed", "pass", "success", "succeeded"}
_FAILED_OUTCOMES = {"failed", "fail", "error", "errored"}


def _write_text(path: Path, content: str) -> Path:
    """Write ``content`` to ``path``, creating parents and ending with a newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _json_text(value: object) -> str:
    """Return deterministic, pretty-printed JSON ending with one newline."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _cell(value: object) -> str:
    """Collapse a value onto one Markdown table cell line."""
    text = "" if value is None else str(value)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return text.replace("|", "\\|")


def _list_cell(values: tuple[str, ...]) -> str:
    return "; ".join(values)


def _normalise(value: object) -> str:
    return str(value or "").strip().lower()


def _last_result(requirement_id: str, results: dict[str, list[dict[str, object]]]) -> str:
    """Reimplementation of the RTM last-result rule for one requirement."""
    entries = results.get(requirement_id)
    if not entries:
        return "not-run"

    outcomes = [_normalise(entry.get("outcome")) for entry in entries]
    has_pass = any(outcome in _PASSED_OUTCOMES for outcome in outcomes)
    has_fail = any(outcome in _FAILED_OUTCOMES for outcome in outcomes)

    if has_pass and has_fail:
        return "mixed"
    if has_fail:
        return "fail"
    if outcomes and all(outcome in _PASSED_OUTCOMES for outcome in outcomes):
        return "pass"
    return "not-run"


def _load_results(root: Path) -> dict[str, list[dict[str, object]]]:
    try:
        raw = json.loads((root / _RESULTS_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    results: dict[str, list[dict[str, object]]] = {}
    for requirement_id, entries in raw.items():
        if isinstance(entries, list):
            results[str(requirement_id)] = [entry for entry in entries if isinstance(entry, dict)]
    return results


def _satisfying_elements(root: Path) -> dict[str, tuple[str, ...]]:
    model = load_model(root)
    satisfiers: dict[str, set[str]] = {}
    for element in model.elements:
        for requirement_id in element.satisfies:
            satisfiers.setdefault(requirement_id, set()).add(element.id)
    return {requirement_id: tuple(sorted(ids)) for requirement_id, ids in satisfiers.items()}


def _rtm_status(
    requirement_status: str,
    *,
    model_elements: tuple[str, ...],
    code_paths: tuple[str, ...],
    test_paths: tuple[str, ...],
) -> str:
    if _normalise(requirement_status) == "deprecated":
        return "deprecated"
    complete = bool(model_elements and code_paths and test_paths)
    return "complete" if complete else "incomplete"


def _rtm_rows(root: Path) -> list[dict[str, str]]:
    requirements = load_requirements(root)
    satisfiers = _satisfying_elements(root)
    code_tags = load_code_tags(root)
    test_tags = load_test_tags(root)
    results = _load_results(root)

    rows: list[dict[str, str]] = []
    for requirement in requirements:
        model_elements = satisfiers.get(requirement.id, ())
        code_paths = code_tags.get(requirement.id, ())
        test_paths = test_tags.get(requirement.id, ())
        rows.append(
            {
                "req_id": _cell(requirement.id),
                "title": _cell(requirement.title),
                "priority": _cell(requirement.priority),
                "model_elements": _cell(_list_cell(model_elements)),
                "code": _cell(_list_cell(code_paths)),
                "tests": _cell(_list_cell(test_paths)),
                "last_result": _cell(_last_result(requirement.id, results)),
                "status": _cell(
                    _rtm_status(
                        requirement.status,
                        model_elements=model_elements,
                        code_paths=code_paths,
                        test_paths=test_paths,
                    )
                ),
            }
        )
    return rows


def _sorted_relations(model: Any) -> list[Any]:
    return sorted(
        model.relations,
        key=lambda relation: (relation.from_id, relation.to_id, relation.type),
    )


def _mermaid_text(model: Any) -> str:
    """Build a deterministic Mermaid flowchart from model elements and relations."""
    elements = sorted(model.elements, key=lambda element: element.id)
    relations = _sorted_relations(model)

    aliases = {element.id: _identifier_alias("n_", element.id) for element in elements}
    lines = ["flowchart LR"]
    for element in elements:
        label = f"{element.id}<br/>{element.name}" if element.name else element.id
        label = label.replace('"', "&quot;")
        lines.append(f'    {aliases[element.id]}["{label}"]')
    for relation in relations:
        if relation.from_id not in aliases or relation.to_id not in aliases:
            continue
        label = relation.type.replace('"', "&quot;")
        lines.append(f"    {aliases[relation.from_id]} -->|{label}| {aliases[relation.to_id]}")
    return "\n".join(lines)


def _render_template(name: str, context: dict[str, object]) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIRECTORY)),
        autoescape=select_autoescape(default=False, default_for_string=False),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template(name)
    content = template.render(**context)
    if not content.endswith("\n"):
        content += "\n"
    return content


def generate_docs(root: Path = Path(".")) -> list[Path]:
    """Render requirements, architecture, and RTM Markdown documents."""
    root = Path(root)
    requirements = load_requirements(root)
    model = load_model(root)
    elements = sorted(model.elements, key=lambda element: element.id)
    relations = _sorted_relations(model)

    requirement_rows = [
        {
            "id": _cell(requirement.id),
            "title": _cell(requirement.title),
            "type": _cell(requirement.type),
            "priority": _cell(requirement.priority),
            "owner": _cell(requirement.owner),
            "verification": _cell(requirement.verification),
            "status": _cell(requirement.status),
            "text": _cell(requirement.text),
        }
        for requirement in requirements
    ]
    element_rows = [
        {
            "id": _cell(element.id),
            "kind": _cell(element.kind),
            "name": _cell(element.name),
            "satisfies": _cell(_list_cell(element.satisfies)),
            "allocated_to": _cell(element.allocated_to or ""),
        }
        for element in elements
    ]
    relation_rows = [
        {
            "from": _cell(relation.from_id),
            "to": _cell(relation.to_id),
            "type": _cell(relation.type),
        }
        for relation in relations
    ]

    docs = {
        "requirements.md": _render_template(
            "requirements.md.j2", {"requirements": requirement_rows}
        ),
        "architecture.md": _render_template(
            "architecture.md.j2",
            {
                "system": _cell(model.system),
                "version": _cell(model.version),
                "elements": element_rows,
                "relations": relation_rows,
                "mermaid": _mermaid_text(model),
            },
        ),
        "rtm.md": _render_template("rtm.md.j2", {"rows": _rtm_rows(root)}),
    }

    paths = [_write_text(root / _DOCS_DIRECTORY / name, content) for name, content in docs.items()]
    return sorted(paths, key=lambda path: str(path))


def _identifier_alias(prefix: str, value: str) -> str:
    return prefix + re.sub(r"[^0-9A-Za-z_]", "_", value)


def _plantuml_label(value: str) -> str:
    return value.replace("\\", "/").replace('"', "'").replace("\r", " ").replace("\n", " ")


def _block_definition_puml(model: Any) -> str:
    elements = sorted(model.elements, key=lambda element: element.id)
    relations = _sorted_relations(model)
    aliases = {element.id: _identifier_alias("E_", element.id) for element in elements}

    title = f"{_plantuml_label(model.system)} {_plantuml_label(model.version)}".rstrip()
    lines = ["@startuml", f"title {title}"]
    for element in elements:
        label = _plantuml_label(element.id)
        if element.name:
            label += "\\n" + _plantuml_label(element.name)
        lines.append(f'class "{label}" as {aliases[element.id]} {{')
        lines.append(f"  kind: {_plantuml_label(element.kind)}")
        if element.allocated_to:
            lines.append(f"  allocated to: {_plantuml_label(element.allocated_to)}")
        lines.append("}")
    for relation in relations:
        if relation.from_id not in aliases or relation.to_id not in aliases:
            continue
        lines.append(
            f"{aliases[relation.from_id]} --> {aliases[relation.to_id]} : "
            f"{_plantuml_label(relation.type)}"
        )
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def _requirements_puml(root: Path) -> str:
    model = load_model(root)
    requirements = load_requirements(root)
    elements = sorted(model.elements, key=lambda element: element.id)
    requirement_aliases = {
        requirement.id: _identifier_alias("R_", requirement.id) for requirement in requirements
    }
    element_aliases = {element.id: _identifier_alias("E_", element.id) for element in elements}

    lines = ["@startuml", "title Requirement traceability"]
    for requirement in requirements:
        label = _plantuml_label(requirement.id)
        if requirement.title:
            label += "\\n" + _plantuml_label(requirement.title)
        lines.append(f'class "{label}" as {requirement_aliases[requirement.id]} {{')
        lines.append(f"  type: {_plantuml_label(requirement.type)}")
        lines.append(f"  status: {_plantuml_label(requirement.status)}")
        lines.append("}")
    for element in elements:
        if not element.satisfies:
            continue
        lines.append(
            f'class "{_plantuml_label(element.id)}\\n{_plantuml_label(element.name)}" '
            f"as {element_aliases[element.id]}"
        )
        for requirement_id in sorted(element.satisfies):
            if requirement_id not in requirement_aliases:
                continue
            edge = f"{element_aliases[element.id]} --> {requirement_aliases[requirement_id]}"
            lines.append(f"{edge} : satisfies")
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def _dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", "\\n")


def _block_definition_dot(model: Any) -> str:
    elements = sorted(model.elements, key=lambda element: element.id)
    relations = _sorted_relations(model)
    shapes = {"actor": "ellipse", "behavior": "component", "interface": "ellipse"}

    lines = [f'digraph "{_dot_escape(model.system)}" {{', "  rankdir=LR;"]
    for element in elements:
        label = element.id if not element.name else f"{element.id}\n{element.name}"
        shape = shapes.get(_normalise(element.kind), "box")
        lines.append(
            f'  "{_dot_escape(element.id)}" [label="{_dot_escape(label)}", shape={shape}];'
        )
    for relation in relations:
        lines.append(
            f'  "{_dot_escape(relation.from_id)}" -> "{_dot_escape(relation.to_id)}" '
            f'[label="{_dot_escape(relation.type)}"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def generate_diagrams(root: Path = Path(".")) -> list[Path]:
    """Write deterministic PlantUML and Graphviz diagrams, plus SVG when ``dot`` exists."""
    root = Path(root)
    model = load_model(root)

    paths = [
        _write_text(
            root / _DIAGRAM_DIRECTORY / "block-definition.puml",
            _block_definition_puml(model),
        ),
        _write_text(
            root / _DIAGRAM_DIRECTORY / "requirements.puml",
            _requirements_puml(root),
        ),
        _write_text(
            root / _DIAGRAM_DIRECTORY / "block-definition.dot",
            _block_definition_dot(model),
        ),
    ]

    dot_binary = shutil.which("dot")
    if dot_binary:
        dot_path = root / _DIAGRAM_DIRECTORY / "block-definition.dot"
        svg_path = root / _DIAGRAM_DIRECTORY / "block-definition.svg"
        try:
            subprocess.run(
                [dot_binary, "-Tsvg", str(dot_path), "-o", str(svg_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            pass
        else:
            if svg_path.is_file():
                paths.append(svg_path)

    return sorted(paths, key=lambda path: str(path))


def _load_create_app(root: Path) -> Any:
    src = (root / "src").resolve()
    src_text = str(src)
    added = src_text not in sys.path
    if added:
        sys.path.insert(0, src_text)
    try:
        module = importlib.import_module("thermostat.api")
        create_app = module.create_app
        return create_app()
    finally:
        if added:
            try:
                sys.path.remove(src_text)
            except ValueError:
                pass


def generate_openapi(root: Path = Path(".")) -> Path:
    """Dump the FastAPI schema after checking the required endpoints exist."""
    root = Path(root)
    app = _load_create_app(root)
    schema = app.openapi()

    paths = schema.get("paths")
    if not isinstance(paths, dict):
        paths = {}
    status_path = paths.get("/status")
    setpoint_path = paths.get("/setpoint")
    if not isinstance(status_path, dict) or "get" not in status_path:
        raise ValueError("missing GET /status endpoint")
    if not isinstance(setpoint_path, dict) or "put" not in setpoint_path:
        raise ValueError("missing PUT /setpoint endpoint")

    return _write_text(root / _OPENAPI_PATH, json.dumps(schema, indent=2, sort_keys=True) + "\n")


def _requirement_number(requirement_id: str) -> str:
    match = re.search(r"(\d+)$", requirement_id)
    if match:
        return f"{int(match.group(1)):03d}"
    return re.sub(r"[^0-9A-Za-z_]", "_", requirement_id)


def _requirement_title(title: str) -> str:
    text = " ".join(title.replace("\r", " ").replace("\n", " ").split())
    return text.replace("\\", "/").replace('"', "'")


def generate_test_stubs(root: Path = Path(".")) -> list[Path]:
    """Write pytest skeletons for requirements without a requirement-tagged test."""
    root = Path(root)
    requirements = load_requirements(root)
    test_tags = load_test_tags(root)

    paths: list[Path] = []
    for requirement in requirements:
        if test_tags.get(requirement.id):
            continue
        number = _requirement_number(requirement.id)
        title = _requirement_title(requirement.title)
        suffix = f": {title}" if title else ""
        content = (
            f'"""Requirement test stub for {requirement.id}{suffix}."""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            "import pytest\n"
            "\n"
            "\n"
            f'@pytest.mark.req("{requirement.id}")\n'
            f"def test_req_{number}() -> None:\n"
            f'    """Verify {requirement.id} is implemented."""\n'
            f'    pytest.skip("{requirement.id} has no requirement-tagged test yet")\n'
        )
        paths.append(_write_text(root / _STUB_DIRECTORY / f"test_req_{number}.py", content))

    return sorted(paths, key=lambda path: str(path))


def _dependency_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _fallback_sbom() -> dict[str, object]:
    components = [
        {
            "type": "library",
            "name": name,
            "version": _dependency_version(name),
            "purl": f"pkg:pypi/{name}@{_dependency_version(name)}",
        }
        for name in _RUNTIME_DEPENDENCIES
    ]
    components.sort(key=lambda component: (str(component["name"]), str(component["version"])))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": components,
    }


_RANDOM_BOM_REF = re.compile(r"^BomRef\.\d+\.\d+$")


def _stabilise_bom_refs(value: Any) -> None:
    """Replace CycloneDX random ``BomRef.x.y`` identifiers in place."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "bom-ref" and isinstance(item, str) and _RANDOM_BOM_REF.match(item):
                value[key] = "BomRef.project"
            else:
                _stabilise_bom_refs(item)
    elif isinstance(value, list):
        for item in value:
            _stabilise_bom_refs(item)


def _normalise_sbom(data: dict[str, Any]) -> dict[str, Any]:
    data.pop("serialNumber", None)
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("timestamp", None)
    components = data.get("components")
    if isinstance(components, list):
        data["components"] = sorted(
            components,
            key=lambda component: (
                str(component.get("name", "")) if isinstance(component, dict) else "",
                str(component.get("version", "")) if isinstance(component, dict) else "",
            ),
        )
    _stabilise_bom_refs(data)
    return data


def generate_sbom(root: Path = Path(".")) -> Path:
    """Write a deterministic CycloneDX SBOM, using the CLI when it is usable."""
    root = Path(root)
    report_path = root / _REPORT_DIRECTORY / "sbom.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] | None = None
    tool = shutil.which("cyclonedx-py")
    if tool:
        try:
            with tempfile.TemporaryDirectory(
                dir=report_path.parent, prefix=".sbom-"
            ) as temp_directory:
                temp_path = Path(temp_directory) / "sbom.json"
                result = subprocess.run(
                    [
                        tool,
                        "environment",
                        "--output-file",
                        str(temp_path),
                        "--output-format",
                        "json",
                    ],
                    check=False,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    raw = json.loads(temp_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("components"), list):
                        data = _normalise_sbom(raw)
        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            data = None

    if data is None:
        data = _fallback_sbom()

    return _write_text(report_path, _json_text(data))


def generate_all(root: Path = Path(".")) -> list[Path]:
    """Generate every Phase 5 artifact and return the sorted unique paths."""
    root = Path(root)
    paths: list[Path] = []
    paths.extend(generate_docs(root))
    paths.extend(generate_diagrams(root))
    paths.append(generate_openapi(root))
    paths.extend(generate_test_stubs(root))
    paths.append(generate_sbom(root))
    return sorted(set(paths), key=lambda path: str(path))
