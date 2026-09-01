"""Verify versioned solver capability decisions and fail-closed reports."""

from __future__ import annotations

import pytest

from model.hydraulic_1d import HydraulicStructure
from model.hydraulic_1d.capabilities import (
    CapabilityStatus,
    capabilities_for,
    compatibility_report,
    required_capabilities,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.mascaret.adapter import MascaretModelValidator
from tests.benchmark.hydraulic_1d.network.cases import (
    n01_confluence,
    n05_combined_boundaries,
    s01_broad_crested_weir,
)


def test_pinned_mascaret_matrix_has_unique_versioned_features() -> None:
    """Keep every public capability decision tied to one adapter/runtime tuple."""

    capabilities = capabilities_for("mascaret", "v9.1.1")
    assert capabilities
    assert {item.adapter_version for item in capabilities} == {
        "dayu-mascaret-adapter-v2"
    }
    assert len({item.feature for item in capabilities}) == len(capabilities)
    assert next(item for item in capabilities if item.feature == "GATE").status == (
        CapabilityStatus.UNSUPPORTED
    )
    assert next(item for item in capabilities if item.feature == "PUMP").status == (
        CapabilityStatus.UNSUPPORTED
    )


def test_model_features_are_derived_without_solver_specific_fields() -> None:
    """Derive topology, combined-boundary, and structure requirements centrally."""

    assert "BRANCHED_NETWORK" in required_capabilities(n01_confluence().model)
    assert {"BRANCHED_NETWORK", "LATERAL_INFLOW", "COMBINED_BOUNDARIES"}.issubset(
        required_capabilities(n05_combined_boundaries().model)
    )
    assert "WEIR" in required_capabilities(s01_broad_crested_weir().model)


@pytest.mark.parametrize("kind", ["bridge", "culvert", "gate", "pump"])
def test_unverified_or_unsupported_structures_fail_before_runtime(kind: str) -> None:
    """Return structure identities and evidence state in compatibility errors."""

    source = n01_confluence().model
    structure = HydraulicStructure(
        id=f"{kind}-blocked",
        branch_id="branch-c",
        kind=kind,
        chainage_m=500.0,
    )
    model = source.model_copy(update={"structures": (structure,)})
    report = compatibility_report(model, engine="mascaret", engine_version="v9.1.1")
    issue = next(item for item in report["issues"] if item["feature"] == kind.upper())
    assert issue["structure_ids"] == [f"{kind}-blocked"]
    with pytest.raises(Hydraulic1DValidationError, match="MODEL_ENGINE_INCOMPATIBLE"):
        MascaretModelValidator().validate(model)
