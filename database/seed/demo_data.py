"""Idempotently seed the versioned Phase 3 DEMO hydraulic dataset."""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.database.session import SessionLocal  # noqa: E402
from app.ai.service import seed_builtin_knowledge  # noqa: E402
from app.gis.models import (  # noqa: E402
    AdministrativeArea,
    BoundaryCondition,
    CrossSection,
    DatasetVersion,
    Gate,
    GISPublication,
    MapAnnotation,
    ModelParameter,
    PlaceName,
    PointOfInterest,
    Pump,
    River,
    RiverNode,
    RiverConnection,
    RiverSegment,
    Road,
    SimulationCase,
    SimulationCaseBoundary,
    WaterName,
)
from app.river.service import generate_topology  # noqa: E402
from app.gis_governance.hashing import canonical_sha256  # noqa: E402
from app.gis_governance.service import _core_content_rows  # noqa: E402


RIVER_SPECS = [
    {
        "code": "DEMO-RIVER-A",
        "name": "DEMO 主河道 A",
        "length": 58_600.0,
        "level": "main",
        "description": "DEMO DATA｜Phase 3 水动力模拟测试，不代表真实工程。",
        "coordinates": [(120.00, 30.25), (120.15, 30.28), (120.30, 30.24), (120.48, 30.30)],
        "section_count": 10,
    },
    {
        "code": "DEMO-RIVER-B",
        "name": "DEMO 支流 B",
        "length": 31_200.0,
        "level": "tributary",
        "description": "DEMO DATA｜北向测试支流。",
        "coordinates": [(120.15, 30.28), (120.22, 30.40), (120.30, 30.49)],
        "section_count": 5,
    },
    {
        "code": "DEMO-RIVER-C",
        "name": "DEMO 支流 C",
        "length": 28_400.0,
        "level": "tributary",
        "description": "DEMO DATA｜南向测试支流。",
        "coordinates": [(120.30, 30.24), (120.40, 30.12), (120.54, 30.08)],
        "section_count": 5,
    },
]

GATE_SPECS = [
    ("DEMO-GATE-001", "DEMO 闸门 01", "DEMO-RIVER-A", "节制闸", 18.0, 6.5, 140.4, 5.0, "online", 120.08, 30.264),
    ("DEMO-GATE-002", "DEMO 闸门 02", "DEMO-RIVER-A", "分洪闸", 14.0, 5.8, 97.4, 4.8, "online", 120.23, 30.258),
    ("DEMO-GATE-003", "DEMO 闸门 03", "DEMO-RIVER-A", "节制闸", 20.0, 7.2, 172.8, 5.1, "maintenance", 120.40, 30.276),
    ("DEMO-GATE-004", "DEMO 闸门 04", "DEMO-RIVER-B", "进水闸", 11.5, 5.0, 69.0, 5.6, "online", 120.22, 30.40),
    ("DEMO-GATE-005", "DEMO 闸门 05", "DEMO-RIVER-C", "退水闸", 12.0, 5.2, 74.9, 4.6, "offline", 120.45, 30.105),
]

PUMP_SPECS = [
    ("DEMO-PUMP-001", "DEMO 泵站 01", "DEMO-RIVER-A", 72.0, 6.0, 1_600.0, "online", 120.18, 30.272),
    ("DEMO-PUMP-002", "DEMO 泵站 02", "DEMO-RIVER-B", 48.0, 5.5, 1_120.0, "online", 120.26, 30.445),
    ("DEMO-PUMP-003", "DEMO 泵站 03", "DEMO-RIVER-C", 56.0, 6.2, 1_320.0, "maintenance", 120.38, 30.145),
]


def _line_wkt(coordinates: list[tuple[float, float]]) -> WKTElement:
    """Return a CGCS2000 LineString element."""

    body = ", ".join(f"{longitude} {latitude}" for longitude, latitude in coordinates)
    return WKTElement(f"LINESTRING ({body})", srid=4490)


def _point_wkt(longitude: float, latitude: float) -> WKTElement:
    """Return a CGCS2000 Point element."""

    return WKTElement(f"POINT ({longitude} {latitude})", srid=4490)


def _interpolate(
    coordinates: list[tuple[float, float]], ratio: float
) -> tuple[float, float]:
    """Interpolate a display position along a DEMO polyline."""

    segment_count = len(coordinates) - 1
    scaled = min(ratio * segment_count, segment_count - 1e-9)
    segment = int(scaled)
    local_ratio = scaled - segment
    start = coordinates[segment]
    end = coordinates[segment + 1]
    return (
        start[0] + (end[0] - start[0]) * local_ratio,
        start[1] + (end[1] - start[1]) * local_ratio,
    )


def _ensure_dataset_version(session: Any) -> DatasetVersion:
    """Return the DEMO version or create it in an empty database."""

    version = session.scalar(select(DatasetVersion).where(DatasetVersion.version == "V1.0"))
    if version is None:
        version = DatasetVersion(
            version="V1.0",
            name="2026 现状河网（DEMO）",
            description="Phase 3 DEMO DATA，不代表真实工程。",
            creator="Codex DEMO",
        )
        session.add(version)
        session.flush()
    return version


def _backfill_governance_metadata(session: Any) -> None:
    """Backfill immutable-version hashes and missing publication audit rows.

    This maintenance step deliberately updates only governance metadata.  It
    never refreshes or otherwise mutates the four frozen core business tables.
    """

    frozen_without_hash = session.scalars(
        select(DatasetVersion)
        .where(
            DatasetVersion.status.in_(("approved", "published", "retired")),
            DatasetVersion.content_hash.is_(None),
        )
        .order_by(DatasetVersion.id)
        .with_for_update()
    ).all()
    for frozen_version in frozen_without_hash:
        frozen_version.content_hash = canonical_sha256(
            _core_content_rows(session, frozen_version.id)
        )

    published_without_audit = session.scalars(
        select(DatasetVersion)
        .outerjoin(
            GISPublication,
            GISPublication.dataset_version_id == DatasetVersion.id,
        )
        .where(
            DatasetVersion.status == "published",
            GISPublication.id.is_(None),
        )
        .order_by(DatasetVersion.id)
        .with_for_update(of=DatasetVersion)
    ).all()
    for published_version in published_without_audit:
        session.add(
            GISPublication(
                dataset_version_id=published_version.id,
                publication_status="published",
                published_by="demo-seed-governance-backfill",
                published_at=(
                    published_version.published_at
                    or published_version.created_time
                    or datetime.now(UTC)
                ),
                manifest_json={
                    "legacy_backfill": True,
                    "publish_boundary": "existing public compatibility",
                },
            )
        )


def _ensure_parameter(
    session: Any,
    version_id: int,
    name: str,
    value: float,
    unit: str,
    description: str,
) -> None:
    """Insert or refresh one solver parameter without creating duplicates."""

    parameter = session.scalar(
        select(ModelParameter).where(
            ModelParameter.dataset_version_id == version_id,
            ModelParameter.parameter_type == "solver",
            ModelParameter.parameter_name == name,
        )
    )
    if parameter is None:
        parameter = ModelParameter(
            dataset_version_id=version_id,
            parameter_type="solver",
            parameter_name=name,
            value=value,
            unit=unit,
            description=description,
        )
        session.add(parameter)
    else:
        parameter.value = value
        parameter.unit = unit
        parameter.description = description


def _seed_demo_data_rows() -> dict[str, int]:
    """Populate DEMO rows or maintain governance metadata for a frozen baseline."""

    with SessionLocal.begin() as session:
        version = _ensure_dataset_version(session)
        if version.status != "draft":
            # Published/approved versions are frozen facts. Repeated container starts
            # may add governance metadata and count rows, but must never refresh
            # business fields, annotations, gazetteer data, or topology.
            _backfill_governance_metadata(session)
            session.flush()
            counts: dict[str, int] = {}
            for label, model in (
                ("dataset_versions", DatasetVersion), ("rivers", River), ("gates", Gate),
                ("pumps", Pump), ("cross_sections", CrossSection),
                ("map_annotations", MapAnnotation), ("administrative_areas", AdministrativeArea),
                ("roads", Road), ("place_names", PlaceName), ("water_names", WaterName),
                ("pois", PointOfInterest), ("river_nodes", RiverNode),
                ("simulation_cases", SimulationCase),
            ):
                counts[label] = session.scalar(select(func.count(model.id))) or 0
            return counts
        rivers_by_code: dict[str, River] = {}
        for spec in RIVER_SPECS:
            river = session.scalar(
                select(River).where(
                    River.dataset_version_id == version.id,
                    River.code == spec["code"],
                )
            )
            if river is None:
                river = River(
                    dataset_version_id=version.id,
                    code=spec["code"],
                    name=spec["name"],
                    length=spec["length"],
                    level=spec["level"],
                    status="active",
                    description=spec["description"],
                    geometry=_line_wkt(spec["coordinates"]),
                )
                session.add(river)
                session.flush()
            else:
                river.level = spec["level"]
                river.description = spec["description"]
            rivers_by_code[str(spec["code"])] = river

        for (
            code,
            name,
            river_code,
            gate_type,
            width,
            height,
            max_flow,
            bottom,
            gate_status,
            longitude,
            latitude,
        ) in GATE_SPECS:
            gate = session.scalar(
                select(Gate).where(
                    Gate.dataset_version_id == version.id, Gate.gate_code == code
                )
            )
            if gate is None:
                session.add(
                    Gate(
                        dataset_version_id=version.id,
                        name=name,
                        gate_code=code,
                        river_id=rivers_by_code[river_code].id,
                        gate_type=gate_type,
                        opening_direction="vertical",
                        control_mode="local",
                        width=width,
                        height=height,
                        max_flow=max_flow,
                        bottom_elevation=bottom,
                        status=gate_status,
                        geometry=_point_wkt(longitude, latitude),
                    )
                )

        for (
            code,
            name,
            river_code,
            design_flow,
            head,
            power,
            pump_status,
            longitude,
            latitude,
        ) in PUMP_SPECS:
            pump = session.scalar(
                select(Pump).where(
                    Pump.dataset_version_id == version.id, Pump.pump_code == code
                )
            )
            if pump is None:
                session.add(
                    Pump(
                        dataset_version_id=version.id,
                        name=name,
                        pump_code=code,
                        river_id=rivers_by_code[river_code].id,
                        design_flow=design_flow,
                        head=head,
                        power=power,
                        efficiency_curve={
                            "points": [[0.0, 0.0], [0.5, 0.78], [1.0, 0.84]]
                        },
                        control_mode="local",
                        status=pump_status,
                        geometry=_point_wkt(longitude, latitude),
                    )
                )

        section_number = 0
        for spec in RIVER_SPECS:
            river = rivers_by_code[str(spec["code"])]
            for index in range(1, int(spec["section_count"]) + 1):
                section_number += 1
                ratio = index / (int(spec["section_count"]) + 1)
                station = round(float(spec["length"]) * ratio, 3)
                section = session.scalar(
                    select(CrossSection).where(
                        CrossSection.dataset_version_id == version.id,
                        CrossSection.river_id == river.id,
                        CrossSection.station == station,
                    )
                )
                if section is not None:
                    continue
                longitude, latitude = _interpolate(spec["coordinates"], ratio)
                base = 7.2 + math.sin(index * 0.72) * 0.45
                points = [
                    [0.0, round(base + 2.8, 2)],
                    [5.0, round(base + 0.9, 2)],
                    [10.0, round(base, 2)],
                    [15.0, round(base + 0.7, 2)],
                    [20.0, round(base + 2.5, 2)],
                ]
                session.add(
                    CrossSection(
                        dataset_version_id=version.id,
                        river_id=river.id,
                        section_code=f"DEMO-CS-{section_number:03d}",
                        section_name=f"DEMO 横断面 {section_number:03d}",
                        station=station,
                        points={"points": points},
                        roughness=0.028 + index * 0.0002,
                        elevation_min=min(point[1] for point in points),
                        survey_date=None,
                        geometry=_point_wkt(longitude, latitude),
                    )
                )

        session.flush()
        river_count = session.scalar(
            select(func.count(River.id)).where(River.dataset_version_id == version.id)
        ) or 0
        node_count = session.scalar(
            select(func.count(RiverNode.id)).where(RiverNode.dataset_version_id == version.id)
        ) or 0
        segment_count = session.scalar(
            select(func.count(RiverSegment.id)).where(RiverSegment.dataset_version_id == version.id)
        ) or 0
        connection_count = session.scalar(
            select(func.count(RiverConnection.id)).where(
                RiverConnection.dataset_version_id == version.id
            )
        ) or 0
        # 结果表通过外键绑定稳定的节点身份。仅在拓扑缺失/不完整时生成，
        # 避免每次容器启动删除节点并破坏历史仿真的可追溯性。
        if node_count == 0 or segment_count == 0 or connection_count != segment_count or segment_count < river_count:
            generate_topology(session, version.id, 0.00001)
        main_river = rivers_by_code["DEMO-RIVER-A"]
        main_segments = session.scalars(
            select(RiverSegment).where(RiverSegment.river_id == main_river.id)
        ).all()
        all_segments = session.scalars(
            select(RiverSegment).where(RiverSegment.dataset_version_id == version.id)
        ).all()
        upstream_ids = {item.upstream_node_id for item in all_segments}
        downstream_ids = {item.downstream_node_id for item in all_segments}
        source_node_ids = sorted(upstream_ids - downstream_ids)
        sink_node_ids = sorted(downstream_ids - upstream_ids)

        parameter_specs = (
            ("time_step", 60.0, "s", "请求时间步长；CFL 约束可自动降低"),
            ("duration_seconds", 3600.0, "s", "模拟总时长"),
            ("output_interval", 300.0, "s", "结果输出间隔"),
            ("cfl", 0.75, "-", "CFL 稳定性系数"),
            ("initial_water_level", 10.8, "m", "初始水位"),
            ("initial_flow", 60.0, "m³/s", "初始流量"),
            ("minimum_depth", 0.05, "m", "最小计算水深"),
        )
        for name, value, unit, description in parameter_specs:
            _ensure_parameter(session, version.id, name, value, unit, description)

        explicit_boundaries: list[BoundaryCondition] = []
        for index, source_node_id in enumerate(source_node_ids, start=1):
            upstream = session.scalar(
                select(BoundaryCondition).where(
                    BoundaryCondition.dataset_version_id == version.id,
                    BoundaryCondition.name == f"DEMO 上游恒定流量 {index}",
                )
            )
            if upstream is None:
                upstream = BoundaryCondition(
                    dataset_version_id=version.id,
                    name=f"DEMO 上游恒定流量 {index}",
                    boundary_type="upstream_flow",
                    target_node_id=source_node_id,
                    values={"mode": "constant", "value": 60.0 if index == 1 else 20.0},
                    unit="m³/s",
                    description="DEMO DATA｜Phase 4 显式外边界",
                )
                session.add(upstream)
            else:
                upstream.target_node_id = source_node_id
                upstream.values = {"mode": "constant", "value": 60.0 if index == 1 else 20.0}
                upstream.unit = "m³/s"
            session.flush()
            explicit_boundaries.append(upstream)
        for index, sink_node_id in enumerate(sink_node_ids, start=1):
            downstream = session.scalar(
                select(BoundaryCondition).where(
                    BoundaryCondition.dataset_version_id == version.id,
                    BoundaryCondition.name == f"DEMO 下游恒定水位 {index}",
                )
            )
            if downstream is None:
                downstream = BoundaryCondition(
                    dataset_version_id=version.id,
                    name=f"DEMO 下游恒定水位 {index}",
                    boundary_type="downstream_water_level",
                    target_node_id=sink_node_id,
                    values={"mode": "constant", "value": 10.2},
                    unit="m",
                    description="DEMO DATA｜Phase 4 显式外边界",
                )
                session.add(downstream)
            else:
                downstream.target_node_id = sink_node_id
                downstream.values = {"mode": "constant", "value": 10.2}
                downstream.unit = "m"
            session.flush()
            explicit_boundaries.append(downstream)

        simulation_case = session.scalar(
            select(SimulationCase)
            .where(SimulationCase.dataset_version_id == version.id)
            .order_by(SimulationCase.id)
        )
        if simulation_case is None:
            simulation_case = SimulationCase(
                name="DEMO 基准工况",
                description="Phase 4 河网联合调度仿真基线",
                dataset_version_id=version.id,
                boundary_condition_id=explicit_boundaries[0].id,
            )
            session.add(simulation_case)
        else:
            simulation_case.boundary_condition_id = explicit_boundaries[0].id
        session.flush()
        session.query(SimulationCaseBoundary).filter(
            SimulationCaseBoundary.case_id == simulation_case.id
        ).delete(synchronize_session=False)
        for boundary in explicit_boundaries:
            session.add(
                SimulationCaseBoundary(
                    case_id=simulation_case.id,
                    boundary_condition_id=boundary.id,
                    role=boundary.boundary_type,
                )
            )

        segments_by_river: dict[int, list[RiverSegment]] = {}
        for segment in all_segments:
            segments_by_river.setdefault(segment.river_id, []).append(segment)
        for gate_index, gate in enumerate(
            session.scalars(select(Gate).where(Gate.dataset_version_id == version.id).order_by(Gate.id)).all()
        ):
            river_segments = sorted(segments_by_river[gate.river_id], key=lambda item: item.id)
            segment = river_segments[gate_index % len(river_segments)]
            gate.river_segment_id = segment.id
            gate.station = segment.length * 0.5
            gate.upstream_node_id = segment.upstream_node_id
            gate.downstream_node_id = segment.downstream_node_id
            gate.crest_elevation = gate.bottom_elevation
            gate.discharge_coefficient = 0.62
            gate.minimum_opening = 0.1
            gate.maximum_opening = gate.height
            gate.opening_rate_limit = 0.02
            gate.minimum_hold_seconds = 60.0
            gate.allow_reverse_flow = False
        for pump in session.scalars(
            select(Pump).where(Pump.dataset_version_id == version.id).order_by(Pump.id)
        ).all():
            river_segments = sorted(segments_by_river[pump.river_id], key=lambda item: item.id)
            segment = river_segments[0]
            pump.intake_node_id = segment.upstream_node_id
            pump.outlet_node_id = segment.downstream_node_id
            pump.transfer_type = "internal_transfer"
            pump.unit_count = 2
            pump.minimum_running_units = 1
            pump.maximum_running_units = 2
            pump.minimum_run_seconds = 120.0
            pump.minimum_stop_seconds = 120.0
            pump.maximum_starts_per_run = 6
            pump.minimum_operating_head = 0.0
            pump.maximum_operating_head = pump.head * 1.5
            pump.reverse_flow_protection = True
            pump.head_curve = {"points": [[0.0, pump.head * 1.2], [pump.design_flow, pump.head]]}

        # Phase 1C labels are derived from the same authoritative rows. ON CONFLICT keeps
        # repeated Compose starts idempotent and never creates a second GIS data source.
        session.execute(text("""
            INSERT INTO map_annotation (
                dataset_version_id, annotation_type, name, text, description,
                longitude, latitude, rotation, font_size, color,
                visible_scale_min, visible_scale_max, related_type, related_id, geometry
            )
            SELECT dataset_version_id, 'river', 'river-' || id, name,
                   '河道名称（由权威河道几何派生）', ST_X(ST_LineInterpolatePoint(geometry, 0.5)),
                   ST_Y(ST_LineInterpolatePoint(geometry, 0.5)),
                   MOD((DEGREES(ST_Azimuth(ST_StartPoint(geometry), ST_EndPoint(geometry))) + 360)::numeric, 360)::double precision,
                   18, '#72F1E2', 40000, 500000, 'river', id,
                   ST_LineInterpolatePoint(geometry, 0.5)
            FROM river WHERE dataset_version_id = :version_id
            UNION ALL
            SELECT dataset_version_id, 'gate', 'gate-' || id, name, '闸门名称',
                   ST_X(geometry), ST_Y(geometry), 0, 15, '#FFD166', 0, 120000,
                   'gate', id, geometry FROM gate WHERE dataset_version_id = :version_id
            UNION ALL
            SELECT dataset_version_id, 'pump', 'pump-' || id, name, '泵站名称',
                   ST_X(geometry), ST_Y(geometry), 0, 15, '#6CC7FF', 0, 120000,
                   'pump', id, geometry FROM pump WHERE dataset_version_id = :version_id
            UNION ALL
            SELECT dataset_version_id, 'cross_section', 'cross-section-' || id,
                   COALESCE(NULLIF(section_name, ''), section_code), '横断面名称',
                   ST_X(geometry), ST_Y(geometry), 0, 12, '#CBB9FF', 0, 65000,
                   'cross_section', id, geometry
            FROM cross_section WHERE dataset_version_id = :version_id
            ON CONFLICT ON CONSTRAINT uq_map_annotation_version_related_name DO NOTHING
        """), {"version_id": version.id})

        # Phase 1D offline gazetteer rows are idempotent and remain version-owned.
        session.execute(text("""
            INSERT INTO administrative_area
                (dataset_version_id, code, name, administrative_level, address, geometry)
            VALUES
                (:version_id, 'CN-GD-GZ', '广州市', 'city', '广东省广州市', ST_GeomFromText('POLYGON((113.10 22.95,113.55 22.95,113.55 23.35,113.10 23.35,113.10 22.95))',4490)),
                (:version_id, 'CN-GD-GZ-TH', '天河区', 'district', '广东省广州市天河区', ST_GeomFromText('POLYGON((113.25 23.05,113.48 23.05,113.48 23.24,113.25 23.24,113.25 23.05))',4490)),
                (:version_id, 'DEMO-BASIN', 'DEMO 工程流域', 'engineering_demo', 'DEMO DATA', ST_GeomFromText('POLYGON((119.92 30.02,120.62 30.02,120.62 30.55,119.92 30.55,119.92 30.02))',4490))
            ON CONFLICT ON CONSTRAINT uq_administrative_area_version_code DO NOTHING
        """), {"version_id": version.id})

        session.execute(text("""
            INSERT INTO road (dataset_version_id, code, name, road_type, address, geometry)
            VALUES
                (:version_id, 'GZ-TSL', '天寿路', 'urban', '广州市天河区天寿路', ST_GeomFromText('LINESTRING(113.3380 23.1410,113.3392 23.1465,113.3400 23.1515)',4490)),
                (:version_id, 'GZ-GYKSL', '广园快速路', 'expressway', '广州市天河区广园快速路', ST_GeomFromText('LINESTRING(113.2900 23.1590,113.3500 23.1610,113.4300 23.1580)',4490)),
                (:version_id, 'GZ-TYDXL', '天源路', 'arterial', '广州市天河区天源路', ST_GeomFromText('LINESTRING(113.3450 23.1650,113.3600 23.2050,113.3760 23.2450)',4490)),
                (:version_id, 'DEMO-RD-001', 'DEMO 防汛巡检路', 'engineering', 'DEMO 工程流域', ST_GeomFromText('LINESTRING(120.00 30.235,120.18 30.255,120.36 30.235,120.55 30.285)',4490))
            ON CONFLICT ON CONSTRAINT uq_road_version_code DO NOTHING
        """), {"version_id": version.id})

        session.execute(text("""
            INSERT INTO place_name (dataset_version_id, code, name, place_type, address, importance, geometry)
            VALUES
                (:version_id, 'PLACE-GZ', '广州市', 'city', '广东省广州市', 100, ST_SetSRID(ST_MakePoint(113.2644,23.1291),4490)),
                (:version_id, 'PLACE-TH', '天河区', 'district', '广东省广州市天河区', 90, ST_SetSRID(ST_MakePoint(113.3612,23.1247),4490)),
                (:version_id, 'PLACE-DEMO', 'DEMO 河网调度区', 'engineering_demo', 'DEMO DATA', 80, ST_SetSRID(ST_MakePoint(120.27,30.27),4490))
            ON CONFLICT ON CONSTRAINT uq_place_name_version_code DO NOTHING
        """), {"version_id": version.id})

        session.execute(text("""
            INSERT INTO water_name (dataset_version_id, code, name, water_type, address, geometry)
            VALUES
                (:version_id, 'WATER-ZJ', '珠江', 'river', '广东省广州市', ST_SetSRID(ST_MakePoint(113.2700,23.1050),4490)),
                (:version_id, 'WATER-SHC', '沙河涌', 'channel', '广州市天河区', ST_SetSRID(ST_MakePoint(113.3220,23.1450),4490)),
                (:version_id, 'WATER-DEMO', 'DEMO 主河道水系', 'engineering_demo', 'DEMO DATA', ST_SetSRID(ST_MakePoint(120.30,30.24),4490))
            ON CONFLICT ON CONSTRAINT uq_water_name_version_code DO NOTHING
        """), {"version_id": version.id})

        session.execute(text("""
            INSERT INTO poi (dataset_version_id, code, name, category, address, geometry)
            VALUES
                (:version_id, 'POI-GZ-EAST', '广州东站', 'transport', '广州市天河区林和中路', ST_SetSRID(ST_MakePoint(113.3249,23.1503),4490)),
                (:version_id, 'POI-TIANHE-SPORTS', '天河体育中心', 'public_service', '广州市天河区天河路299号', ST_SetSRID(ST_MakePoint(113.3283,23.1377),4490)),
                (:version_id, 'POI-COORD-DEMO', '天寿路坐标示例点', 'demo_coordinate', '广州市天河区天寿路', ST_SetSRID(ST_MakePoint(113.3238,23.1356),4490)),
                (:version_id, 'POI-DAYU-CENTER', '大禹天工调度中心', 'engineering', 'DEMO 工程流域', ST_SetSRID(ST_MakePoint(120.27,30.27),4490))
            ON CONFLICT ON CONSTRAINT uq_poi_version_code DO NOTHING
        """), {"version_id": version.id})

        # Fresh installations run migration 0011 before seeding, so explicitly
        # freeze the completed DEMO version just like upgraded installations do.
        version.status = "published"
        version.published_at = datetime.now(UTC)
        version.change_summary = version.change_summary or "Frozen DEMO baseline."
        session.flush()
        _backfill_governance_metadata(session)

    with SessionLocal() as session:
        return {
            "dataset_versions": session.scalar(select(func.count(DatasetVersion.id))) or 0,
            "rivers": session.scalar(select(func.count(River.id))) or 0,
            "gates": session.scalar(select(func.count(Gate.id))) or 0,
            "pumps": session.scalar(select(func.count(Pump.id))) or 0,
            "cross_sections": session.scalar(select(func.count(CrossSection.id))) or 0,
            "map_annotations": session.scalar(select(func.count(MapAnnotation.id))) or 0,
            "administrative_areas": session.scalar(select(func.count(AdministrativeArea.id))) or 0,
            "roads": session.scalar(select(func.count(Road.id))) or 0,
            "place_names": session.scalar(select(func.count(PlaceName.id))) or 0,
            "water_names": session.scalar(select(func.count(WaterName.id))) or 0,
            "pois": session.scalar(select(func.count(PointOfInterest.id))) or 0,
            "river_nodes": session.scalar(select(func.count(RiverNode.id))) or 0,
            "simulation_cases": session.scalar(select(func.count(SimulationCase.id))) or 0,
        }


def seed_demo_data() -> dict[str, int]:
    """Seed DEMO data and always run the idempotent built-in knowledge import."""

    counts = _seed_demo_data_rows()
    # Keep the AI knowledge transaction separate from the spatial seed.  In
    # particular, the frozen-baseline fast path above must not skip this step.
    with SessionLocal() as session:
        seed_builtin_knowledge(session)
    return counts


if __name__ == "__main__":
    print(f"DEMO DATA 已就绪：{seed_demo_data()}")
