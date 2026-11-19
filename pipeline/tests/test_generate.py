"""Tests for deterministic artifact generation."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from mbse import generate


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_requirement(
    root: Path,
    requirement_id: str,
    title: str,
    *,
    req_type: str = "functional",
    status: str = "approved",
) -> None:
    content = (
        f"id: {requirement_id}\n"
        f'title: "{title}"\n'
        f'text: "{title} shall be satisfied."\n'
        f"type: {req_type}\n"
        "priority: high\n"
        "owner: team-demo\n"
        "verification: test\n"
        f"status: {status}\n"
        'rationale: "Demonstrates the generated artifacts."\n'
    )
    _write(root / "requirements" / f"{requirement_id}.yaml", content)


def _write_api(root: Path, *, broken: bool = False) -> None:
    setpoint = (
        ""
        if broken
        else (
            '    @app.put("/setpoint")\n'
            "    async def setpoint(payload: dict) -> dict:\n"
            "        return payload\n"
            "\n"
        )
    )
    content = (
        "# @implements REQ-001\n"
        "from __future__ import annotations\n"
        "\n"
        "from fastapi import FastAPI\n"
        "\n"
        "\n"
        "def create_app() -> FastAPI:\n"
        '    app = FastAPI(title="Demo")\n'
        "\n"
        '    @app.get("/status")\n'
        "    async def status() -> dict:\n"
        '        return {"state": "ok"}\n'
        "\n"
        f"{setpoint}"
        "    return app\n"
    )
    _write(root / "src" / "thermostat" / "__init__.py", "")
    _write(root / "src" / "thermostat" / "api.py", content)


def _write_project(root: Path) -> None:
    _write_requirement(root, "REQ-001", "Temperature setpoint tracking")
    _write_requirement(root, "REQ-002", "Authenticated setpoint updates", req_type="security")
    _write_requirement(root, "REQ-003", "Legacy display", status="deprecated")
    _write_api(root)

    model = (
        "system: DemoSystem\n"
        "version: 1.0.0\n"
        "elements:\n"
        "  - id: BLK-controller\n"
        "    kind: block\n"
        "    name: Controller\n"
        "    satisfies: [REQ-001]\n"
        "    allocated_to: src/thermostat/api.py\n"
        "  - id: BLK-extra\n"
        "    kind: block\n"
        "    name: Extra\n"
        "    satisfies: [REQ-002]\n"
        "    allocated_to: src/thermostat/api.py\n"
        "relations:\n"
        "  - {from: BLK-controller, to: BLK-extra, type: uses}\n"
    )
    _write(root / "models" / "system.yaml", model)

    tests = (
        "import pytest\n"
        "\n"
        "\n"
        '@pytest.mark.req("REQ-001")\n'
        "def test_status() -> None:\n"
        "    assert True\n"
    )
    _write(root / "tests" / "test_api.py", tests)

    results = {
        "REQ-001": [{"test": "tests/test_api.py::test_status", "outcome": "passed"}],
    }
    _write(root / "build" / "reports" / "req_results.json", json.dumps(results))


@contextmanager
def _isolated_thermostat() -> Iterator[None]:
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == "thermostat" or name.startswith("thermostat.")
    }
    for name in saved:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in [
            name for name in sys.modules if name == "thermostat" or name.startswith("thermostat.")
        ]:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def test_generate_docs_contains_requirements_and_is_byte_identical(tmp_path: Path) -> None:
    _write_project(tmp_path)

    first_paths = generate.generate_docs(tmp_path)
    first = {path.name: path.read_bytes() for path in first_paths}
    second_paths = generate.generate_docs(tmp_path)
    second = {path.name: path.read_bytes() for path in second_paths}

    assert [path.name for path in first_paths] == [
        "architecture.md",
        "requirements.md",
        "rtm.md",
    ]
    assert first == second

    requirements = first["requirements.md"].decode("utf-8")
    architecture = first["architecture.md"].decode("utf-8")
    rtm = first["rtm.md"].decode("utf-8")

    assert "REQ-001" in requirements
    assert "REQ-002" in requirements
    assert "Temperature setpoint tracking" in requirements
    assert "| ID | Title | Type | Priority | Owner | Verification | Status | Text |" in requirements

    assert "DemoSystem" in architecture
    assert "1.0.0" in architecture
    assert "BLK-controller" in architecture
    assert "```mermaid" in architecture
    assert "flowchart LR" in architecture
    assert "| ID | Kind | Name | Satisfies | Allocated to |" in architecture

    header = "| Req ID | Title | Priority | Model elements | Code | Tests | Last result | Status |"
    assert header in rtm
    assert "REQ-001" in rtm
    assert "pass" in rtm
    assert "REQ-002" in rtm
    assert "not-run" in rtm


def test_generate_diagrams_without_graphviz_writes_plantuml_and_dot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(generate.shutil, "which", lambda name: None)

    paths = generate.generate_diagrams(tmp_path)
    names = [path.name for path in paths]

    assert names == [
        "block-definition.dot",
        "block-definition.puml",
        "requirements.puml",
    ]
    assert not (tmp_path / "build" / "diagrams" / "block-definition.svg").exists()

    puml = (tmp_path / "build" / "diagrams" / "block-definition.puml").read_text(encoding="utf-8")
    dot = (tmp_path / "build" / "diagrams" / "block-definition.dot").read_text(encoding="utf-8")
    requirements = (tmp_path / "build" / "diagrams" / "requirements.puml").read_text(
        encoding="utf-8"
    )

    assert puml.startswith("@startuml")
    assert puml.endswith("@enduml\n")
    assert "BLK-controller" in puml
    assert dot.startswith('digraph "DemoSystem"')
    assert '"BLK-controller" -> "BLK-extra"' in dot
    assert "REQ-001" in requirements

    first = {path.name: path.read_bytes() for path in paths}
    generate.generate_diagrams(tmp_path)
    assert {path.name: path.read_bytes() for path in paths} == first


def test_generate_diagrams_renders_svg_when_dot_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(
        generate.shutil,
        "which",
        lambda name: "/usr/bin/dot" if name == "dot" else None,
    )

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        output = Path(command[command.index("-o") + 1])
        output.write_text("<svg></svg>\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(generate.subprocess, "run", fake_run)

    paths = generate.generate_diagrams(tmp_path)

    assert "block-definition.svg" in [path.name for path in paths]
    assert (tmp_path / "build" / "diagrams" / "block-definition.svg").is_file()


def test_generate_openapi_writes_sorted_schema_and_cleans_sys_path(tmp_path: Path) -> None:
    _write_project(tmp_path)
    src = str((tmp_path / "src").resolve())

    with _isolated_thermostat():
        path = generate.generate_openapi(tmp_path)

    raw = path.read_text(encoding="utf-8")
    schema = json.loads(raw)

    assert raw == json.dumps(schema, indent=2, sort_keys=True) + "\n"
    assert "get" in schema["paths"]["/status"]
    assert "put" in schema["paths"]["/setpoint"]
    assert src not in sys.path


def test_generate_openapi_raises_on_missing_endpoint(tmp_path: Path) -> None:
    _write_project(tmp_path)
    _write_api(tmp_path, broken=True)

    with _isolated_thermostat(), pytest.raises(ValueError, match="/setpoint"):
        generate.generate_openapi(tmp_path)


def test_generate_test_stubs_only_for_untested_requirements(tmp_path: Path) -> None:
    _write_project(tmp_path)

    paths = generate.generate_test_stubs(tmp_path)

    assert [path.name for path in paths] == ["test_req_002.py", "test_req_003.py"]
    stub = paths[0].read_text(encoding="utf-8")
    assert '@pytest.mark.req("REQ-002")' in stub
    assert "def test_req_002() -> None:" in stub
    assert "pytest.skip(" in stub
    assert "REQ-002" in stub
    assert not (tmp_path / "build" / "stubs" / "test_req_001.py").exists()


def test_generate_sbom_falls_back_to_deterministic_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(generate.shutil, "which", lambda name: None)

    first_path = generate.generate_sbom(tmp_path)
    first = first_path.read_bytes()
    second = generate.generate_sbom(tmp_path).read_bytes()

    assert first == second
    data = json.loads(first)
    assert data["bomFormat"] == "CycloneDX"
    assert data["specVersion"] == "1.5"
    assert "serialNumber" not in data
    assert "timestamp" not in data.get("metadata", {})

    names = [component["name"] for component in data["components"]]
    assert names == sorted(names)
    assert {"click", "fastapi", "pyyaml", "uvicorn"} <= set(names)


def test_generate_sbom_normalises_tool_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(
        generate.shutil,
        "which",
        lambda name: "/usr/bin/cyclonedx-py" if name == "cyclonedx-py" else None,
    )
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "serialNumber": "urn:uuid:random-value",
        "metadata": {"timestamp": "2026-01-01T00:00:00Z", "component": {"name": "demo"}},
        "components": [
            {"type": "library", "name": "zeta", "version": "9.0.0"},
            {"type": "library", "name": "alpha", "version": "1.0.0"},
        ],
    }

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        output = Path(command[command.index("--output-file") + 1])
        output.write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(generate.subprocess, "run", fake_run)

    first_path = generate.generate_sbom(tmp_path)
    first = first_path.read_bytes()
    second = generate.generate_sbom(tmp_path).read_bytes()

    assert first == second
    data = json.loads(first)
    assert "serialNumber" not in data
    assert "timestamp" not in data["metadata"]
    assert [component["name"] for component in data["components"]] == ["alpha", "zeta"]


def test_generate_all_returns_sorted_unique_existing_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(generate.shutil, "which", lambda name: None)

    with _isolated_thermostat():
        paths = generate.generate_all(tmp_path)

    assert paths == sorted(set(paths), key=str)
    assert all(path.is_file() for path in paths)
    assert {path.name for path in paths} >= {
        "requirements.md",
        "architecture.md",
        "rtm.md",
        "block-definition.puml",
        "requirements.puml",
        "block-definition.dot",
        "openapi.json",
        "test_req_002.py",
        "sbom.json",
    }
