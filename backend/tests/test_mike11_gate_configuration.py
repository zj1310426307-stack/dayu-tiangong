"""Contract tests for MIKE11-style Gate database inputs."""

import pytest
from pydantic import ValidationError

from app.hydraulic.engineering import (
    _mike11_gate_configuration,
    _stored_hydraulic_parameters,
    _validate_mike11_gate_authority,
)
from app.hydraulic.models import HydraulicStructure
from app.hydraulic.schemas import HydraulicStructureCreate, Mike11GateConfiguration


def _underflow_configuration() -> Mike11GateConfiguration:
    """Return one complete MIKE11 Underflow example using screenshot defaults."""

    return Mike11GateConfiguration(
        gate_type="underflow",
        number_of_gates=1,
        underflow_discharge_coefficient=0.63,
        maximum_speed_m_per_s=0.001,
        initial_value_m=0.0,
        maximum_value_m=1.0,
        marker_2_horizontal_offset_m=0.0,
        graphic_gate_height_or_opening_m=1.0,
        control_definitions=[
            {
                "priority": 1,
                "calculation_mode": "tabulated",
                "control_type": "H",
                "target_type": "GateL",
                "scaling_type": "none",
                "value": 0.0,
            }
        ],
    )


def test_mike11_gate_defaults_preserve_bidirectional_loss_factors() -> None:
    """The six MIKE11 loss coefficients retain their independent default values."""

    configuration = _underflow_configuration()

    assert configuration.head_loss_factors.model_dump() == {
        "positive_inflow": 0.5,
        "positive_outflow": 1.0,
        "positive_free_overflow": 1.0,
        "negative_inflow": 0.5,
        "negative_outflow": 1.0,
        "negative_free_overflow": 1.0,
    }


def test_mike11_underflow_requires_coefficient_and_unique_priorities() -> None:
    """Incomplete Underflow and ambiguous control precedence fail at the API boundary."""

    with pytest.raises(ValidationError, match="underflow_discharge_coefficient"):
        Mike11GateConfiguration(gate_type="underflow")
    with pytest.raises(ValidationError, match="priorities must be unique"):
        Mike11GateConfiguration(
            gate_type="overflow",
            control_definitions=[
                {"priority": 1},
                {"priority": 1},
            ],
        )


def test_structure_create_allows_derived_location_but_rejects_partial_xy() -> None:
    """Branch plus chainage may derive geometry, while manual XY remains an atomic pair."""

    minimal = {
        "dataset_version_id": 1,
        "network_id": 2,
        "branch_id": 3,
        "structure_code": "G-01",
        "structure_name": "Test gate",
        "structure_type": "gate",
        "chainage_m": 10.0,
    }
    assert HydraulicStructureCreate(**minimal).x is None
    with pytest.raises(ValidationError, match="x and y must be supplied together"):
        HydraulicStructureCreate(**minimal, x=112.0)


def test_mike11_reserved_payload_round_trips_through_typed_contract() -> None:
    """Persistence keeps one validated nested payload and blocks raw-key bypasses."""

    configuration = _underflow_configuration()
    stored = _stored_hydraulic_parameters(
        {"correction_coefficient": 0.63}, configuration
    )

    assert _mike11_gate_configuration(stored) == configuration
    with pytest.raises(ValueError, match="MIKE11_GATE_CONFIGURATION_RESERVED"):
        _stored_hydraulic_parameters(
            {"mike11_gate_configuration": {"gate_type": "overflow"}}, None
        )


def test_mike11_duplicate_solver_values_must_agree() -> None:
    """MIKE11 and D-Flow-facing fields cannot silently disagree in one Gate row."""

    configuration = _underflow_configuration()
    structure = HydraulicStructure(
        id=9,
        dataset_version_id=3,
        network_id=4,
        branch_id=5,
        structure_code="G-01",
        structure_name="Test gate",
        structure_type="gate",
        chainage_m=10.0,
        height_m=1.2,
        hydraulic_law_type="vertical_underflow_gate",
        hydraulic_parameters=_stored_hydraulic_parameters(
            {"correction_coefficient": 0.63}, configuration
        ),
        operation_rule_type="fixed",
        operation_parameters={
            "opening_rate_limit_m_per_s": 0.001,
            "maximum_opening_m": 1.0,
        },
        status="draft",
        metadata_json={},
    )
    _validate_mike11_gate_authority(structure)

    structure.operation_parameters = {
        **structure.operation_parameters,
        "maximum_opening_m": 0.8,
    }
    with pytest.raises(ValueError, match="maximum_opening_m conflicts"):
        _validate_mike11_gate_authority(structure)
