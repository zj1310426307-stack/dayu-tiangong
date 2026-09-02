"""Verify fail-closed Gate/Pump mapping and optional HYDROLIB round trips."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import model.hydraulic_1d.dflow_fm.structures as mapping_module
from model.hydraulic_1d.dflow_fm.structures import (
    DFlowFMStructureMapper,
    PUMP_CAPACITY_SEMANTICS,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.structures import (
    GateHydraulicSpec,
    GateOpeningHorizontalDirection,
    GeneralOpeningCoefficients,
    GeneralOpeningGeometry,
    HydraulicDataStatus,
    PumpControlMode,
    PumpHeadReductionCurve,
    PumpHeadReductionPoint,
    PumpHydraulicSpec,
    PumpOrientation,
    PumpTransferType,
    SourcedHydraulicBoolean,
    SourcedHydraulicScalar,
    StructureFlowDirection,
)


pytestmark = pytest.mark.engineering_structure
HYDROLIB_SKIP_REASON = "HYDROLIB-core 1.0.1 is not installed for typed round-trip tests"
HYDROLIB_AVAILABLE = find_spec("hydrolib") is not None


class _FakeNativeStructure:
    """Capture typed-constructor keyword arguments in dependency-free unit tests."""

    def __init__(self, **values: Any) -> None:
        """Expose mapper output without supplying HYDROLIB defaults."""

        self.values = values


def _fake_hydrolib_types() -> SimpleNamespace:
    """Return fake constructors with the same three mapper-facing roles."""

    return SimpleNamespace(
        orifice=_FakeNativeStructure,
        general_structure=_FakeNativeStructure,
        pump=_FakeNativeStructure,
    )


def _synthetic(value: float) -> SourcedHydraulicScalar:
    """Create one visibly synthetic scalar for mapping fixtures."""

    return SourcedHydraulicScalar.synthetic(value, "synthetic G/P mapper fixture")


def _vertical_gate(**updates: Any) -> GateHydraulicSpec:
    """Build the complete audited Orifice subset and apply selected test changes."""

    values: dict[str, Any] = {
        "structure_id": "gate-v-1",
        "name": "Vertical gate",
        "branch_id": "branch-1",
        "chainage_m": 125.0,
        "gate_subtype": "vertical_underflow_gate",
        "crest_level_m": _synthetic(2.0),
        "crest_width_m": _synthetic(3.5),
        "opening_m": _synthetic(0.4),
        "maximum_opening_m": _synthetic(1.2),
        "allowed_flow_direction": StructureFlowDirection.BOTH,
        "use_velocity_height": False,
        "correction_coefficient": _synthetic(0.61),
        "maximum_opening_axis": "vertical",
    }
    values.update(updates)
    return GateHydraulicSpec(**values)


def _general_geometry(**updates: Any) -> GeneralOpeningGeometry:
    """Build a fully explicit GeneralStructure geometry fixture."""

    values: dict[str, Any] = {
        "upstream_1_width_m": _synthetic(5.0),
        "upstream_1_level_m": _synthetic(1.0),
        "upstream_2_width_m": _synthetic(4.5),
        "upstream_2_level_m": _synthetic(1.2),
        "crest_length_m": _synthetic(0.8),
        "downstream_1_width_m": _synthetic(5.2),
        "downstream_1_level_m": _synthetic(0.9),
        "downstream_2_width_m": _synthetic(4.7),
        "downstream_2_level_m": _synthetic(1.1),
        "gate_lower_edge_level_m": _synthetic(2.6),
        "gate_height_m": _synthetic(1.8),
        "gate_opening_width_m": _synthetic(1.5),
        "horizontal_opening_direction": GateOpeningHorizontalDirection.SYMMETRIC,
    }
    values.update(updates)
    return GeneralOpeningGeometry(**values)


def _general_coefficients(**updates: Any) -> GeneralOpeningCoefficients:
    """Build the complete directional coefficient set with synthetic evidence."""

    values = {
        name: _synthetic(0.85 if "contraction" in name else 0.95)
        for name in GeneralOpeningCoefficients.model_fields
    }
    values["extra_resistance"] = _synthetic(0.0)
    values.update(updates)
    return GeneralOpeningCoefficients(**values)


def _general_gate(**updates: Any) -> GateHydraulicSpec:
    """Build the complete audited GeneralStructure subset."""

    values: dict[str, Any] = {
        "structure_id": "gate-g-1",
        "name": "General opening",
        "branch_id": "branch-1",
        "chainage_m": 275.0,
        "gate_subtype": "general_opening",
        "crest_level_m": _synthetic(2.0),
        "crest_width_m": _synthetic(4.0),
        "opening_m": _synthetic(1.5),
        "maximum_opening_m": _synthetic(3.0),
        "allowed_flow_direction": StructureFlowDirection.POSITIVE,
        "use_velocity_height": True,
        "general_geometry": _general_geometry(),
        "general_coefficients": _general_coefficients(),
        "maximum_opening_axis": "horizontal",
    }
    values.update(updates)
    return GateHydraulicSpec(**values)


def _pump(**updates: Any) -> PumpHydraulicSpec:
    """Build the supported aggregate, non-staged inline Pump subset."""

    values: dict[str, Any] = {
        "structure_id": "pump-1",
        "name": "Aggregate station",
        "branch_id": "transfer-branch",
        "chainage_m": 45.0,
        "transfer_type": PumpTransferType.INLINE_BRANCH,
        "intake_id": "intake-node",
        "outlet_id": "outlet-node",
        "orientation": PumpOrientation.POSITIVE,
        "unit_count": 3,
        "control_mode": PumpControlMode.AGGREGATE_CAPACITY,
        "aggregate_capacity_m3s": _synthetic(4.5),
        "availability": SourcedHydraulicBoolean.synthetic(
            True, "synthetic P mapper fixture"
        ),
        "head_reduction_curve": PumpHeadReductionCurve(
            status=HydraulicDataStatus.SYNTHETIC_ASSUMPTION,
            evidence="synthetic P mapper fixture",
            points=(
                PumpHeadReductionPoint(head_m=-1.0, reduction_factor=1.0),
                PumpHeadReductionPoint(head_m=2.0, reduction_factor=0.8),
                PumpHeadReductionPoint(head_m=5.0, reduction_factor=0.0),
            ),
        ),
    }
    values.update(updates)
    return PumpHydraulicSpec(**values)


def _install_fake_hydrolib(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only the optional import boundary for dependency-free mapper checks."""

    monkeypatch.setattr(
        mapping_module,
        "_load_hydrolib_structure_types",
        _fake_hydrolib_types,
    )


def test_specs_are_frozen_and_provenance_is_explicit() -> None:
    """Prevent mutation and prevent an UNKNOWN scalar from carrying a hidden value."""

    spec = _vertical_gate()

    with pytest.raises(ValidationError, match="frozen"):
        spec.chainage_m = 200.0  # type: ignore[misc]
    with pytest.raises(ValidationError, match="UNKNOWN hydraulic scalar"):
        SourcedHydraulicScalar(status=HydraulicDataStatus.UNKNOWN, value=1.0)


def test_gate_missing_geometry_fails_before_optional_dependency() -> None:
    """Keep an omitted crest level UNKNOWN instead of accepting HYDROLIB defaults."""

    spec = _vertical_gate(crest_level_m=SourcedHydraulicScalar())

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_gate(spec)

    assert error.value.code == "GATE_REQUIRED_FIELD_MISSING"
    assert error.value.field_path == "crest_level_m"


def test_gate_unknown_coefficient_has_stable_fail_closed_code() -> None:
    """Reject an unknown Orifice correction coefficient without substituting 1.0."""

    spec = _vertical_gate(correction_coefficient=SourcedHydraulicScalar())

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_gate(spec)

    assert error.value.code == "GATE_COEFFICIENT_UNKNOWN"


def test_unsupported_gate_subtype_has_stable_fail_closed_code() -> None:
    """Preserve future neutral subtypes while refusing an unaudited engine mapping."""

    payload = _vertical_gate().model_dump(mode="json")
    payload["gate_subtype"] = "radial_gate"

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_gate(payload)

    assert error.value.code == "GATE_SUBTYPE_UNSUPPORTED"


def test_vertical_underflow_gate_maps_every_engineering_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map the strict rectangular subset to Orifice without a hidden native default."""

    _install_fake_hydrolib(monkeypatch)

    native = DFlowFMStructureMapper().map_gate(_vertical_gate())

    assert native.values == {
        "type": "orifice",
        "id": "gate-v-1",
        "name": "Vertical gate",
        "branchId": "branch-1",
        "chainage": 125.0,
        "allowedFlowDir": "both",
        "crestLevel": 2.0,
        "crestWidth": 3.5,
        "gateLowerEdgeLevel": 2.4,
        "corrCoeff": 0.61,
        "useVelocityHeight": False,
        "useLimitFlowPos": False,
        "useLimitFlowNeg": False,
    }


def test_general_opening_requires_every_directional_coefficient() -> None:
    """Reject one UNKNOWN GeneralStructure coefficient instead of accepting 1.0."""

    coefficients = _general_coefficients(negative_drowned_gate=SourcedHydraulicScalar())
    spec = _general_gate(general_coefficients=coefficients)

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_gate(spec)

    assert error.value.code == "GATE_COEFFICIENT_UNKNOWN"
    assert error.value.field_path.endswith("negative_drowned_gate")


def test_general_opening_maps_full_geometry_and_coefficients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supply every GeneralStructure field and retain the selected opening axis."""

    _install_fake_hydrolib(monkeypatch)

    native = DFlowFMStructureMapper().map_gate(_general_gate())

    assert native.values["type"] == "generalStructure"
    assert native.values["gateOpeningWidth"] == pytest.approx(1.5)
    assert native.values["gateLowerEdgeLevel"] == pytest.approx(2.6)
    assert native.values["posFreeGateFlowCoeff"] == pytest.approx(0.95)
    assert native.values["negContrCoefFreeGate"] == pytest.approx(0.85)
    assert native.values["extraResistance"] == pytest.approx(0.0)
    assert native.values["gateOpeningHorizontalDirection"] == "symmetric"


def test_general_opening_axis_mismatch_fails_closed() -> None:
    """Do not serialize an opening command that disagrees with explicit geometry."""

    spec = _general_gate(opening_m=_synthetic(1.4))

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_gate(spec)

    assert error.value.code == "GATE_OPENING_GEOMETRY_MISMATCH"


def test_pump_requires_explicit_head_reduction_curve() -> None:
    """Reject a design capacity with no sourced or synthetic Q-H relationship."""

    spec = _pump(head_reduction_curve=PumpHeadReductionCurve())

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_pump(spec)

    assert error.value.code == "PUMP_HEAD_REDUCTION_CURVE_REQUIRED"


def test_pump_rejects_cross_basin_transfer_before_mapping() -> None:
    """Do not reinterpret an arbitrary inter-basin transfer as an inline Pump."""

    spec = _pump(transfer_type=PumpTransferType.INTER_BASIN)

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_pump(spec)

    assert error.value.code == "PUMP_TRANSFER_TYPE_UNSUPPORTED"


def test_pump_rejects_unit_count_control_before_mapping() -> None:
    """Do not multiply a per-unit command into D-Flow aggregate Capacity."""

    spec = _pump(control_mode=PumpControlMode.UNIT_COUNT)

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMStructureMapper().map_pump(spec)

    assert error.value.code == "PUMP_UNIT_COUNT_CONTROL_UNSUPPORTED"


def test_pump_maps_aggregate_capacity_without_unit_multiplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep three-unit metadata separate from the already aggregated Capacity."""

    _install_fake_hydrolib(monkeypatch)

    native = DFlowFMStructureMapper().map_pump(_pump())

    assert PUMP_CAPACITY_SEMANTICS == "PRESCRIBED_CAPACITY_NOT_ACTUAL_DISCHARGE"
    assert native.values["capacity"] == pytest.approx(4.5)
    assert native.values["numStages"] == 0
    assert native.values["numReductionLevels"] == 3
    assert native.values["head"] == pytest.approx([-1.0, 2.0, 5.0])
    assert native.values["reductionFactor"] == pytest.approx([1.0, 0.8, 0.0])


def test_unavailable_pump_maps_to_zero_requested_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Represent explicit aggregate unavailability as zero prescribed Capacity."""

    _install_fake_hydrolib(monkeypatch)
    unavailable = SourcedHydraulicBoolean.source_data(False, "station outage record")

    native = DFlowFMStructureMapper().map_pump(_pump(availability=unavailable))

    assert native.values["capacity"] == pytest.approx(0.0)


def _save_and_reload(native: Any, filepath: Path) -> Any:
    """Exercise the official typed StructureModel writer and reader."""

    from hydrolib.core.dflowfm.structure.models import StructureModel

    model = StructureModel(structure=[native])
    model.save(filepath)
    loaded = StructureModel(filepath)
    assert len(loaded.structure) == 1
    return loaded.structure[0]


@pytest.mark.skipif(not HYDROLIB_AVAILABLE, reason=HYDROLIB_SKIP_REASON)
def test_vertical_gate_hydrolib_save_load_roundtrip(tmp_path: Path) -> None:
    """Round-trip the mapped Orifice with the locked HYDROLIB implementation."""

    native = DFlowFMStructureMapper().map_gate(_vertical_gate())

    loaded = _save_and_reload(native, tmp_path / "vertical-gate.ini")

    assert loaded.type == "orifice"
    assert loaded.id == "gate-v-1"
    assert loaded.crestlevel == pytest.approx(2.0)
    assert loaded.gateloweredgelevel == pytest.approx(2.4)
    assert loaded.corrcoeff == pytest.approx(0.61)


@pytest.mark.skipif(not HYDROLIB_AVAILABLE, reason=HYDROLIB_SKIP_REASON)
def test_general_gate_hydrolib_save_load_roundtrip(tmp_path: Path) -> None:
    """Round-trip GeneralStructure while recording the 1.0.1 tag-casing defect."""

    native = DFlowFMStructureMapper().map_gate(_general_gate())
    filepath = tmp_path / "general-gate.ini"
    assert native.type == "generalStructure"

    loaded = _save_and_reload(native, filepath)

    assert "type                           = generalStructure" in filepath.read_text()
    assert loaded.__class__.__name__ == "GeneralStructure"
    # HYDROLIB-core 1.0.1 selects the correct union member and then lowercases
    # its stored type value; the mapper compensates before passing a new object
    # to StructureModel, while read-back class identity proves typed parsing.
    assert loaded.type == "generalstructure"
    assert loaded.gateopeningwidth == pytest.approx(1.5)
    assert loaded.negcontrcoeffreegate == pytest.approx(0.85)
    assert loaded.extraresistance == pytest.approx(0.0)


@pytest.mark.skipif(not HYDROLIB_AVAILABLE, reason=HYDROLIB_SKIP_REASON)
def test_pump_hydrolib_save_load_roundtrip(tmp_path: Path) -> None:
    """Round-trip a non-staged aggregate Pump and its reduction table."""

    native = DFlowFMStructureMapper().map_pump(_pump())

    loaded = _save_and_reload(native, tmp_path / "pump.ini")

    assert loaded.type == "pump"
    assert loaded.numstages == 0
    assert loaded.capacity == pytest.approx(4.5)
    assert loaded.head == pytest.approx([-1.0, 2.0, 5.0])
    assert loaded.reductionfactor == pytest.approx([1.0, 0.8, 0.0])
