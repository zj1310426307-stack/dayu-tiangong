"""Phase 2 水利数据库的 SQLAlchemy/PostGIS 统一模型元数据。"""

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """集中保存全部数据库模型元数据，作为 Alembic 唯一发现入口。"""


class DatasetVersion(Base):
    """标识一组不可混用的河网、断面、建筑物和模型参数数据。"""

    __tablename__ = "dataset_version"
    __table_args__ = (UniqueConstraint("version", name="uq_dataset_version_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str] = mapped_column(String(64), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rivers: Mapped[list["River"]] = relationship(back_populates="dataset_version")
    parameters: Mapped[list["ModelParameter"]] = relationship(back_populates="dataset_version")
    boundary_conditions: Mapped[list["BoundaryCondition"]] = relationship(
        back_populates="dataset_version"
    )
    simulation_cases: Mapped[list["SimulationCase"]] = relationship(
        back_populates="dataset_version"
    )


class River(Base):
    """河道空间聚合根，几何为 EPSG:4326 LineString。"""

    __tablename__ = "river"
    __table_args__ = (
        CheckConstraint("length >= 0", name="ck_river_length_nonnegative"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'planned')",
            name="ck_river_status",
        ),
        UniqueConstraint("dataset_version_id", "code", name="uq_river_version_code"),
        Index("ix_river_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_river_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    length: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    description: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
        nullable=False,
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="rivers")
    segments: Mapped[list["RiverSegment"]] = relationship(back_populates="river")
    cross_sections: Mapped[list["CrossSection"]] = relationship(back_populates="river")
    gates: Mapped[list["Gate"]] = relationship(back_populates="river")
    pumps: Mapped[list["Pump"]] = relationship(back_populates="river")
    connections: Mapped[list["RiverConnection"]] = relationship(back_populates="river")


class RiverNode(Base):
    """保存河网端点和汇分流节点，并保留可直接审计的经纬度。"""

    __tablename__ = "river_node"
    __table_args__ = (
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_river_node_longitude"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_river_node_latitude"),
        CheckConstraint(
            "node_type IN ('start', 'end', 'confluence', 'bifurcation', 'gate_control')",
            name="ck_river_node_type",
        ),
        UniqueConstraint("dataset_version_id", "node_code", name="uq_river_node_version_code"),
        Index("ix_river_node_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_river_node_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    node_code: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )


class RiverSegment(Base):
    """把复杂河道拆分为具有明确上下游节点的计算河段。"""

    __tablename__ = "river_segment"
    __table_args__ = (
        CheckConstraint("length >= 0", name="ck_river_segment_length_nonnegative"),
        UniqueConstraint(
            "dataset_version_id", "segment_code", name="uq_river_segment_version_code"
        ),
        Index("ix_river_segment_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_river_segment_river_id", "river_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="CASCADE"))
    segment_code: Mapped[str] = mapped_column(String(64), nullable=False)
    upstream_node_id: Mapped[int] = mapped_column(
        ForeignKey("river_node.id", ondelete="RESTRICT"), nullable=False
    )
    downstream_node_id: Mapped[int] = mapped_column(
        ForeignKey("river_node.id", ondelete="RESTRICT"), nullable=False
    )
    length: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="segments")


class RiverConnection(Base):
    """以有向边表达节点之间的河网连接关系。"""

    __tablename__ = "river_connection"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "from_node_id",
            "to_node_id",
            "river_id",
            name="uq_river_connection_edge",
        ),
        Index("ix_river_connection_river_id", "river_id"),
        Index("ix_river_connection_from_node_id", "from_node_id"),
        Index("ix_river_connection_to_node_id", "to_node_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("river_node.id", ondelete="CASCADE"), nullable=False
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("river_node.id", ondelete="CASCADE"), nullable=False
    )
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="CASCADE"))

    river: Mapped[River] = relationship(back_populates="connections")


class CrossSection(Base):
    """河道横断面，保存桩号、有序横向高程点和空间定位点。"""

    __tablename__ = "cross_section"
    __table_args__ = (
        CheckConstraint("station >= 0", name="ck_cross_section_station_nonnegative"),
        CheckConstraint("roughness > 0", name="ck_cross_section_roughness_positive"),
        UniqueConstraint(
            "dataset_version_id", "section_code", name="uq_cross_section_version_code"
        ),
        UniqueConstraint(
            "dataset_version_id",
            "river_id",
            "station",
            name="uq_cross_section_version_river_station",
        ),
        Index("ix_cross_section_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_cross_section_river_id", "river_id"),
        Index("ix_cross_section_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="CASCADE"))
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    station: Mapped[float] = mapped_column(Float, nullable=False)
    points: Mapped[dict[str, list[list[float]]]] = mapped_column(JSON, nullable=False)
    roughness: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_min: Mapped[float] = mapped_column(Float, nullable=False)
    survey_date: Mapped[date | None] = mapped_column(Date)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="cross_sections")


class Gate(Base):
    """闸门静态设计参数和空间定位，不承载调度执行状态。"""

    __tablename__ = "gate"
    __table_args__ = (
        CheckConstraint("width > 0", name="ck_gate_width_positive"),
        CheckConstraint("height > 0", name="ck_gate_height_positive"),
        CheckConstraint("max_flow >= 0", name="ck_gate_max_flow_nonnegative"),
        CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'fault')",
            name="ck_gate_status",
        ),
        UniqueConstraint("dataset_version_id", "gate_code", name="uq_gate_version_code"),
        Index("ix_gate_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_gate_river_id", "river_id"),
        Index("ix_gate_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(64), nullable=False)
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="RESTRICT"))
    gate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    opening_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    max_flow: Mapped[float] = mapped_column(Float, nullable=False)
    bottom_elevation: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="gates")


class Pump(Base):
    """泵站设计流量、扬程、功率、效率曲线和空间定位。"""

    __tablename__ = "pump"
    __table_args__ = (
        CheckConstraint("design_flow >= 0", name="ck_pump_design_flow_nonnegative"),
        CheckConstraint("head >= 0", name="ck_pump_head_nonnegative"),
        CheckConstraint("power >= 0", name="ck_pump_power_nonnegative"),
        CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'fault')",
            name="ck_pump_status",
        ),
        UniqueConstraint("dataset_version_id", "pump_code", name="uq_pump_version_code"),
        Index("ix_pump_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_pump_river_id", "river_id"),
        Index("ix_pump_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pump_code: Mapped[str] = mapped_column(String(64), nullable=False)
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="RESTRICT"))
    design_flow: Mapped[float] = mapped_column(Float, nullable=False)
    head: Mapped[float] = mapped_column(Float, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    efficiency_curve: Mapped[dict[str, list[list[float]]]] = mapped_column(JSON, nullable=False)
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="pumps")


class ModelParameter(Base):
    """保存可按数据版本追溯的 Phase 3 模型参数。"""

    __tablename__ = "model_parameter"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "parameter_type",
            "parameter_name",
            name="uq_model_parameter_version_name",
        ),
        Index("ix_model_parameter_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    parameter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="parameters")


class BoundaryCondition(Base):
    """保存上游流量、下游水位等边界时间序列或定值。"""

    __tablename__ = "boundary_condition"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "name", name="uq_boundary_condition_version_name"
        ),
        Index("ix_boundary_condition_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    boundary_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="boundary_conditions")


class SimulationCase(Base):
    """引用版本化河网和边界条件，定义可交给 Phase 3 的计算方案。"""

    __tablename__ = "simulation_case"
    __table_args__ = (
        UniqueConstraint("name", name="uq_simulation_case_name"),
        Index("ix_simulation_case_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    boundary_condition_id: Mapped[int] = mapped_column(
        ForeignKey("boundary_condition.id", ondelete="RESTRICT"), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="simulation_cases")
