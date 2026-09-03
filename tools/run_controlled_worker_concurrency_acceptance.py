"""Run Gate-only and joint Gate/Pump jobs concurrently through Celery."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from time import monotonic, sleep
from sqlalchemy import delete, func, select

from app.database.session import SessionLocal
from app.gis.models import (
    DispatchEvent,
    DispatchPlan,
    DispatchRun,
    HydraulicTaskSectionResult,
    SimulationCase,
    SimulationTask,
    StructureResult,
)
from app.hydraulic.models import HydraulicCrossSection
from app.worker.tasks import HYDRAULIC_1D_QUEUE, run_hydraulic_task
from model.hydraulic_1d.controlled import ControlledHydraulic1DRun
from model.hydraulic_1d.registry import (
    CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    DFLOW_FM_SOLVER_ID,
    DFLOW_FM_UPSTREAM_COMMIT,
    controlled_task_engine_provenance,
)
from model.provenance import snapshot_hash
from tools.run_controlled_engine_acceptance import build_run as build_gate_run
from tools.run_controlled_pump_engine_acceptance import build_run as build_joint_run


def _create_job(
    session: object,
    *,
    case: SimulationCase,
    label: str,
    controlled: ControlledHydraulic1DRun,
) -> tuple[int, int, int]:
    frozen = controlled.model_dump(mode="json")
    plan = DispatchPlan(
        dataset_version_id=case.dataset_version_id,
        simulation_case_id=case.id,
        name=f"Phase 07 {label} concurrency {datetime.now(UTC).isoformat()}",
        version=1,
        status="frozen",
        snapshot_target="hydraulic_v3",
        description="temporary synthetic Phase 07 worker concurrency acceptance",
        duration_seconds=600.0,
        evaluation_config={},
        storage_level="key_sections",
        created_by="phase07-acceptance",
    )
    session.add(plan)
    session.flush()
    task = SimulationTask(
        case_id=case.id,
        dataset_version_id=case.dataset_version_id,
        status="queued",
        progress=0,
        config={"runtime_mode": "container", "synthetic_fixture": True},
        task_kind="controlled_hydraulic_preview",
        evidence_class="SYNTHETIC_NUMERICAL_ONLY",
        input_schema_version=CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
        input_snapshot=frozen,
        input_snapshot_hash=snapshot_hash(frozen),
        engine_version=DFLOW_FM_ENGINE_VERSION,
        engine_commit=DFLOW_FM_UPSTREAM_COMMIT,
        solver_build_id=DFLOW_FM_SOLVER_ID,
        build_mode="development",
        build_verified=True,
        execution_phase="queued",
        artifact_status="none",
        queued_time=datetime.now(UTC),
        delivery_attempt_count=1,
        last_delivery_time=datetime.now(UTC),
        **controlled_task_engine_provenance(),
    )
    session.add(task)
    session.flush()
    dispatch_run = DispatchRun(
        plan_id=plan.id,
        controlled_task_id=task.id,
        status="queued",
        run_mode="hydraulic_preview",
        evidence_class="SYNTHETIC_NUMERICAL_ONLY",
        engine_id=DFLOW_FM_ENGINE_ID,
        control_runtime="d-rtc/fbc",
        result_contract={},
    )
    session.add(dispatch_run)
    session.flush()
    return task.id, dispatch_run.id, plan.id


def _counts(session: object, task_id: int, run_id: int) -> dict[str, object]:
    type_counts = dict(
        session.execute(
            select(StructureResult.structure_type, func.count())
            .where(StructureResult.task_id == task_id)
            .group_by(StructureResult.structure_type)
        ).all()
    )
    pump_audit_rows = session.scalar(
        select(func.count()).select_from(StructureResult).where(
            StructureResult.task_id == task_id,
            StructureResult.structure_type == "pump",
            StructureResult.native_applied_capacity.is_not(None),
            StructureResult.actual_discharge.is_not(None),
            StructureResult.intake_water_level.is_not(None),
            StructureResult.outlet_water_level.is_not(None),
            StructureResult.pump_actual_stage.is_(None),
        )
    )
    return {
        "hydraulic_records": session.scalar(
            select(func.count()).select_from(HydraulicTaskSectionResult).where(
                HydraulicTaskSectionResult.task_id == task_id
            )
        ),
        "structure_records": session.scalar(
            select(func.count()).select_from(StructureResult).where(
                StructureResult.task_id == task_id
            )
        ),
        "structure_type_counts": type_counts,
        "pump_native_audit_records": pump_audit_rows,
        "control_events": session.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.run_id == run_id
            )
        ),
    }


def _cleanup(session: object, jobs: list[tuple[int, int, int]]) -> None:
    for task_id, run_id, plan_id in jobs:
        session.execute(delete(DispatchEvent).where(DispatchEvent.run_id == run_id))
        dispatch_run = session.get(DispatchRun, run_id)
        if dispatch_run is not None:
            session.delete(dispatch_run)
            session.flush()
        task = session.get(SimulationTask, task_id)
        if task is not None:
            session.delete(task)
            session.flush()
        plan = session.get(DispatchPlan, plan_id)
        if plan is not None:
            session.delete(plan)
            session.flush()
    session.commit()


def _wait_for_jobs(
    jobs: list[tuple[int, int, int]], *, timeout_seconds: float
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        with SessionLocal() as session:
            statuses = [session.get(SimulationTask, item[0]).status for item in jobs]
            if all(status in {"success", "failed", "cancelled"} for status in statuses):
                return
        sleep(0.5)
    raise RuntimeError("controlled worker concurrency acceptance timed out")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()

    jobs: list[tuple[int, int, int]] = []
    with SessionLocal() as session:
        case = session.scalar(select(SimulationCase).order_by(SimulationCase.id))
        if case is None:
            raise RuntimeError("the local synthetic acceptance database has no case")
        section_rows = list(
            session.scalars(
                select(HydraulicCrossSection)
                .where(HydraulicCrossSection.dataset_version_id == case.dataset_version_id)
                .order_by(HydraulicCrossSection.branch_id, HydraulicCrossSection.chainage)
            ).all()
        )
        by_branch: dict[int, list[HydraulicCrossSection]] = {}
        for section in section_rows:
            by_branch.setdefault(section.branch_id, []).append(section)
        branch_id, sections = next(
            (branch, rows) for branch, rows in by_branch.items() if len(rows) >= 6
        )
        branch = str(branch_id)
        gate = build_gate_run(
            database_branch_id=branch,
            database_section_ids=tuple(str(item.id) for item in sections[:3]),
        )
        joint = build_joint_run(
            joint=True,
            database_branch_id=branch,
            database_section_ids=tuple(str(item.id) for item in sections[:6]),
        )
        jobs = [
            _create_job(session, case=case, label="Gate-only", controlled=gate),
            _create_job(session, case=case, label="Gate-Pump", controlled=joint),
        ]
        session.commit()
        for task_id, run_id, _ in jobs:
            delivery = run_hydraulic_task.apply_async(
                args=[task_id],
                queue=HYDRAULIC_1D_QUEUE,
            )
            session.get(SimulationTask, task_id).queue_job_id = str(delivery.id)
            session.get(DispatchRun, run_id).queue_job_id = str(delivery.id)
        session.commit()

    try:
        _wait_for_jobs(jobs, timeout_seconds=args.timeout_seconds)
        with SessionLocal() as session:
            payload_jobs: list[dict[str, object]] = []
            for label, (task_id, run_id, _) in zip(
                ("gate-only", "gate-pump"), jobs, strict=True
            ):
                task = session.get(SimulationTask, task_id)
                dispatch_run = session.get(DispatchRun, run_id)
                if task is None or dispatch_run is None:
                    raise RuntimeError("acceptance job ownership record is missing")
                payload_jobs.append(
                    {
                        "label": label,
                        "task_id": task_id,
                        "task_status": task.status,
                        "run_status": dispatch_run.status,
                        "worker_id": task.worker_id,
                        "execution_attempt_count": task.execution_attempt_count,
                        "result_counts": _counts(session, task_id, run_id),
                        "result_contract": dispatch_run.result_contract,
                        "error_message": task.error_message,
                    }
                )
            workspace_dirs = sorted(
                str(path.relative_to(args.workspace_root))
                for path in args.workspace_root.glob("*/*")
                if path.is_dir()
            )
            payload = {
                "schema_version": "dayu.phase07-worker-concurrency-acceptance.v1",
                "status": "PASS",
                "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
                "jobs": payload_jobs,
                "workspace_directories": workspace_dirs,
                "database_isolation": "task_id/run_id foreign keys and unique constraints",
                "real_engineering_validation": False,
            }
            for job in payload_jobs:
                counts = job["result_counts"]
                if job["task_status"] != "success" or job["run_status"] != "success":
                    payload["status"] = "FAIL"
                if not counts["hydraulic_records"] or not counts["structure_records"]:
                    payload["status"] = "FAIL"
            gate_types = payload_jobs[0]["result_counts"]["structure_type_counts"]
            joint_types = payload_jobs[1]["result_counts"]["structure_type_counts"]
            if set(gate_types) != {"gate"} or set(joint_types) != {"gate", "pump"}:
                payload["status"] = "FAIL"
            if not payload_jobs[1]["result_counts"]["pump_native_audit_records"]:
                payload["status"] = "FAIL"
            if len(workspace_dirs) != 2 or len(set(workspace_dirs)) != 2:
                payload["status"] = "FAIL"
            serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(serialized, encoding="utf-8")
            print(serialized, end="")
            if payload["status"] != "PASS":
                raise RuntimeError("controlled worker concurrency acceptance failed")
    finally:
        with SessionLocal() as session:
            _cleanup(session, jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
