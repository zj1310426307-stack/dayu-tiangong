"""Run the reviewed real-MASCARET suite and emit auditable JSON evidence."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from math import isfinite
from pathlib import Path
from shutil import copy2
from typing import Any

from model.hydraulic_1d import Hydraulic1DExecutionContext, evaluate_hydraulic_benchmark
from model.hydraulic_1d.mascaret import MascaretEngine, MascaretRuntimeConfig
from model.hydraulic_1d.mascaret.workspace import find_attempt_workspaces
from tests.benchmark.hydraulic_1d.acceptance import (
    ACCEPTANCE_MANIFEST,
    assert_case_acceptance,
)
from tests.benchmark.hydraulic_1d.cases import ALL_BENCHMARKS


def _digest(path: Path) -> str:
    """Hash one retained native result without loading it all into memory."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(
    name: str,
    *,
    expected: float,
    actual: float,
    tolerance: float,
    operator: str,
) -> dict[str, Any]:
    """Create one stable expected/actual/error/tolerance acceptance record."""

    if operator == "<=":
        passed = actual <= expected + tolerance
    elif operator == ">=":
        passed = actual + tolerance >= expected
    elif operator == "==":
        passed = abs(actual - expected) <= tolerance
    else:  # pragma: no cover - the local registry is closed.
        raise ValueError(f"unsupported acceptance operator: {operator}")
    absolute_error = abs(actual - expected)
    scale = max(abs(expected), 1e-15)
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "absolute_error": absolute_error,
        "relative_error": absolute_error / scale,
        "tolerance": tolerance,
        "operator": operator,
        "passed": passed,
    }


def _rows(result) -> dict[str, list]:
    """Group unified records by authoritative section identity."""

    grouped: dict[str, list] = {}
    for row in result.records:
        grouped.setdefault(row.cross_section_id, []).append(row)
    for values in grouped.values():
        values.sort(key=lambda item: float(item.timestamp))
    return grouped


def _case_checks(case, result, metrics, comparison_results) -> list[dict[str, Any]]:
    """Translate the human-reviewed manifest into machine-verifiable evidence."""

    case_id = case.benchmark_id
    manifest = ACCEPTANCE_MANIFEST.get(case_id, {})
    checks = [
        _check(
            "runtime_seconds_positive",
            expected=0.0,
            actual=metrics.runtime,
            tolerance=0.0,
            operator=">=",
        ),
        _check(
            "mass_balance_relative_residual",
            expected=0.0,
            actual=metrics.mass_balance_error,
            tolerance=float(
                ACCEPTANCE_MANIFEST["global"][
                    "mass_balance_max_relative_residual"
                ]["tolerance"]
            ),
            operator="==",
        ),
    ]
    if case_id == "benchmark-01-uniform-rectangular":
        expected_states = {
            item.cross_section_id: item
            for item in case.model.initial_condition.by_section
        }
        for section_id, values in _rows(result).items():
            final = values[-1]
            expected = expected_states[section_id]
            checks.extend(
                (
                    _check(
                        f"{section_id}.discharge_m3s",
                        expected=expected.discharge_m3s,
                        actual=final.discharge_m3s,
                        tolerance=max(
                            float(manifest["discharge_absolute_m3s"]["tolerance"]),
                            abs(expected.discharge_m3s)
                            * float(manifest["discharge_relative"]["tolerance"]),
                        ),
                        operator="==",
                    ),
                    _check(
                        f"{section_id}.water_level_m",
                        expected=expected.water_level_m,
                        actual=final.water_level_m,
                        tolerance=max(
                            float(manifest["water_level_absolute_m"]["tolerance"]),
                            abs(expected.water_level_m)
                            * float(manifest["water_level_relative"]["tolerance"]),
                        ),
                        operator="==",
                    ),
                    _check(
                        f"{section_id}.velocity_m_s",
                        expected=float(case.reference_velocity_m_s),
                        actual=final.velocity_m_s,
                        tolerance=max(
                            float(manifest["velocity_absolute_ms"]["tolerance"]),
                            abs(float(case.reference_velocity_m_s))
                            * float(manifest["velocity_relative"]["tolerance"]),
                        ),
                        operator="==",
                    ),
                )
            )
    elif case_id == "benchmark-02-roughness-sensitivity":
        monitor_id = min(case.model.cross_sections, key=lambda item: item.chainage_m).id
        states = [_rows(item)[monitor_id][-1] for item in (result, *comparison_results)]
        for index, (lower, higher) in enumerate(zip(states, states[1:]), start=1):
            checks.extend(
                (
                    _check(
                        f"n{index}_to_n{index + 1}.stage_rise_m",
                        expected=float(manifest["minimum_stage_rise_m"]["tolerance"]),
                        actual=higher.water_level_m - lower.water_level_m,
                        tolerance=0.0,
                        operator=">=",
                    ),
                    _check(
                        f"n{index}_to_n{index + 1}.velocity_drop_m_s",
                        expected=float(
                            manifest["minimum_velocity_drop_ms"]["tolerance"]
                        ),
                        actual=lower.velocity_m_s - higher.velocity_m_s,
                        tolerance=0.0,
                        operator=">=",
                    ),
                )
            )
    elif case_id == "benchmark-03-flood-hydrograph":
        sections = sorted(case.model.cross_sections, key=lambda item: item.chainage_m)
        values = _rows(result)[sections[-2].id]
        baseline = values[0]
        peak_q = max(values, key=lambda item: item.discharge_m3s)
        peak_h = max(values, key=lambda item: item.water_level_m)
        upstream = next(
            item for item in case.model.boundaries if item.location == "upstream"
        )
        input_peak = max(upstream.series, key=lambda item: item.value)
        checks.extend(
            (
                _check(
                    "downstream_peak_q_rise_m3s",
                    expected=float(manifest["minimum_peak_q_rise_m3s"]["tolerance"]),
                    actual=peak_q.discharge_m3s - baseline.discharge_m3s,
                    tolerance=0.0,
                    operator=">=",
                ),
                _check(
                    "downstream_peak_h_rise_m",
                    expected=float(manifest["minimum_peak_h_rise_m"]["tolerance"]),
                    actual=peak_h.water_level_m - baseline.water_level_m,
                    tolerance=0.0,
                    operator=">=",
                ),
                _check(
                    "peak_q_arrival_time_s",
                    expected=float(
                        input_peak.time_seconds
                        + case.model.settings.output_interval_seconds
                    ),
                    actual=float(peak_q.timestamp),
                    tolerance=0.0,
                    operator=">=",
                ),
                _check(
                    "downstream_peak_q_m3s",
                    expected=float(input_peak.value),
                    actual=peak_q.discharge_m3s,
                    tolerance=float(input_peak.value)
                    * float(manifest["peak_q_overshoot_relative"]["tolerance"]),
                    operator="<=",
                ),
            )
        )
    elif case_id == "benchmark-04-natural-sections":
        expected = {item.id: item.chainage_m for item in case.model.cross_sections}
        observed = _rows(result)
        checks.append(
            _check(
                "section_count",
                expected=float(len(expected)),
                actual=float(len(observed)),
                tolerance=0.0,
                operator="==",
            )
        )
        checks.append(
            _check(
                "maximum_chainage_error_m",
                expected=0.0,
                actual=max(
                    abs(row.chainage_m - expected[row.cross_section_id])
                    for row in result.records
                ),
                tolerance=1e-6,
                operator="==",
            )
        )
    elif case_id == "benchmark-05-boundary-series":
        upstream = next(
            item for item in case.model.boundaries if item.location == "upstream"
        )
        downstream = next(
            item for item in case.model.boundaries if item.location == "downstream"
        )
        checks.extend(
            (
                _check(
                    "boundary_q_rmse_m3s",
                    expected=0.0,
                    actual=metrics.discharge_error,
                    tolerance=max(
                        float(manifest["discharge_absolute_m3s"]["tolerance"]),
                        max(abs(item.value) for item in upstream.series)
                        * float(manifest["discharge_relative"]["tolerance"]),
                    ),
                    operator="==",
                ),
                _check(
                    "boundary_h_rmse_m",
                    expected=0.0,
                    actual=metrics.water_level_error,
                    tolerance=max(
                        float(manifest["water_level_absolute_m"]["tolerance"]),
                        max(abs(item.value) for item in downstream.series)
                        * float(manifest["water_level_relative"]["tolerance"]),
                    ),
                    operator="==",
                ),
            )
        )
    if not all(isfinite(float(item["actual"])) for item in checks):
        raise ValueError(f"{case_id} produced a non-finite acceptance value")
    return checks


def _snapshot_native(
    workspace_root: Path, job_id: str, destination: Path
) -> dict[str, Any]:
    """Copy the exact retained Opthyca output into the CI evidence directory."""

    matches = find_attempt_workspaces(workspace_root, job_id=job_id)
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one retained workspace for {job_id}, found {len(matches)}"
        )
    source = matches[0] / "results.opt"
    if not source.is_file():
        raise RuntimeError(f"retained native result is missing for {job_id}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, destination)
    return {
        "file": destination.name,
        "sha256": _digest(destination),
        "bytes": destination.stat().st_size,
    }


def main() -> int:
    """Execute all reviewed cases and return nonzero if any check fails."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    workspace_root = args.workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    engine = MascaretEngine(MascaretRuntimeConfig.from_environment())
    available, detail = engine.availability()
    if not available:
        raise RuntimeError(detail)
    cases: list[dict[str, Any]] = []
    for case_factory in ALL_BENCHMARKS:
        case = case_factory()
        job_id = case.benchmark_id
        result = engine.run(
            case.model,
            Hydraulic1DExecutionContext(job_id=job_id, workspace_root=workspace_root),
        )
        metrics = evaluate_hydraulic_benchmark(
            case.model, result, reference_velocity_m_s=case.reference_velocity_m_s
        )
        comparison_results = []
        comparison_metrics = []
        native = [
            _snapshot_native(
                workspace_root, job_id, output.parent / "native" / f"{job_id}.opt"
            )
        ]
        for index, comparison_model in enumerate(case.comparison_models, start=1):
            comparison_job = f"{job_id}-comparison-{index}"
            comparison_result = engine.run(
                comparison_model,
                Hydraulic1DExecutionContext(
                    job_id=comparison_job, workspace_root=workspace_root
                ),
            )
            comparison_results.append(comparison_result)
            comparison_metrics.append(
                evaluate_hydraulic_benchmark(comparison_model, comparison_result)
            )
            native.append(
                _snapshot_native(
                    workspace_root,
                    comparison_job,
                    output.parent / "native" / f"{comparison_job}.opt",
                )
            )
        assert_case_acceptance(
            case,
            result,
            metrics,
            comparison_results=tuple(comparison_results),
            comparison_metrics=tuple(comparison_metrics),
        )
        checks = _case_checks(case, result, metrics, tuple(comparison_results))
        cases.append(
            {
                "case_id": case.benchmark_id,
                "status": "PASS" if all(item["passed"] for item in checks) else "FAIL",
                "metrics": metrics.to_dict(),
                "checks": checks,
                "native_results": native,
                "runtime_provenance": result.diagnostics["runtime_provenance"],
            }
        )
    report = {
        "schema_version": "dayu.mascaret-acceptance-report.v1",
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "FAIL",
        "runtime_detail": detail,
        "acceptance_manifest": ACCEPTANCE_MANIFEST,
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
