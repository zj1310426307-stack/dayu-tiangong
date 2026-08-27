"""Native-v4 result-v3 quality and deterministic artifact gates."""

from __future__ import annotations

import copy
import gzip

import pytest

from app.model_engine.v4_result import build_stage_evidence_artifact, validate_v4_result
from model import HydraulicEngine
from model.adapters import project_v4_to_v4_lite
from tests.model_engine.helpers import native_v4_payload


@pytest.fixture(scope="module")
def solved():
    projection = project_v4_to_v4_lite(native_v4_payload())
    result = HydraulicEngine().run(projection.runtime_snapshot).to_dict()
    return projection, result


def test_valid_d1_result_closes_v4_quality_gates(solved) -> None:
    projection, result = solved
    validate_v4_result(result, projection)


def test_forged_pump_evidence_and_water_balance_are_rejected(solved) -> None:
    projection, result = solved
    forged = copy.deepcopy(result)
    forged["pump_coupling_evidence"][0]["maximum_absolute_head_residual_m"] = 1.0
    with pytest.raises(ValueError, match="Pump operating-point residual"):
        validate_v4_result(forged, projection)
    unbalanced = copy.deepcopy(result)
    unbalanced["water_balance"]["status"] = "fail"
    with pytest.raises(ValueError, match="water balance"):
        validate_v4_result(unbalanced, projection)


def test_stage_artifact_is_deterministic_canonical_jsonl_gzip(solved) -> None:
    projection, result = solved
    first, first_count = build_stage_evidence_artifact(result, projection)
    second, second_count = build_stage_evidence_artifact(result, projection)
    assert first == second
    assert first_count == second_count
    assert first[4:8] == b"\x00\x00\x00\x00"
    lines = gzip.decompress(first).decode("utf-8").splitlines()
    assert len(lines) == first_count
    assert lines[0].startswith('{"evidence":')
    assert '"record_type":"gate_stage"' in lines[0]
