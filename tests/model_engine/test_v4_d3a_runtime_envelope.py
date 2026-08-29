"""Backend persistence gates for D3A RC1 runtime-envelope evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.model_engine.v4_result import validate_v4_result
from model.adapters import project_v4_to_v4_lite, run_v4_lite
from model.solver.registry import D3A_3_CAPABILITY_ID, resolve_capability
from tests.model_engine.helpers import native_v4_d3a_3_payload


def test_native_d3a_result_revalidates_dynamic_envelope_before_persistence() -> None:
    """A genuine result passes while forged envelope status/extrema fail closed."""

    projection = project_v4_to_v4_lite(native_v4_d3a_3_payload())
    document = run_v4_lite(projection.runtime_snapshot).to_dict()
    validate_v4_result(document, projection)

    capability = resolve_capability(D3A_3_CAPABILITY_ID)
    diagnostics = document["diagnostics"]
    provenance = document["provenance"]
    assert diagnostics["runtime_envelope_status"] == "pass"
    assert diagnostics["minimum_water_depth_m"] > 1.0e-3
    assert diagnostics["minimum_discharge_m3s"] >= -1.0e-12
    assert diagnostics["maximum_froude_number"] <= 0.8 + 1.0e-12
    assert provenance["runtime_envelope_id"] == capability.runtime_envelope_id
    assert provenance["runtime_envelope_hash"] == capability.runtime_envelope_hash

    forged_status = deepcopy(document)
    forged_status["diagnostics"]["runtime_envelope_status"] = "fail"
    with pytest.raises(ValueError, match="runtime-envelope diagnostics"):
        validate_v4_result(forged_status, projection)

    forged_froude = deepcopy(document)
    forged_froude["diagnostics"]["maximum_froude_number"] = 0.81
    with pytest.raises(ValueError, match="runtime-envelope diagnostics"):
        validate_v4_result(forged_froude, projection)

    forged_provenance = deepcopy(document)
    forged_provenance["provenance"]["runtime_envelope_hash"] = "0" * 64
    with pytest.raises(ValueError, match="runtime-envelope provenance"):
        validate_v4_result(forged_provenance, projection)
