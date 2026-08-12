"""Idempotently seed the versioned Phase 3 DEMO hydraulic dataset."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.database.session import SessionLocal  # noqa: E402
from app.ai.service import seed_builtin_knowledge  # noqa: E402
from app.gis.models import (  # noqa: E402
    BoundaryCondition,
    CrossSection,
    DatasetVersion,
    Gate,
    ModelParameter,
    Pump,
    River,
    RiverNode,
    RiverConnection,
    RiverSegment,
    SimulationCase,
    SimulationCaseBoundary,
)
from app.river.service import generate_topology  # noqa: E402


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


def seed_demo_data() -> dict[str, int]:
    """Populate the complete DEMO model input and return final row counts."""

    with SessionLocal.begin() as session:
        version = _ensure_dataset_version(session)
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

    with SessionLocal() as session:
        # Phase 6 内置知识随空库初始化幂等入库，容器无需手工执行第二条命令。
        seed_builtin_knowledge(session)
        return {
            "dataset_versions": session.scalar(select(func.count(DatasetVersion.id))) or 0,
            "rivers": session.scalar(select(func.count(River.id))) or 0,
            "gates": session.scalar(select(func.count(Gate.id))) or 0,
            "pumps": session.scalar(select(func.count(Pump.id))) or 0,
            "cross_sections": session.scalar(select(func.count(CrossSection.id))) or 0,
            "river_nodes": session.scalar(select(func.count(RiverNode.id))) or 0,
            "simulation_cases": session.scalar(select(func.count(SimulationCase.id))) or 0,
        }


if __name__ == "__main__":
    print(f"DEMO DATA 已就绪：{seed_demo_data()}")
