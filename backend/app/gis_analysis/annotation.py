"""Read versioned labels and derive time-varying text without mutating source annotations."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.gis import service as gis_service
from app.gis.models import DatasetVersion, DispatchEvent, MapAnnotation
from app.gis_analysis.schemas import AnnotationCollection, AnnotationRecord


def list_annotations(
    session: Session,
    dataset_version_id: int,
    scale_denominator: float,
    bbox: tuple[float, float, float, float] | None,
    annotation_types: list[str] | None,
    limit: int,
    offset: int,
    time_seconds: float,
    task_id: int | None,
    dispatch_run_id: int | None,
) -> AnnotationCollection:
    """Return labels visible at one scale and decorate them with one atomic simulation frame."""

    if session.get(DatasetVersion, dataset_version_id) is None:
        raise gis_service.GISVersionError("数据版本不存在")

    conditions = [
        MapAnnotation.dataset_version_id == dataset_version_id,
        MapAnnotation.visible_scale_min <= scale_denominator,
        MapAnnotation.visible_scale_max >= scale_denominator,
    ]
    if bbox is not None:
        conditions.append(
            func.ST_Intersects(MapAnnotation.geometry, func.ST_MakeEnvelope(*bbox, 4490))
        )
    if annotation_types:
        conditions.append(MapAnnotation.annotation_type.in_(annotation_types))
    total = session.scalar(select(func.count(MapAnnotation.id)).where(*conditions)) or 0
    rows = session.scalars(
        select(MapAnnotation).where(*conditions).order_by(MapAnnotation.id).limit(limit).offset(offset)
    ).all()

    frame = gis_service.get_interaction_frame(
        session, dataset_version_id, time_seconds, task_id, dispatch_run_id
    ) if task_id or dispatch_run_id else None
    water_by_section = {sample.section_id: sample for sample in frame.water_samples} if frame else {}
    structure_by_key = {
        (sample.structure_type, sample.structure_id): sample for sample in frame.structure_samples
    } if frame else {}

    records: list[AnnotationRecord] = []
    for row in rows:
        lines: list[str] = []
        source = "static"
        if row.related_type == "cross_section" and row.related_id in water_by_section:
            sample = water_by_section[row.related_id]
            lines = [f"水位 {sample.water_level:.2f} m", f"流速 {sample.velocity:.2f} m/s"]
            source = "simulation"
        elif (row.related_type, row.related_id) in structure_by_key:
            sample = structure_by_key[(row.related_type, row.related_id)]
            if sample.structure_type == "gate":
                percent = (sample.actual_value or 0) * 100
                lines = [f"开度 {percent:.0f}%", f"流量 {sample.flow:.1f} m³/s"]
            else:
                lines = [
                    "运行" if sample.state == "running" else "停止",
                    f"流量 {sample.flow:.1f} m³/s",
                    f"功率 {(sample.power_kw or 0):.1f} kW",
                ]
            source = "dispatch"
        records.append(_record(row, lines, source))

    if dispatch_run_id:
        records.extend(
            _event_records(session, dataset_version_id, dispatch_run_id, time_seconds, limit - len(records))
        )
    return AnnotationCollection(
        items=records[:limit], total=total, limit=limit, offset=offset,
        dataset_version_id=dataset_version_id, scale_denominator=scale_denominator,
    )


def _record(row: MapAnnotation, lines: list[str], source: str) -> AnnotationRecord:
    """Serialize one annotation while keeping dynamic lines separate from persistent text."""

    return AnnotationRecord(
        id=row.id, dataset_version_id=row.dataset_version_id,
        annotation_type=row.annotation_type, name=row.name, text=row.text,
        description=row.description, longitude=row.longitude, latitude=row.latitude,
        rotation=row.rotation, font_size=row.font_size, color=row.color,
        visible_scale_min=row.visible_scale_min, visible_scale_max=row.visible_scale_max,
        related_type=row.related_type, related_id=row.related_id,
        display_text="\n".join([row.text, *lines]), dynamic_lines=lines,
        dynamic_source=source, created_time=row.created_time,
    )


def _event_records(
    session: Session, dataset_version_id: int, run_id: int, time_seconds: float, remaining: int
) -> list[AnnotationRecord]:
    """Build transient event labels at the related facility location for the selected time."""

    if remaining <= 0:
        return []
    # Event labels remain transient; reserve a high positive namespace required by the API schema.
    events = session.scalars(
        select(DispatchEvent).where(
            DispatchEvent.run_id == run_id,
            DispatchEvent.time_seconds <= time_seconds,
        ).order_by(DispatchEvent.time_seconds.desc(), DispatchEvent.id.desc()).limit(min(remaining, 20))
    ).all()
    from app.gis.models import Gate, Pump

    records: list[AnnotationRecord] = []
    for event in events:
        model = Gate if event.structure_type == "gate" else Pump
        asset = session.get(model, event.structure_id)
        if asset is None or asset.dataset_version_id != dataset_version_id:
            continue
        longitude, latitude = session.execute(
            select(func.ST_X(model.geometry), func.ST_Y(model.geometry)).where(model.id == asset.id)
        ).one()
        records.append(AnnotationRecord(
            id=1_000_000_000 + event.id, dataset_version_id=dataset_version_id,
            annotation_type="dispatch_event", name=f"dispatch-event-{event.id}",
            text=f"{event.time_seconds:.0f}s {asset.name}", description=event.reason,
            longitude=longitude, latitude=latitude, rotation=0, font_size=13,
            color="#FFC85C", visible_scale_min=0, visible_scale_max=120000,
            related_type="dispatch_event", related_id=event.id,
            display_text=f"{event.time_seconds:.0f}s {asset.name}\n{event.outcome} · {event.reason or '调度动作'}",
            dynamic_lines=[event.outcome, event.reason or "调度动作"], dynamic_source="dispatch",
            created_time=event.created_time,
        ))
    return records
