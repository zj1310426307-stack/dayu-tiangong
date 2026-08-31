"""Prevent the retired custom numerical route from re-entering production."""

from __future__ import annotations

import ast
from pathlib import Path

from app.main import app


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PATHS = (
    "model/engine.py",
    "model/hydraulic_model.py",
    "model/solver/saint_venant.py",
    "model/solver/finite_volume",
    "model/network/solver.py",
    "model/adapters/v4.py",
    "model/adapters/v4_lite.py",
    "tools/collect_d3a_shipping_science.py",
    "tools/diagnose_model02_cross_platform.py",
    "examples/hydraulic/saint-venant-mvp",
    "examples/hydraulic/gate-pump-strong-coupling",
)
FORBIDDEN_MODULE_PREFIXES = (
    "model.engine",
    "model.hydraulic_model",
    "model.solver",
    "model.network.solver",
    "model.adapters",
    "model.api.v4",
    "model.result.mvp",
)


def _imports(path: Path) -> list[str]:
    """Return every absolute import target from one production Python file."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
    return targets


def test_retired_custom_solver_files_are_absent() -> None:
    """The default checkout must not contain the old production numerical core."""

    present = [
        item
        for item in FORBIDDEN_PATHS
        if (ROOT / item).is_file()
        or ((ROOT / item).is_dir() and any((ROOT / item).rglob("*.py")))
    ]
    assert present == []


def test_production_python_cannot_import_retired_solver_modules() -> None:
    """Scan import syntax rather than relying on one application startup path."""

    violations: list[str] = []
    paths = [
        *ROOT.glob("backend/app/**/*.py"),
        *ROOT.glob("model/**/*.py"),
        *ROOT.glob("tools/**/*.py"),
        *ROOT.glob("examples/**/*.py"),
    ]
    for path in paths:
        for target in _imports(path):
            if target.startswith(FORBIDDEN_MODULE_PREFIXES):
                violations.append(f"{path.relative_to(ROOT)} -> {target}")
    assert violations == []


def test_business_layer_cannot_import_mascaret_internals() -> None:
    """Concrete engine files remain behind the solver-neutral factory boundary."""

    violations = []
    for path in ROOT.glob("backend/app/**/*.py"):
        for target in _imports(path):
            if target.startswith("model.hydraulic_1d.mascaret"):
                violations.append(f"{path.relative_to(ROOT)} -> {target}")
    assert violations == []


def test_openapi_has_one_solver_neutral_model_surface() -> None:
    """No legacy or native-v4 route may remain in the public application."""

    paths = app.openapi()["paths"]
    assert "/api/v1/model/readiness" in paths
    assert "/api/v1/model/preview" in paths
    assert all("/model/v4/" not in path for path in paths)
    assert all("input-v3" not in path and "input-v4" not in path for path in paths)
