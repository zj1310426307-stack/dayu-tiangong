"""幂等生成 Phase 2 版本化河网、水工建筑物和模型输入 DEMO DATA。"""

import math
import sys
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.database.session import SessionLocal  # noqa: E402
from app.gis.models import (  # noqa: E402
    BoundaryCondition,
    CrossSection,
    DatasetVersion,
    Gate,
    ModelParameter,
    Pump,
    River,
    RiverNode,
    SimulationCase,
)
from app.river.service import generate_topology  # noqa: E402


RIVER_SPECS = [
    {
        "code": "DEMO-RIVER-A",
        "name": "DEMO 主河道 A",
        "length": 58_600.0,
        "level": "main",
        "description": "DEMO DATA｜Phase 2 版本化水利数据库测试，不代表真实工程。",
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
    """将经纬度序列转换为带 SRID 的 LineString WKT。"""

    body = ", ".join(f"{longitude} {latitude}" for longitude, latitude in coordinates)
    return WKTElement(f"LINESTRING ({body})", srid=4326)


def _point_wkt(longitude: float, latitude: float) -> WKTElement:
    """将经纬度转换为带 SRID 的 Point WKT。"""

    return WKTElement(f"POINT ({longitude} {latitude})", srid=4326)


def _interpolate(coordinates: list[tuple[float, float]], ratio: float) -> tuple[float, float]:
    """按折线分段均匀插值，生成横断面测试位置。"""

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


def _ensure_dataset_version(session) -> DatasetVersion:
    """取得迁移基线版本，或在空表中补建该版本。"""

    version = session.scalar(select(DatasetVersion).where(DatasetVersion.version == "V1.0"))
    if version is None:
        version = DatasetVersion(
            version="V1.0",
            name="2026现状河网（DEMO）",
            description="Phase 2 DEMO DATA，不代表真实工程。",
            creator="Codex DEMO",
        )
        session.add(version)
        session.flush()
    return version


def seed_demo_data() -> dict[str, int]:
    """按版本化业务唯一键补齐 DEMO DATA 并返回最终数量。"""

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
            rivers_by_code[spec["code"]] = river

        for index, (code, name, river_code, gate_type, width, height, max_flow, bottom, status, longitude, latitude) in enumerate(GATE_SPECS, start=1):
            gate = session.scalar(select(Gate).where(Gate.dataset_version_id == version.id, Gate.gate_code == code))
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
                        status=status,
                        geometry=_point_wkt(longitude, latitude),
                    )
                )

        for code, name, river_code, design_flow, head, power, status, longitude, latitude in PUMP_SPECS:
            pump = session.scalar(select(Pump).where(Pump.dataset_version_id == version.id, Pump.pump_code == code))
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
                        efficiency_curve={"points": [[0.0, 0.0], [0.5, 0.78], [1.0, 0.84]]},
                        control_mode="local",
                        status=status,
                        geometry=_point_wkt(longitude, latitude),
                    )
                )

        section_number = 0
        for spec in RIVER_SPECS:
            river = rivers_by_code[spec["code"]]
            for index in range(1, spec["section_count"] + 1):
                section_number += 1
                ratio = index / (spec["section_count"] + 1)
                station = round(spec["length"] * ratio, 3)
                section = session.scalar(select(CrossSection).where(CrossSection.dataset_version_id == version.id, CrossSection.river_id == river.id, CrossSection.station == station))
                if section is not None:
                    continue
                longitude, latitude = _interpolate(spec["coordinates"], ratio)
                base = 7.2 + math.sin(index * 0.72) * 0.45
                points = [[0.0, round(base + 2.8, 2)], [5.0, round(base + 0.9, 2)], [10.0, round(base, 2)], [15.0, round(base + 0.7, 2)], [20.0, round(base + 2.5, 2)]]
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
        topology = generate_topology(session, version.id, 0.00001)
        first_node_id = topology.nodes[0].id if topology.nodes else None

        if session.scalar(select(ModelParameter).where(ModelParameter.dataset_version_id == version.id, ModelParameter.parameter_type == "solver", ModelParameter.parameter_name == "time_step")) is None:
            session.add(ModelParameter(dataset_version_id=version.id, parameter_type="solver", parameter_name="time_step", value=60.0, unit="s", description="DEMO 一维非恒定流计算步长"))

        boundary = session.scalar(select(BoundaryCondition).where(BoundaryCondition.dataset_version_id == version.id, BoundaryCondition.name == "DEMO 上游恒定流量"))
        if boundary is None:
            boundary = BoundaryCondition(dataset_version_id=version.id, name="DEMO 上游恒定流量", boundary_type="upstream_flow", target_node_id=first_node_id, values={"mode": "constant", "value": 120.0}, unit="m³/s", description="DEMO DATA")
            session.add(boundary)
            session.flush()

        if session.scalar(select(SimulationCase).where(SimulationCase.name == "DEMO 基准工况")) is None:
            session.add(SimulationCase(name="DEMO 基准工况", description="Phase 3 模型输入准备基线", dataset_version_id=version.id, boundary_condition_id=boundary.id))

    with SessionLocal() as session:
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
