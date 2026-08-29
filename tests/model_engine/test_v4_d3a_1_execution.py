"""Native authoritative-v4 execution gate for the D3A-1 capability."""

from model.adapters import project_v4_to_v4_lite, run_v4_lite
from model.solver.registry import D3A_1_CAPABILITY_ID, D3A_1_RUNTIME_ADAPTER_ID
from tests.model_engine.helpers import native_v4_d3a_1_payload


def test_native_v4_d3a_1_projects_and_executes_without_d1_inference() -> None:
    source = native_v4_d3a_1_payload()
    projection = project_v4_to_v4_lite(source)
    assert projection.source.solver_selection.capability_id == D3A_1_CAPABILITY_ID
    assert (
        projection.manifest["runtime_adapter_id"] == D3A_1_RUNTIME_ADAPTER_ID
    )
    assert projection.runtime.provenance.validation_policy_version == "d3a-1-v1"
    assert all(item.default_manning_n == 0.025 for item in projection.runtime.sections)

    document = run_v4_lite(projection.runtime_snapshot).to_dict()
    assert document["provenance"]["validation_policy_version"] == "d3a-1-v1"
    assert 0.0 < document["diagnostics"]["maximum_friction_number"] <= 0.1
    assert document["diagnostics"]["friction_retry_count"] >= 0
    assert document["water_balance"]["status"] == "pass"
