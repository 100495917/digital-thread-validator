# Procedimiento manual de la demo

Esta guía reproduce paso a paso lo que hace `scripts/demo.sh`, pero ejecutando los comandos a mano.

La demo se hace en una **copia temporal** del repositorio. No modifica tu árbol de trabajo principal.

## Requisitos

- Linux/macOS con `bash`, `git`, `python` y `pytest`.
- Entorno virtual activado y proyecto instalado:

```bash
cd /ruta/a/digital-thread-validator
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Comprueba que `mbse` está disponible:

```bash
mbse --help
```

## 1. Crear una copia aislada

Ejecuta esto desde la raíz del repositorio:

```bash
REPO="$PWD"
DEMO="$(mktemp -d)"
mkdir -p "$DEMO/project"

tar -C "$REPO" \
  --exclude=./.git \
  --exclude=./.venv \
  --exclude=./build \
  --exclude=./site \
  --exclude=./docs \
  --exclude=./reports \
  --exclude=./.pytest_cache \
  --exclude=./.ruff_cache \
  --exclude=./.coverage \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.egg-info' \
  -cf - . | tar -C "$DEMO/project" -xf -

cd "$DEMO/project"
rm -rf digital_thread

git init -q
git config user.name "Digital Thread Demo"
git config user.email "demo@example.invalid"
git add -A
git commit -q -m "chore: import demo baseline (REQ-001..REQ-013)"

echo "Directorio de demo: $DEMO/project"
```

A partir de aquí, todos los comandos se ejecutan dentro de `$DEMO/project`. Hazlo todo en la **misma terminal**, porque `DEMO` es una variable de esa sesión.

## 2. Crear la línea base v1.0.0

Valida los artefactos, comprueba la trazabilidad, ejecuta las pruebas de requisitos, genera la RTM y actualiza el digital thread:

```bash
mbse validate all
mbse trace check
python -m pytest tests/requirements
mbse trace rtm
mbse thread update
```

Debes ver una salida similar a:

```text
traceability coverage: 100.0%
verification coverage: 100.0%
```

Congela la línea base y etiqueta el commit:

```bash
mbse baseline freeze v1.0.0
git add baselines
git commit -m "chore(release): freeze baseline v1.0.0"
git tag v1.0.0
```

Evidencia esperada:

- `baselines/baseline-v1.0.0.json`
- Etiqueta `v1.0.0`
- `digital_thread/thread.json`

## 3. Cambiar REQ-003 en una rama

```bash
git checkout -b demo/req-003
sed -i 's/0\.5/0.3/' requirements/REQ-003.yaml
```

Crea la prueba de regresión de la demo:

```bash
cat > tests/requirements/test_req_003_threshold.py <<'PY'
"""Demo-only regression test for the tightened REQ-003 hysteresis threshold."""

from __future__ import annotations

from pathlib import Path

import pytest

from thermostat.controller import HYSTERESIS_DELTA_C


@pytest.mark.req("REQ-003")
def test_req_003_threshold_updated() -> None:
    text = Path("requirements/REQ-003.yaml").read_text(encoding="utf-8")
    assert "0.3" in text
    assert HYSTERESIS_DELTA_C == 0.3
PY
```

Confirma el cambio y valida:

```bash
git add requirements/REQ-003.yaml tests/requirements/test_req_003_threshold.py
git commit -m "feat(REQ-003): tighten heating activation threshold to 0.3 C"
mbse validate all
```

La validación debe seguir pasando: el requisito sigue siendo medible y no ambiguo.

## 4. Actualizar el digital thread y ver la staleness

```bash
mbse thread update
```

Busca en la salida una línea como:

```text
stale: 4
```

El valor exacto puede variar, pero debe ser mayor que cero. Inspecciona el informe:

```bash
sed -n '/^## Stale nodes/,$p' build/reports/thread_diff.md
```

Ahí deben aparecer las pruebas que verifican REQ-003 y que todavía no se han revisado.

## 5. Analizar el impacto desde v1.0.0

```bash
mbse impact --base v1.0.0 --head HEAD
mbse thread query --downstream REQ-003
```

Debes ver artefactos afectados, por ejemplo:

```text
ModelElement BLK-controller
CodeModule src/thermostat/controller.py
Test tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
```

Informes generados:

- `build/reports/impact.json`
- `build/reports/impact.md`
- `build/reports/rtm_diff.md`

## 6. Ejecutar solo las pruebas afectadas (fallo esperado)

Selecciona las pruebas:

```bash
SELECTED="$(python -m mbse.select_tests)"
echo "$SELECTED"
read -r -a TESTS <<<"$SELECTED"
```

La prueba nueva de REQ-003 debe aparecer en la selección.

Ejecuta solo esas pruebas:

```bash
python -m pytest "${TESTS[@]}"
```

El resultado esperado es un fallo, porque el controlador todavía usa `0.5`:

```text
FAILED tests/requirements/test_req_003_threshold.py::test_req_003_threshold_updated
```

Comprueba que el fallo está asociado a REQ-003:

```bash
python - <<'PY'
import json
from pathlib import Path

results = json.loads(Path("build/reports/req_results.json").read_text(encoding="utf-8"))
for entry in results.get("REQ-003", []):
    print(entry["test"], entry["outcome"])
PY
```

Debe aparecer `test_req_003_threshold_updated` con `failed`.

## 7. Corregir el controlador y volver a verde

Cambia la constante del controlador:

```bash
sed -i 's/^HYSTERESIS_DELTA_C = 0.5$/HYSTERESIS_DELTA_C = 0.3/' \
  src/thermostat/controller.py
```

Actualiza las expectativas de frontera que todavía codifican el valor antiguo. Hazlo **solo en la copia temporal**:

```bash
sed -i \
  -e 's/controller.update(21\.4) is True/controller.update(21.2) is True/' \
  -e 's/controller.update(21\.5) is False/controller.update(21.4) is False/' \
  -e 's/controller.update(20\.5) is False/controller.update(20.7) is False/' \
  tests/requirements/test_requirements.py

sed -i \
  -e 's/assert HYSTERESIS_DELTA_C == 0\.5/assert HYSTERESIS_DELTA_C == 0.3/' \
  -e 's/controller.update(20\.5) is False/controller.update(20.7) is False/' \
  -e 's/controller.update(21\.499) is True/controller.update(21.299) is True/' \
  -e 's/controller.update(21\.4) is True/controller.update(21.2) is True/' \
  -e 's/controller.update(20\.6) is False/controller.update(20.7) is False/' \
  tests/unit/test_controller.py

printf '\n# Regression coverage for the v1.1.0 threshold.\n' \
  >> tests/requirements/test_req_003_threshold.py
```

Confirma el arreglo:

```bash
git add src/thermostat/controller.py \
  tests/requirements/test_requirements.py \
  tests/requirements/test_req_003_threshold.py \
  tests/unit/test_controller.py
git commit -m "fix(REQ-003): align controller and tests with the 0.3 C threshold"
```

Valida y ejecuta las pruebas:

```bash
mbse validate all
python -m pytest tests/requirements tests/unit/test_controller.py
python -m pytest "${TESTS[@]}"
```

Ahora todo debe pasar.

Actualiza el thread y comprueba que ya no hay staleness:

```bash
mbse thread update
```

Debe aparecer:

```text
stale: 0
```

Completa las comprobaciones del cambio:

```bash
mbse impact --base v1.0.0 --head HEAD
mbse commits check --range v1.0.0..HEAD --strict
mbse trace rtm
```

## 8. Crear la release v1.1.0

```bash
mbse baseline freeze v1.1.0
git add baselines
git commit -m "chore(release): freeze baseline v1.1.0"
git tag v1.1.0
```

Compara las dos líneas base:

```bash
mbse baseline diff v1.0.0 v1.1.0
```

Debe mostrar cambios en:

- `requirements/REQ-003.yaml`
- `src/thermostat/controller.py`
- La prueba nueva y las pruebas de frontera actualizadas
- La fila RTM de REQ-003

Genera changelog, métricas y el informe agregado:

```bash
mbse changelog --version v1.1.0 --output build/reports/changelog.md
mbse metrics
mbse report
```

Evidencia esperada:

- `build/reports/baseline_diff.json` y `.md`
- `build/reports/changelog.md`
- `build/reports/metrics.json`
- `build/reports/summary.json` y `.md`
- `status: pass` en la salida de `mbse report`

## 9. Demos negativos

### 9.1 Requisito ambiguo

```bash
cat > requirements/REQ-014.yaml <<'YAML'
id: REQ-014
title: "Fast response"
text: "The system shall respond quickly."
type: performance
priority: medium
owner: team-performance
verification: test
status: approved
rationale: "Demo-only ambiguous requirement."
YAML

mbse validate all
```

Debe fallar con `RQ-003` (término ambiguo) y `RQ-004` (requisito de rendimiento sin valor medible).

```bash
rm requirements/REQ-014.yaml
```

### 9.2 Requisito sin modelo ni prueba

```bash
cat > requirements/REQ-015.yaml <<'YAML'
id: REQ-015
title: "Heartbeat signal"
text: "The system shall emit a heartbeat every 10 seconds."
type: functional
priority: low
owner: team-control
verification: test
status: approved
rationale: "Demo-only requirement without a model allocation or test."
YAML

mbse trace check
```

Debe fallar con `TRC-001` (sin elemento del modelo que lo satisfaga) y `TRC-003` (requisito aprobado con verificación por prueba, pero sin prueba).

```bash
rm requirements/REQ-015.yaml
```

### 9.3 Secreto falso

Construye la clave en tiempo de ejecución para que la propia guía no sea detectada como secreto:

```bash
FAKE_KEY="AKIA$(printf 'IOSFODNN7EXAMPLE')"
printf 'aws_access_key_id = "%s"\n' "$FAKE_KEY" > demo-secrets.txt
```

Ejecuta solo la etapa de escaneo de secretos:

```bash
python - <<'PY'
from pathlib import Path

from mbse.security import scan_secrets

result = scan_secrets(Path("."))
print(f"gitleaks: {result.status} ({len(result.findings)} finding(s))")
for finding in result.findings:
    print(f"{finding.path}:{finding.line}: {finding.rule} {finding.severity}: {finding.message}")
raise SystemExit(1 if result.status == "failed" else 0)
PY
```

Debe salir con código distinto de cero y mostrar `gitleaks: failed` (o el fallback `SEC-SECRET-AWS`).

```bash
rm demo-secrets.txt
```

### 9.4 Dependencia vulnerable

```bash
printf 'pyyaml==5.3\n' > demo-cve-requirements.txt
pip-audit -r demo-cve-requirements.txt --no-deps
rm demo-cve-requirements.txt
```

Debe reportar una vulnerabilidad de PyYAML (`PYSEC`/`CVE`). Si no hay red o base de datos de avisos, se considera un `SKIP`, no un fallo de la demo.

## 10. Resumen final

Muestra los artefactos afectados del último informe de impacto:

```bash
python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("build/reports/impact.json").read_text(encoding="utf-8"))
print(f"base: {report.get('base')}")
print(f"head: {report.get('head')}")
print(f"risk: {report.get('risk', {}).get('level', 'unknown')}")
for bucket in ("directly_changed", "impacted", "needs_review", "needs_retest"):
    entries = report.get("artifacts", {}).get(bucket, [])
    print(f"{bucket}: {len(entries)}")
    for entry in entries:
        print(f"  - {entry.get('type')} {entry.get('id')}")
PY
```

## Limpieza

Borra la copia temporal:

```bash
cd /
rm -rf "$DEMO"
```

## Qué demuestra

1. Un cambio de requisito se puede versionar y validar como código.
2. El digital thread detecta pruebas obsoletas (`stale`) y relaciones afectadas.
3. El análisis de impacto permite ejecutar solo las pruebas necesarias.
4. Un fallo queda asociado a REQ-003.
5. El arreglo limpia la staleness y vuelve a dejar todo en verde.
6. Las líneas base permiten comparar versiones y generar changelog, métricas e informes.
7. Los gates rechazan requisitos ambiguos, trazabilidad incompleta, secretos y dependencias vulnerables.
