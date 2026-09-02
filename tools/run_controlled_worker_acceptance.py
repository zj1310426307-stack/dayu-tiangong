"""Submit one real controlled D-Flow job through Redis/Celery and verify persistence."""

from __future__ import annotations

from datetime import UTC, datetime
import json
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
from model.hydraulic_1d.registry import (
    CONTROLLED_HYDRAULIC_1D_RUN_SCHEMA,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    DFLOW_FM_SOLVER_ID,
    DFLOW_FM_UPSTREAM_COMMIT,
    controlled_task_engine_provenance,
)
from model.provenance import snapshot_hash
from tools.run_controlled_engine_acceptance import build_run


def main() -> int:
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
            (branch, rows) for branch, rows in by_branch.items() if len(rows) >= 3
        )
        controlled = build_run(
            database_branch_id=str(branch_id),
            database_section_ids=tuple(str(item.id) for item in sections[:3]),
        )
        frozen = controlled.model_dump(mode="json")
        plan = DispatchPlan(
            dataset_version_id=case.dataset_version_id,
            simulation_case_id=case.id,
            name=f"06R worker acceptance {datetime.now(UTC).isoformat()}",
            version=1,
            status="frozen",
            snapshot_target="hydraulic_v3",
            description="temporary synthetic 06R worker acceptance",
            duration_seconds=600.0,
            evaluation_config={},
            storage_level="key_sections",
            created_by="06r-acceptance",
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
        session.commit()
        task_id, run_id, plan_id = task.id, dispatch_run.id, plan.id
        delivery = run_hydraulic_task.apply_async(
            args=[task_id],
            queue=HYDRAULIC_1D_QUEUE,
        )
        task.queue_job_id = str(delivery.id)
        dispatch_run.queue_job_id = str(delivery.id)
        session.commit()

    deadline = monotonic() + 120.0
    while monotonic() < deadline:
        with SessionLocal() as session:
            task = session.get(SimulationTask, task_id)
            if task is not None and task.status in {"success", "failed", "cancelled"}:
                break
        sleep(0.5)
    else:
        raise RuntimeError("controlled worker acceptance timed out")

    with SessionLocal() as session:
        task = session.get(SimulationTask, task_id)
        dispatch_run = session.get(DispatchRun, run_id)
        assert task is not None and dispatch_run is not None
        counts = {
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
            "control_events": session.scalar(
                select(func.count()).select_from(DispatchEvent).where(
                    DispatchEvent.run_id == run_id
                )
            ),
        }
        output = {
            "status": "PASS" if task.status == "success" else "FAIL",
            "task_status": task.status,
            "run_status": dispatch_run.status,
            "execution_attempt_count": task.execution_attempt_count,
            "result_counts": counts,
            "error_message": task.error_message,
            "evidence_class": task.evidence_class,
        }
        session.execute(delete(DispatchEvent).where(DispatchEvent.run_id == run_id))
        session.delete(dispatch_run)
        session.flush()
        session.delete(task)
        session.flush()
        session.delete(session.get(DispatchPlan, plan_id))
        session.commit()
    print(json.dumps(output, indent=2, sort_keys=True))
    if output["status"] != "PASS" or not all(counts.values()):
        raise RuntimeError("controlled worker did not persist the complete result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
