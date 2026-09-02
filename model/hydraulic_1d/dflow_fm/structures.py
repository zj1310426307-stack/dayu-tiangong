"""Strict HYDROLIB-core 1.0.1 mapping for audited D-Flow Gate/Pump subsets."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from math import isclose
from typing import Any, Mapping

from model.hydraulic_1d.errors import (
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.structures import (
    GateHydraulicSpec,
    GeneralOpeningCoefficients,
    GeneralOpeningGeometry,
    HydraulicDataStatus,
    PumpControlMode,
    PumpHydraulicSpec,
    PumpTransferType,
    SourcedHydraulicBoolean,
    SourcedHydraulicScalar,
)


HYDROLIB_CORE_REQUIRED_VERSION = "1.0.1"
PUMP_CAPACITY_SEMANTICS = "PRESCRIBED_CAPACITY_NOT_ACTUAL_DISCHARGE"


@dataclass(frozen=True)
class _HydrolibStructureTypes:
    """Keep optional HYDROLIB imports outside the solver-neutral model boundary."""

    orifice: type[Any]
    general_structure: type[Any]
    pump: type[Any]


def _load_hydrolib_structure_types() -> _HydrolibStructureTypes:
    """Import only the pinned HYDROLIB release and fail closed on drift or absence."""

    try:
        installed_version = metadata.version("hydrolib-core")
    except metadata.PackageNotFoundError as exc:
        raise Hydraulic1DRuntimeUnavailable(
            "HYDROLIB-core 1.0.1 is required for D-Flow structure mapping",
            code="DFLOW_HYDROLIB_CORE_NOT_AVAILABLE",
        ) from exc
    if installed_version != HYDROLIB_CORE_REQUIRED_VERSION:
        raise Hydraulic1DRuntimeUnavailable(
            (
                "D-Flow structure mapping is locked to HYDROLIB-core "
                f"{HYDROLIB_CORE_REQUIRED_VERSION}, found {installed_version}"
            ),
            code="DFLOW_HYDROLIB_CORE_VERSION_MISMATCH",
        )
    try:
        from hydrolib.core.dflowfm.structure.models import (
            GeneralStructure,
            Orifice,
            Pump,
        )
    except ImportError as exc:
        raise Hydraulic1DRuntimeUnavailable(
            "HYDROLIB-core structure models could not be imported",
            code="DFLOW_HYDROLIB_CORE_NOT_AVAILABLE",
        ) from exc
    return _HydrolibStructureTypes(
        orifice=Orifice,
        general_structure=GeneralStructure,
        pump=Pump,
    )


def _known_scalar(
    item: SourcedHydraulicScalar,
    *,
    code: str,
    field_path: str,
) -> float:
    """Resolve an evidenced scalar or raise the caller's stable missing-data code."""

    if item.status == HydraulicDataStatus.UNKNOWN or item.value is None:
        raise Hydraulic1DValidationError(
            code,
            f"{field_path} is UNKNOWN; no D-Flow engineering default will be used",
            field_path=field_path,
        )
    return float(item.value)


def _known_boolean(
    item: SourcedHydraulicBoolean,
    *,
    code: str,
    field_path: str,
) -> bool:
    """Resolve an evidenced boolean while keeping UNKNOWN distinct from false."""

    if item.status == HydraulicDataStatus.UNKNOWN or item.value is None:
        raise Hydraulic1DValidationError(
            code,
            f"{field_path} is UNKNOWN; no D-Flow engineering default will be used",
            field_path=field_path,
        )
    return item.value


def _require_positive(value: float, field_path: str, code: str) -> None:
    """Reject zero or negative lengths/capacities with a stable mapper error."""

    if value <= 0.0:
        raise Hydraulic1DValidationError(
            code,
            f"{field_path} must be greater than zero",
            field_path=field_path,
        )


def _require_nonnegative(value: float, field_path: str, code: str) -> None:
    """Reject a negative opening or resistance before HYDROLIB construction."""

    if value < 0.0:
        raise Hydraulic1DValidationError(
            code,
            f"{field_path} must be nonnegative",
            field_path=field_path,
        )


class DFlowFMStructureMapper:
    """Map only audited Gate/Pump subsets to HYDROLIB-core typed structures."""

    def map_gate(self, source: GateHydraulicSpec | Mapping[str, Any]) -> Any:
        """Map a vertical underflow Gate or fully explicit general opening."""

        spec = (
            source
            if isinstance(source, GateHydraulicSpec)
            else GateHydraulicSpec.parse_snapshot(dict(source))
        )
        if spec.gate_subtype == "vertical_underflow_gate":
            native_values = self._validate_vertical_underflow_gate(spec)
            native_types = _load_hydrolib_structure_types()
            try:
                return native_types.orifice(**native_values)
            except Exception as exc:
                raise Hydraulic1DValidationError(
                    "GATE_NATIVE_MODEL_INVALID",
                    str(exc),
                    field_path=f"gate[{spec.structure_id}]",
                ) from exc
        if spec.gate_subtype == "general_opening":
            native_values = self._validate_general_opening(spec)
            native_types = _load_hydrolib_structure_types()
            try:
                native = native_types.general_structure(**native_values)
                self._restore_general_structure_discriminator(native)
                return native
            except Exception as exc:
                raise Hydraulic1DValidationError(
                    "GATE_NATIVE_MODEL_INVALID",
                    str(exc),
                    field_path=f"gate[{spec.structure_id}]",
                ) from exc
        raise Hydraulic1DValidationError(
            "GATE_SUBTYPE_UNSUPPORTED",
            f"gate subtype {spec.gate_subtype!r} has no audited D-Flow representation",
            field_path="gate_subtype",
        )

    @staticmethod
    def _restore_general_structure_discriminator(native: Any) -> None:
        """Work around HYDROLIB 1.0.1 lowercasing its own union discriminator.

        ``GeneralStructure`` inherits a validator that changes ``generalStructure``
        to ``generalstructure`` after construction, while ``StructureModel`` in the
        same release discriminates only on ``generalStructure``. Restoring the exact
        declared tag keeps the typed object admissible to the official writer.
        """

        native_type = getattr(native, "type", None)
        if native_type is None:
            # Dependency-free constructor fakes do not expose validated attributes.
            return
        if native_type == "generalstructure":
            # Normal assignment re-runs the same lowercasing validator, so the
            # version-specific compatibility correction must bypass assignment.
            object.__setattr__(native, "type", "generalStructure")
            native_type = native.type
        if native_type != "generalStructure":
            raise ValueError(
                "HYDROLIB GeneralStructure returned an unexpected type discriminator "
                f"{native_type!r}"
            )

    def map_pump(self, source: PumpHydraulicSpec | Mapping[str, Any]) -> Any:
        """Map only a non-staged inline Pump controlled by aggregate Capacity."""

        spec = (
            source
            if isinstance(source, PumpHydraulicSpec)
            else PumpHydraulicSpec.parse_snapshot(dict(source))
        )
        if spec.transfer_type != PumpTransferType.INLINE_BRANCH:
            raise Hydraulic1DValidationError(
                "PUMP_TRANSFER_TYPE_UNSUPPORTED",
                (
                    f"transfer type {spec.transfer_type.value} is not the native "
                    "inline branch Pump representation"
                ),
                field_path="transfer_type",
            )
        if spec.control_mode != PumpControlMode.AGGREGATE_CAPACITY:
            raise Hydraulic1DValidationError(
                "PUMP_UNIT_COUNT_CONTROL_UNSUPPORTED",
                "unit_count must not be converted to aggregate D-Flow Capacity",
                field_path="control_mode",
            )
        capacity = _known_scalar(
            spec.aggregate_capacity_m3s,
            code="PUMP_CAPACITY_REQUIRED",
            field_path="aggregate_capacity_m3s",
        )
        _require_positive(capacity, "aggregate_capacity_m3s", "PUMP_SPEC_INVALID")
        available = _known_boolean(
            spec.availability,
            code="PUMP_AVAILABILITY_REQUIRED",
            field_path="availability",
        )
        curve = spec.head_reduction_curve
        if curve.status == HydraulicDataStatus.UNKNOWN or len(curve.points) < 2:
            raise Hydraulic1DValidationError(
                "PUMP_HEAD_REDUCTION_CURVE_REQUIRED",
                "an explicit sourced or synthetic head/reduction curve is required",
                field_path="head_reduction_curve",
            )
        native_capacity = capacity if available else 0.0
        native_types = _load_hydrolib_structure_types()
        try:
            return native_types.pump(
                type="pump",
                id=spec.structure_id,
                name=spec.name or spec.structure_id,
                branchId=spec.branch_id,
                chainage=float(spec.chainage_m),
                orientation=spec.orientation.value,
                numStages=0,
                capacity=native_capacity,
                numReductionLevels=len(curve.points),
                head=[float(point.head_m) for point in curve.points],
                reductionFactor=[
                    float(point.reduction_factor) for point in curve.points
                ],
            )
        except Exception as exc:
            raise Hydraulic1DValidationError(
                "PUMP_NATIVE_MODEL_INVALID",
                str(exc),
                field_path=f"pump[{spec.structure_id}]",
            ) from exc

    @staticmethod
    def _validate_gate_common(spec: GateHydraulicSpec) -> dict[str, Any]:
        """Resolve shared Gate geometry and direction without HYDROLIB defaults."""

        crest_level = _known_scalar(
            spec.crest_level_m,
            code="GATE_REQUIRED_FIELD_MISSING",
            field_path="crest_level_m",
        )
        crest_width = _known_scalar(
            spec.crest_width_m,
            code="GATE_REQUIRED_FIELD_MISSING",
            field_path="crest_width_m",
        )
        opening = _known_scalar(
            spec.opening_m,
            code="GATE_REQUIRED_FIELD_MISSING",
            field_path="opening_m",
        )
        maximum_opening = _known_scalar(
            spec.maximum_opening_m,
            code="GATE_REQUIRED_FIELD_MISSING",
            field_path="maximum_opening_m",
        )
        _require_positive(crest_width, "crest_width_m", "GATE_SPEC_INVALID")
        _require_nonnegative(opening, "opening_m", "GATE_SPEC_INVALID")
        _require_positive(maximum_opening, "maximum_opening_m", "GATE_SPEC_INVALID")
        if opening > maximum_opening:
            raise Hydraulic1DValidationError(
                "GATE_OPENING_OUT_OF_RANGE",
                "opening_m exceeds maximum_opening_m",
                field_path="opening_m",
            )
        if spec.allowed_flow_direction is None:
            raise Hydraulic1DValidationError(
                "GATE_REQUIRED_FIELD_MISSING",
                "allowed_flow_direction is required",
                field_path="allowed_flow_direction",
            )
        if spec.use_velocity_height is None:
            raise Hydraulic1DValidationError(
                "GATE_REQUIRED_FIELD_MISSING",
                "use_velocity_height is required",
                field_path="use_velocity_height",
            )
        return {
            "crest_level": crest_level,
            "crest_width": crest_width,
            "opening": opening,
            "maximum_opening": maximum_opening,
        }

    def _validate_vertical_underflow_gate(
        self, spec: GateHydraulicSpec
    ) -> dict[str, Any]:
        """Compile the audited rectangular vertical Gate subset to Orifice."""

        common = self._validate_gate_common(spec)
        if spec.maximum_opening_axis != "vertical":
            raise Hydraulic1DValidationError(
                "GATE_SPEC_INVALID",
                "vertical_underflow_gate requires maximum_opening_axis='vertical'",
                field_path="maximum_opening_axis",
            )
        if spec.general_geometry is not None or spec.general_coefficients is not None:
            raise Hydraulic1DValidationError(
                "GATE_SPEC_INVALID",
                "vertical_underflow_gate must not contain GeneralStructure fields",
                field_path="general_geometry",
            )
        correction = _known_scalar(
            spec.correction_coefficient,
            code="GATE_COEFFICIENT_UNKNOWN",
            field_path="correction_coefficient",
        )
        _require_positive(correction, "correction_coefficient", "GATE_SPEC_INVALID")
        return {
            "type": "orifice",
            "id": spec.structure_id,
            "name": spec.name or spec.structure_id,
            "branchId": spec.branch_id,
            "chainage": float(spec.chainage_m),
            "allowedFlowDir": spec.allowed_flow_direction.value,
            "crestLevel": common["crest_level"],
            "crestWidth": common["crest_width"],
            "gateLowerEdgeLevel": common["crest_level"] + common["opening"],
            "corrCoeff": correction,
            "useVelocityHeight": spec.use_velocity_height,
            "useLimitFlowPos": False,
            "useLimitFlowNeg": False,
        }

    def _validate_general_opening(self, spec: GateHydraulicSpec) -> dict[str, Any]:
        """Compile only a complete GeneralStructure geometry and coefficient set."""

        common = self._validate_gate_common(spec)
        geometry = spec.general_geometry
        coefficients = spec.general_coefficients
        if geometry is None:
            raise Hydraulic1DValidationError(
                "GATE_REQUIRED_FIELD_MISSING",
                "general_geometry is required for general_opening",
                field_path="general_geometry",
            )
        if coefficients is None:
            raise Hydraulic1DValidationError(
                "GATE_COEFFICIENT_UNKNOWN",
                "general_coefficients are required for general_opening",
                field_path="general_coefficients",
            )
        if spec.correction_coefficient.status != HydraulicDataStatus.UNKNOWN:
            raise Hydraulic1DValidationError(
                "GATE_SPEC_INVALID",
                "general_opening must use its directional coefficient set, not corrCoeff",
                field_path="correction_coefficient",
            )
        geometry_values = self._general_geometry_values(geometry)
        coefficient_values = self._general_coefficient_values(coefficients)
        self._validate_general_opening_extent(spec, common, geometry_values)
        return {
            "type": "generalStructure",
            "id": spec.structure_id,
            "name": spec.name or spec.structure_id,
            "branchId": spec.branch_id,
            "chainage": float(spec.chainage_m),
            "allowedFlowDir": spec.allowed_flow_direction.value,
            "upstream1Width": geometry_values["upstream_1_width_m"],
            "upstream1Level": geometry_values["upstream_1_level_m"],
            "upstream2Width": geometry_values["upstream_2_width_m"],
            "upstream2Level": geometry_values["upstream_2_level_m"],
            "crestWidth": common["crest_width"],
            "crestLevel": common["crest_level"],
            "crestLength": geometry_values["crest_length_m"],
            "downstream1Width": geometry_values["downstream_1_width_m"],
            "downstream1Level": geometry_values["downstream_1_level_m"],
            "downstream2Width": geometry_values["downstream_2_width_m"],
            "downstream2Level": geometry_values["downstream_2_level_m"],
            "gateLowerEdgeLevel": geometry_values["gate_lower_edge_level_m"],
            "posFreeGateFlowCoeff": coefficient_values["positive_free_gate"],
            "posDrownGateFlowCoeff": coefficient_values["positive_drowned_gate"],
            "posFreeWeirFlowCoeff": coefficient_values["positive_free_weir"],
            "posDrownWeirFlowCoeff": coefficient_values["positive_drowned_weir"],
            "posContrCoefFreeGate": coefficient_values[
                "positive_free_gate_contraction"
            ],
            "negFreeGateFlowCoeff": coefficient_values["negative_free_gate"],
            "negDrownGateFlowCoeff": coefficient_values["negative_drowned_gate"],
            "negFreeWeirFlowCoeff": coefficient_values["negative_free_weir"],
            "negDrownWeirFlowCoeff": coefficient_values["negative_drowned_weir"],
            "negContrCoefFreeGate": coefficient_values[
                "negative_free_gate_contraction"
            ],
            "extraResistance": coefficient_values["extra_resistance"],
            "gateHeight": geometry_values["gate_height_m"],
            "gateOpeningWidth": geometry_values["gate_opening_width_m"],
            "gateOpeningHorizontalDirection": (
                geometry.horizontal_opening_direction.value
            ),
            "useVelocityHeight": spec.use_velocity_height,
        }

    @staticmethod
    def _general_geometry_values(
        geometry: GeneralOpeningGeometry,
    ) -> dict[str, float]:
        """Resolve all GeneralStructure geometry fields and reject any UNKNOWN value."""

        values: dict[str, float] = {}
        for field_name in (
            "upstream_1_width_m",
            "upstream_1_level_m",
            "upstream_2_width_m",
            "upstream_2_level_m",
            "crest_length_m",
            "downstream_1_width_m",
            "downstream_1_level_m",
            "downstream_2_width_m",
            "downstream_2_level_m",
            "gate_lower_edge_level_m",
            "gate_height_m",
            "gate_opening_width_m",
        ):
            values[field_name] = _known_scalar(
                getattr(geometry, field_name),
                code="GATE_REQUIRED_FIELD_MISSING",
                field_path=f"general_geometry.{field_name}",
            )
        if geometry.horizontal_opening_direction is None:
            raise Hydraulic1DValidationError(
                "GATE_REQUIRED_FIELD_MISSING",
                "horizontal_opening_direction is required",
                field_path="general_geometry.horizontal_opening_direction",
            )
        for field_name in (
            "upstream_1_width_m",
            "upstream_2_width_m",
            "downstream_1_width_m",
            "downstream_2_width_m",
            "gate_height_m",
        ):
            _require_positive(values[field_name], field_name, "GATE_SPEC_INVALID")
        for field_name in ("crest_length_m", "gate_opening_width_m"):
            _require_nonnegative(values[field_name], field_name, "GATE_SPEC_INVALID")
        return values

    @staticmethod
    def _general_coefficient_values(
        coefficients: GeneralOpeningCoefficients,
    ) -> dict[str, float]:
        """Resolve all directional coefficients instead of accepting model defaults."""

        values: dict[str, float] = {}
        for field_name in coefficients.__class__.model_fields:
            values[field_name] = _known_scalar(
                getattr(coefficients, field_name),
                code="GATE_COEFFICIENT_UNKNOWN",
                field_path=f"general_coefficients.{field_name}",
            )
            _require_nonnegative(
                values[field_name],
                f"general_coefficients.{field_name}",
                "GATE_SPEC_INVALID",
            )
        for contraction_name in (
            "positive_free_gate_contraction",
            "negative_free_gate_contraction",
        ):
            if values[contraction_name] > 1.0:
                raise Hydraulic1DValidationError(
                    "GATE_SPEC_INVALID",
                    f"{contraction_name} must lie in [0, 1]",
                    field_path=f"general_coefficients.{contraction_name}",
                )
        return values

    @staticmethod
    def _validate_general_opening_extent(
        spec: GateHydraulicSpec,
        common: dict[str, Any],
        geometry: dict[str, float],
    ) -> None:
        """Tie the neutral opening value to one explicit GeneralStructure control axis."""

        axis = spec.maximum_opening_axis
        if axis == "vertical":
            represented_opening = (
                geometry["gate_lower_edge_level_m"] - common["crest_level"]
            )
            _require_nonnegative(
                represented_opening,
                "general_geometry.gate_lower_edge_level_m",
                "GATE_SPEC_INVALID",
            )
        elif axis == "horizontal":
            represented_opening = geometry["gate_opening_width_m"]
        else:
            raise Hydraulic1DValidationError(
                "GATE_REQUIRED_FIELD_MISSING",
                "general_opening requires an explicit maximum_opening_axis",
                field_path="maximum_opening_axis",
            )
        if not isclose(
            represented_opening,
            common["opening"],
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise Hydraulic1DValidationError(
                "GATE_OPENING_GEOMETRY_MISMATCH",
                "opening_m does not match the explicit GeneralStructure opening axis",
                field_path="opening_m",
            )
        if geometry["gate_opening_width_m"] > common["crest_width"]:
            raise Hydraulic1DValidationError(
                "GATE_OPENING_OUT_OF_RANGE",
                "gate_opening_width_m exceeds crest_width_m",
                field_path="general_geometry.gate_opening_width_m",
            )
        if axis == "horizontal" and common["maximum_opening"] > common["crest_width"]:
            raise Hydraulic1DValidationError(
                "GATE_OPENING_OUT_OF_RANGE",
                "horizontal maximum_opening_m exceeds crest_width_m",
                field_path="maximum_opening_m",
            )
        if axis == "vertical" and common["maximum_opening"] > geometry["gate_height_m"]:
            raise Hydraulic1DValidationError(
                "GATE_OPENING_OUT_OF_RANGE",
                "vertical maximum_opening_m exceeds gate_height_m",
                field_path="maximum_opening_m",
            )


__all__ = [
    "DFlowFMStructureMapper",
    "HYDROLIB_CORE_REQUIRED_VERSION",
    "PUMP_CAPACITY_SEMANTICS",
]
