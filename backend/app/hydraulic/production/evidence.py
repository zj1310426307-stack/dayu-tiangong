"""Recompute formal metrics from persisted observations and immutable task results."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import HydraulicTaskSectionResult, SimulationTask
from app.hydraulic.models import (
    HydraulicCrossSection,
    HydraulicCrossSectionProfile,
    HydraulicObservationSeries,
)
from app.hydraulic.production.contracts import (
    HydraulicMetrics,
    ProductionSeries,
    ProductionSeriesPoint,
)
from app.hydraulic.production.metrics import align_and_score
from app.hydraulic.production.records import MetricEvidenceRequest


def compute_persisted_task_metrics(
    session: Session,
    task: SimulationTask,
    evidence: list[MetricEvidenceRequest],
) -> list[HydraulicMetrics]:
    """Score one successful task against explicitly mapped persisted observations."""

    if task.status != "success":
        raise ValueError("Metric evidence requires a successful immutable task")
    metrics: list[HydraulicMetrics] = []
    variables: set[str] = set()
    for mapping in evidence:
        observation = session.get(HydraulicObservationSeries, mapping.observation_series_id)
        section = session.get(HydraulicCrossSection, mapping.cross_section_id)
        if (
            observation is None
            or section is None
            or observation.dataset_version_id != task.dataset_version_id
            or section.dataset_version_id != task.dataset_version_id
        ):
            raise ValueError("Metric evidence is outside the task Dataset Version")
        if section.branch_id != observation.branch_id:
            raise ValueError("Observation and Cross Section must belong to the same Branch")
        distance = abs(float(section.chainage) - float(observation.chainage_m))
        if distance > mapping.maximum_chainage_distance_m:
            raise ValueError("Observation-to-Section chainage distance exceeds the reviewed limit")
        if observation.variable in variables:
            raise ValueError("Formal evidence supports one mapped series per hydraulic variable")
        variables.add(observation.variable)
        if observation.variable == "water_level":
            profile = session.scalar(
                select(HydraulicCrossSectionProfile).where(
                    HydraulicCrossSectionProfile.cross_section_id == section.id,
                    HydraulicCrossSectionProfile.dataset_version_id == task.dataset_version_id,
                    HydraulicCrossSectionProfile.is_active.is_(True),
                )
            )
            if profile is None or profile.vertical_datum != observation.vertical_datum:
                raise ValueError("Observed and simulated water levels require the same datum")
        result_rows = session.scalars(
            select(HydraulicTaskSectionResult)
            .where(
                HydraulicTaskSectionResult.task_id == task.id,
                HydraulicTaskSectionResult.hydraulic_cross_section_id == section.id,
            )
            .order_by(HydraulicTaskSectionResult.time_seconds)
        ).all()
        if not result_rows:
            raise ValueError("Mapped Cross Section has no persisted task results")
        observed = ProductionSeries(
            series_id=observation.series_code,
            variable=observation.variable,
            unit=observation.unit,
            samples=[
                ProductionSeriesPoint.model_validate(sample)
                for sample in observation.samples_json
            ],
            source=(
                f"{observation.source}; file={observation.source_filename}; "
                f"sha256={observation.source_sha256}"
            ),
            branch_id=str(observation.branch_id),
            chainage_m=observation.chainage_m,
            station_id=observation.station_id,
            vertical_datum=observation.vertical_datum,
            time_basis=observation.time_basis,
            timezone=observation.timezone,
        )
        value_field = {
            "water_level": "water_level_m",
            "discharge": "flow_m3s",
        }[observation.variable]
        simulated = ProductionSeries(
            series_id=f"task-{task.id}-section-{section.id}-{observation.variable}",
            variable=observation.variable,
            unit=observation.unit,
            samples=[
                ProductionSeriesPoint(
                    time_seconds=row.time_seconds,
                    value=float(getattr(row, value_field)),
                    quality_flag="GOOD",
                )
                for row in result_rows
            ],
            source=f"simulation_task:{task.id}",
            branch_id=str(section.branch_id),
            chainage_m=section.chainage,
            station_id=observation.station_id,
            vertical_datum=observation.vertical_datum,
        )
        metrics.append(align_and_score(observed, simulated, mapping.alignment))
    return metrics


__all__ = ["compute_persisted_task_metrics"]
