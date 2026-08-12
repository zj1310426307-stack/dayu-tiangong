"""Phase 2 水利数据库的 SQLAlchemy/PostGIS 统一模型元数据。"""

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
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
    """河道空间聚合根，几何为 CGCS2000 / EPSG:4490 LineString。"""

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
        Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False),
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
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
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
        Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False), nullable=False
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
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
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
    river_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_segment.id", ondelete="SET NULL")
    )
    station: Mapped[float | None] = mapped_column(Float)
    upstream_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    downstream_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    crest_elevation: Mapped[float | None] = mapped_column(Float)
    discharge_coefficient: Mapped[float | None] = mapped_column(Float)
    minimum_opening: Mapped[float | None] = mapped_column(Float)
    maximum_opening: Mapped[float | None] = mapped_column(Float)
    opening_rate_limit: Mapped[float | None] = mapped_column(Float)
    minimum_hold_seconds: Mapped[float | None] = mapped_column(Float)
    allow_reverse_flow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
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
    head_curve: Mapped[dict[str, list[list[float]]] | None] = mapped_column(JSON)
    intake_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    outlet_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    transfer_type: Mapped[str | None] = mapped_column(String(24))
    unit_count: Mapped[int | None] = mapped_column(Integer)
    minimum_running_units: Mapped[int | None] = mapped_column(Integer)
    maximum_running_units: Mapped[int | None] = mapped_column(Integer)
    minimum_run_seconds: Mapped[float | None] = mapped_column(Float)
    minimum_stop_seconds: Mapped[float | None] = mapped_column(Float)
    maximum_starts_per_run: Mapped[int | None] = mapped_column(Integer)
    minimum_operating_head: Mapped[float | None] = mapped_column(Float)
    maximum_operating_head: Mapped[float | None] = mapped_column(Float)
    reverse_flow_protection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
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
    tasks: Mapped[list["SimulationTask"]] = relationship(back_populates="simulation_case")
    boundary_links: Mapped[list["SimulationCaseBoundary"]] = relationship(
        back_populates="simulation_case", cascade="all, delete-orphan"
    )


class SimulationCaseBoundary(Base):
    """明确关联一个计算方案使用的边界条件及其角色。"""

    __tablename__ = "simulation_case_boundary"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "boundary_condition_id", name="uq_case_boundary_link"
        ),
        Index("ix_simulation_case_boundary_case_id", "case_id"),
    )

    case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="CASCADE"), primary_key=True
    )
    boundary_condition_id: Mapped[int] = mapped_column(
        ForeignKey("boundary_condition.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    simulation_case: Mapped[SimulationCase] = relationship(back_populates="boundary_links")


class SimulationTask(Base):
    """Persist one reproducible hydraulic execution and its lifecycle state."""

    __tablename__ = "simulation_task"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'cancel_requested', "
            "'cancelled', 'success', 'failed')",
            name="ck_simulation_task_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100", name="ck_simulation_task_progress"
        ),
        Index("ix_simulation_task_case_id", "case_id"),
        Index("ix_simulation_task_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_schema_version: Mapped[str | None] = mapped_column(String(48))
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    input_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str | None] = mapped_column(String(64))
    engine_commit: Mapped[str | None] = mapped_column(String(64))
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    queued_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_reason: Mapped[str | None] = mapped_column(Text)
    current_simulation_time: Mapped[float | None] = mapped_column(Float)
    current_cfl: Mapped[float | None] = mapped_column(Float)
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    simulation_case: Mapped[SimulationCase] = relationship(back_populates="tasks")
    results: Mapped[list["SimulationResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class SimulationResult(Base):
    """Persist one section/time row from a successful hydraulic task."""

    __tablename__ = "simulation_result"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "section_code",
            "time_seconds",
            name="uq_simulation_result_task_section_time",
        ),
        Index("ix_simulation_result_task_id", "task_id"),
        Index("ix_simulation_result_section_id", "section_id"),
        Index("ix_simulation_result_river_id", "river_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("cross_section.id", ondelete="SET NULL")
    )
    river_id: Mapped[int | None] = mapped_column(
        ForeignKey("river.id", ondelete="SET NULL")
    )
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    station: Mapped[float] = mapped_column(Float, nullable=False)
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    water_level: Mapped[float] = mapped_column(Float, nullable=False)
    flow: Mapped[float] = mapped_column(Float, nullable=False)
    velocity: Mapped[float] = mapped_column(Float, nullable=False)

    task: Mapped[SimulationTask] = relationship(back_populates="results")


class DispatchPlan(Base):
    """保存可校验、冻结、克隆和归档的仿真调度计划版本。"""

    __tablename__ = "dispatch_plan"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'validated', 'frozen', 'archived')",
            name="ck_dispatch_plan_status",
        ),
        UniqueConstraint("name", "version", name="uq_dispatch_plan_name_version"),
        Index("ix_dispatch_plan_dataset_version_id", "dataset_version_id"),
        Index("ix_dispatch_plan_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    simulation_case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    description: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    evaluation_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    storage_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="key_sections"
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    frozen_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    frozen_snapshot_hash: Mapped[str | None] = mapped_column(String(64))


class DispatchAction(Base):
    """保存指定时刻的闸门或泵站人工调度命令。"""

    __tablename__ = "dispatch_action"
    __table_args__ = (
        CheckConstraint("structure_type IN ('gate', 'pump')", name="ck_dispatch_action_type"),
        CheckConstraint(
            "(gate_id IS NOT NULL AND pump_id IS NULL) OR "
            "(gate_id IS NULL AND pump_id IS NOT NULL)",
            name="ck_dispatch_action_single_asset",
        ),
        UniqueConstraint(
            "plan_id", "time_seconds", "structure_type", "gate_id", "pump_id",
            name="uq_dispatch_action_asset_time",
        ),
        Index("ix_dispatch_action_plan_time", "plan_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plan.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_id: Mapped[int | None] = mapped_column(ForeignKey("gate.id", ondelete="RESTRICT"))
    pump_id: Mapped[int | None] = mapped_column(ForeignKey("pump.id", ondelete="RESTRICT"))
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    interpolation: Mapped[str] = mapped_column(String(16), nullable=False, server_default="step")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)


class DispatchRule(Base):
    """保存白名单观测和操作符组成的受控阈值规则。"""

    __tablename__ = "dispatch_rule"
    __table_args__ = (Index("ix_dispatch_rule_plan_id", "plan_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plan.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    observation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_object_id: Mapped[int | None] = mapped_column(Integer)
    operator: Mapped[str] = mapped_column(String(4), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    hysteresis: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    minimum_hold_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    cooldown_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    action_template: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class DispatchRun(Base):
    """关联基准与受控任务并保存一次调度仿真的指标和生命周期。"""

    __tablename__ = "dispatch_run"
    __table_args__ = (
        Index("ix_dispatch_run_plan_id", "plan_id"),
        Index("ix_dispatch_run_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plan.id", ondelete="RESTRICT"), nullable=False
    )
    baseline_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    controlled_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DispatchEvent(Base):
    """记录规则/人工命令的请求值、实际值、结果和原因。"""

    __tablename__ = "dispatch_event"
    __table_args__ = (Index("ix_dispatch_event_run_time", "run_id", "time_seconds"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("dispatch_run.id", ondelete="CASCADE"))
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    structure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_command: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_command: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StructureResult(Base):
    """保存闸泵各时刻的请求/实际状态、流量、能耗和约束。"""

    __tablename__ = "structure_result"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "time_seconds", "structure_type", "structure_id",
            name="uq_structure_result_task_time_asset",
        ),
        Index("ix_structure_result_run_time", "dispatch_run_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("simulation_task.id", ondelete="CASCADE"))
    dispatch_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatch_run.id", ondelete="CASCADE")
    )
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    structure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_value: Mapped[float | None] = mapped_column(Float)
    actual_value: Mapped[float | None] = mapped_column(Float)
    flow: Mapped[float] = mapped_column(Float, nullable=False)
    upstream_level: Mapped[float | None] = mapped_column(Float)
    downstream_level: Mapped[float | None] = mapped_column(Float)
    head_difference: Mapped[float | None] = mapped_column(Float)
    transfer_type: Mapped[str | None] = mapped_column(String(24))
    power_kw: Mapped[float | None] = mapped_column(Float)
    energy_kwh: Mapped[float | None] = mapped_column(Float)
    regime: Mapped[str | None] = mapped_column(String(32))
    constraint_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class JunctionResult(Base):
    """保存河网共同水位、节点收支和连续性残差。"""

    __tablename__ = "junction_result"
    __table_args__ = (
        UniqueConstraint("task_id", "node_id", "time_seconds", name="uq_junction_task_node_time"),
        Index("ix_junction_result_task_time", "task_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("simulation_task.id", ondelete="CASCADE"))
    node_id: Mapped[int] = mapped_column(ForeignKey("river_node.id", ondelete="RESTRICT"))
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    water_level: Mapped[float] = mapped_column(Float, nullable=False)
    inflow: Mapped[float] = mapped_column(Float, nullable=False)
    outflow: Mapped[float] = mapped_column(Float, nullable=False)
    source_sink: Mapped[float] = mapped_column(Float, nullable=False)
    balance_residual: Mapped[float] = mapped_column(Float, nullable=False)


class OptimizationTask(Base):
    """Persist a versioned, reproducible multi-objective optimization lifecycle."""

    __tablename__ = "optimization_task"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'cancelled')",
            name="ck_optimization_task_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_optimization_task_progress"),
        Index("ix_optimization_task_status", "status"),
        Index("ix_optimization_task_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pso")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    simulation_case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    objective_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    algorithm_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    best_score: Mapped[float | None] = mapped_column(Float)
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    converged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OptimizationCandidate(Base):
    """Link one generated plan to its score, metrics and Phase 4 simulation task."""

    __tablename__ = "optimization_candidate"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "generation", "candidate_index", name="uq_optimization_candidate_slot"
        ),
        Index("ix_optimization_candidate_task_id", "task_id"),
        Index("ix_optimization_candidate_simulation_task_id", "simulation_task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_task.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dispatch_plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    objective_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    constraint_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    simulation_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OptimizationResult(Base):
    """Persist Pareto level, rank and human-facing recommendation state."""

    __tablename__ = "optimization_result"
    __table_args__ = (
        CheckConstraint(
            "recommendation_status IN ('recommended', 'pareto', 'alternative', 'rejected')",
            name="ck_optimization_result_recommendation_status",
        ),
        Index("ix_optimization_result_task_level", "task_id", "pareto_level"),
    )

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_candidate.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_task.id", ondelete="CASCADE"), nullable=False
    )
    pareto_level: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
