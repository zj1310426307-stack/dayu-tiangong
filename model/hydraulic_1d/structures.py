"""Solver-neutral, provenance-aware Gate and Pump hydraulic specifications."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from model.hydraulic_1d.errors import Hydraulic1DValidationError


class StrictStructureSpec(BaseModel):
    """Freeze hydraulic structure inputs and reject undeclared engineering fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class HydraulicDataStatus(str, Enum):
    """Record whether a hydraulic value is unknown, sourced, or synthetic."""

    UNKNOWN = "UNKNOWN"
    SOURCE_DATA = "SOURCE_DATA"
    SYNTHETIC_ASSUMPTION = "SYNTHETIC_ASSUMPTION"


class SourcedHydraulicScalar(StrictStructureSpec):
    """Carry one finite scalar without turning an unknown into an engineering default."""

    status: HydraulicDataStatus = HydraulicDataStatus.UNKNOWN
    value: FiniteFloat | None = None
    evidence: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """Require a value and evidence only when the value is claimed to be known."""

        if self.status == HydraulicDataStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError("UNKNOWN hydraulic scalar must not contain a value")
            return self
        if self.value is None:
            raise ValueError(f"{self.status.value} hydraulic scalar requires a value")
        if self.evidence is None:
            raise ValueError(f"{self.status.value} hydraulic scalar requires evidence")
        return self

    @classmethod
    def source_data(cls, value: float, evidence: str) -> "SourcedHydraulicScalar":
        """Build a scalar copied from an identified source dataset."""

        return cls(
            status=HydraulicDataStatus.SOURCE_DATA,
            value=value,
            evidence=evidence,
        )

    @classmethod
    def synthetic(cls, value: float, evidence: str) -> "SourcedHydraulicScalar":
        """Build a scalar that is explicitly limited to a synthetic fixture."""

        return cls(
            status=HydraulicDataStatus.SYNTHETIC_ASSUMPTION,
            value=value,
            evidence=evidence,
        )


class SourcedHydraulicBoolean(StrictStructureSpec):
    """Carry a tri-state boolean so missing availability is never interpreted as false."""

    status: HydraulicDataStatus = HydraulicDataStatus.UNKNOWN
    value: bool | None = None
    evidence: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """Keep UNKNOWN distinct from an evidenced true or false value."""

        if self.status == HydraulicDataStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError("UNKNOWN hydraulic boolean must not contain a value")
            return self
        if self.value is None:
            raise ValueError(f"{self.status.value} hydraulic boolean requires a value")
        if self.evidence is None:
            raise ValueError(f"{self.status.value} hydraulic boolean requires evidence")
        return self

    @classmethod
    def source_data(cls, value: bool, evidence: str) -> "SourcedHydraulicBoolean":
        """Build a boolean copied from an identified source dataset."""

        return cls(
            status=HydraulicDataStatus.SOURCE_DATA,
            value=value,
            evidence=evidence,
        )

    @classmethod
    def synthetic(cls, value: bool, evidence: str) -> "SourcedHydraulicBoolean":
        """Build a boolean that is explicitly limited to a synthetic fixture."""

        return cls(
            status=HydraulicDataStatus.SYNTHETIC_ASSUMPTION,
            value=value,
            evidence=evidence,
        )


class StructureFlowDirection(str, Enum):
    """Use the four D-Flow structure directions without embedding D-Flow classes."""

    BOTH = "both"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NONE = "none"


class GateOpeningHorizontalDirection(str, Enum):
    """Describe the explicit horizontal motion supported by GeneralStructure."""

    SYMMETRIC = "symmetric"
    FROM_LEFT = "fromLeft"
    FROM_RIGHT = "fromRight"


class GeneralOpeningGeometry(StrictStructureSpec):
    """Hold every GeneralStructure geometry field that HYDROLIB otherwise defaults."""

    upstream_1_width_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    upstream_1_level_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    upstream_2_width_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    upstream_2_level_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    crest_length_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    downstream_1_width_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    downstream_1_level_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    downstream_2_width_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    downstream_2_level_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    gate_lower_edge_level_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    gate_height_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    gate_opening_width_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    horizontal_opening_direction: GateOpeningHorizontalDirection | None = None


class GeneralOpeningCoefficients(StrictStructureSpec):
    """Hold the full directional coefficient set required by GeneralStructure."""

    positive_free_gate: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    positive_drowned_gate: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    positive_free_weir: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    positive_drowned_weir: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    positive_free_gate_contraction: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    negative_free_gate: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    negative_drowned_gate: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    negative_free_weir: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    negative_drowned_weir: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    negative_free_gate_contraction: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    extra_resistance: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )


class GateHydraulicSpec(StrictStructureSpec):
    """Represent a Gate independently of any D-Flow file or Python object model.

    ``gate_subtype`` deliberately remains a string. The domain can preserve a future
    subtype while an engine mapper rejects it with a stable fail-closed code.
    """

    structure_id: str = Field(min_length=1, max_length=256)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    branch_id: str = Field(min_length=1, max_length=256)
    chainage_m: FiniteFloat = Field(ge=0.0)
    gate_subtype: str = Field(min_length=1, max_length=64)
    crest_level_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    crest_width_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    opening_m: SourcedHydraulicScalar = Field(default_factory=SourcedHydraulicScalar)
    maximum_opening_m: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    allowed_flow_direction: StructureFlowDirection | None = None
    use_velocity_height: bool | None = None
    correction_coefficient: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    general_geometry: GeneralOpeningGeometry | None = None
    general_coefficients: GeneralOpeningCoefficients | None = None
    maximum_opening_axis: Literal["vertical", "horizontal"] | None = None

    @classmethod
    def parse_snapshot(cls, payload: Any) -> "GateHydraulicSpec":
        """Parse untrusted Gate data and expose stable syntax/subtype errors."""

        subtype = payload.get("gate_subtype") if isinstance(payload, dict) else None
        if subtype not in {"vertical_underflow_gate", "general_opening"}:
            raise Hydraulic1DValidationError(
                "GATE_SUBTYPE_UNSUPPORTED",
                f"gate subtype {subtype!r} has no audited D-Flow representation",
                field_path="gate_subtype",
            )
        try:
            return cls.model_validate(payload)
        except Exception as exc:
            raise Hydraulic1DValidationError(
                "GATE_SPEC_INVALID",
                str(exc),
                field_path="gate",
            ) from exc


class PumpOrientation(str, Enum):
    """Identify suction-to-delivery direction relative to increasing branch chainage."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class PumpTransferType(str, Enum):
    """Distinguish the inline native Pump from unsupported transfer semantics."""

    INLINE_BRANCH = "inline_branch"
    INTER_BASIN = "inter_basin"
    EXTERNAL_INFLOW = "external_inflow"
    EXTERNAL_OUTFLOW = "external_outflow"


class PumpControlMode(str, Enum):
    """Separate aggregate Capacity control from unsupported unit-count control."""

    AGGREGATE_CAPACITY = "aggregate_capacity"
    UNIT_COUNT = "unit_count"


class PumpHeadReductionPoint(StrictStructureSpec):
    """Define one delivery-minus-suction head and capacity reduction factor."""

    head_m: FiniteFloat
    reduction_factor: FiniteFloat = Field(ge=0.0, le=1.0)


class PumpHeadReductionCurve(StrictStructureSpec):
    """Carry an explicit Q-H reduction relationship and its provenance."""

    status: HydraulicDataStatus = HydraulicDataStatus.UNKNOWN
    points: tuple[PumpHeadReductionPoint, ...] = ()
    evidence: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_curve(self) -> Self:
        """Require increasing head samples when a real or synthetic curve is claimed."""

        if self.status == HydraulicDataStatus.UNKNOWN:
            if self.points:
                raise ValueError("UNKNOWN pump curve must not contain points")
            return self
        if len(self.points) < 2:
            raise ValueError(
                "known pump head/reduction curve requires at least two points"
            )
        if self.evidence is None:
            raise ValueError(f"{self.status.value} pump curve requires evidence")
        heads = [point.head_m for point in self.points]
        if any(right <= left for left, right in zip(heads, heads[1:])):
            raise ValueError("pump curve heads must be strictly increasing")
        return self


class PumpHydraulicSpec(StrictStructureSpec):
    """Represent one aggregate inline Pump while preserving unsupported semantics."""

    structure_id: str = Field(min_length=1, max_length=256)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    branch_id: str = Field(min_length=1, max_length=256)
    chainage_m: FiniteFloat = Field(ge=0.0)
    transfer_type: PumpTransferType
    intake_id: str = Field(min_length=1, max_length=256)
    outlet_id: str = Field(min_length=1, max_length=256)
    orientation: PumpOrientation
    unit_count: int = Field(ge=1)
    control_mode: PumpControlMode
    aggregate_capacity_m3s: SourcedHydraulicScalar = Field(
        default_factory=SourcedHydraulicScalar
    )
    availability: SourcedHydraulicBoolean = Field(
        default_factory=SourcedHydraulicBoolean
    )
    head_reduction_curve: PumpHeadReductionCurve = Field(
        default_factory=PumpHeadReductionCurve
    )
    native_num_stages: Literal[0] = 0
    capacity_is_actual_discharge: Literal[False] = False

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        """Require distinct intake and outlet identities without inferring topology."""

        if self.intake_id == self.outlet_id:
            raise ValueError("pump intake_id and outlet_id must be distinct")
        return self

    @classmethod
    def parse_snapshot(cls, payload: Any) -> "PumpHydraulicSpec":
        """Parse untrusted Pump data under one stable solver-neutral error code."""

        try:
            return cls.model_validate(payload)
        except Exception as exc:
            raise Hydraulic1DValidationError(
                "PUMP_SPEC_INVALID",
                str(exc),
                field_path="pump",
            ) from exc


__all__ = [
    "GateHydraulicSpec",
    "GateOpeningHorizontalDirection",
    "GeneralOpeningCoefficients",
    "GeneralOpeningGeometry",
    "HydraulicDataStatus",
    "PumpControlMode",
    "PumpHeadReductionCurve",
    "PumpHeadReductionPoint",
    "PumpHydraulicSpec",
    "PumpOrientation",
    "PumpTransferType",
    "SourcedHydraulicBoolean",
    "SourcedHydraulicScalar",
    "StructureFlowDirection",
]
