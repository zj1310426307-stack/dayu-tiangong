"""横断面 CRUD 与空间序列化业务服务。"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.spatial import geometry_expression, geometry_json
from app.cross_section.schemas import (
    CrossSectionCreate,
    CrossSectionListResponse,
    CrossSectionRecord,
    CrossSectionUpdate,
)
from app.gis.models import CrossSection


def _record(session: Session, section: CrossSection) -> CrossSectionRecord:
    """把 ORM 横断面转换为响应记录。"""

    return CrossSectionRecord(
        id=section.id,
        dataset_version_id=section.dataset_version_id,
        river_id=section.river_id,
        section_code=section.section_code,
        section_name=section.section_name,
        station=section.station,
        points=section.points,
        roughness=section.roughness,
        elevation_min=section.elevation_min,
        survey_date=section.survey_date,
        geometry=geometry_json(session, section.geometry),
        created_time=section.created_time,
    )


def list_cross_sections(
    session: Session,
    dataset_version_id: int | None,
    river_id: int | None,
    search: str | None,
    limit: int,
    offset: int,
) -> CrossSectionListResponse:
    """按版本、河道和关键词分页查询横断面。"""

    conditions = []
    if dataset_version_id is not None:
        conditions.append(CrossSection.dataset_version_id == dataset_version_id)
    if river_id is not None:
        conditions.append(CrossSection.river_id == river_id)
    if search:
        token = f"%{search.strip()}%"
        conditions.append(
            or_(CrossSection.section_code.ilike(token), CrossSection.section_name.ilike(token))
        )
    total = session.scalar(select(func.count(CrossSection.id)).where(*conditions)) or 0
    sections = session.scalars(
        select(CrossSection)
        .where(*conditions)
        .order_by(CrossSection.river_id, CrossSection.station)
        .limit(limit)
        .offset(offset)
    ).all()
    return CrossSectionListResponse(
        items=[_record(session, section) for section in sections],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_cross_section(session: Session, section_id: int) -> CrossSectionRecord | None:
    """按主键读取横断面。"""

    section = session.get(CrossSection, section_id)
    return _record(session, section) if section else None


def create_cross_section(session: Session, payload: CrossSectionCreate) -> CrossSectionRecord:
    """新增横断面。"""

    values = payload.model_dump(exclude={"geometry"})
    section = CrossSection(**values, geometry=geometry_expression(payload.geometry, "Point"))
    session.add(section)
    session.flush()
    return _record(session, section)


def update_cross_section(
    session: Session, section: CrossSection, payload: CrossSectionUpdate
) -> CrossSectionRecord:
    """局部更新横断面。"""

    values = payload.model_dump(exclude_unset=True)
    geometry = values.pop("geometry", None)
    for key, value in values.items():
        setattr(section, key, value)
    if geometry is not None:
        section.geometry = geometry_expression(geometry, "Point")
    session.flush()
    return _record(session, section)


def delete_cross_section(session: Session, section: CrossSection) -> None:
    """删除指定横断面。"""

    session.delete(section)
    session.flush()
