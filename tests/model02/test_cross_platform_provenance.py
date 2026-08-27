"""Cross-platform contracts for canonical input and separated hash domains."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from model.adapters import (
    build_v4_lite_mesh,
    v4_lite_mesh_hash,
    v4_lite_runtime_projection_hash,
    v4_lite_solver_policy_hash,
    v4_lite_validation_policy_hash,
)
from model.api import parse_v4_lite_input
from model.provenance import (
    CANONICALIZATION_ID,
    authoritative_input_hash,
    canonical_json_bytes,
    snapshot_hash,
)
from tests.model02.test_v4_lite_pump_strong_coupling import (
    make_v4_lite_d1_payload,
)

_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "model02"
    / "v4-lite-3-moving-nonprismatic.json"
)
_AUTHORITATIVE_HASH = (
    "96eb4e4d28bc05c865c3f5e8f24e3b0169b4d29f95bfe515e22e72237bf2bec1"
)


def _fixture_payload() -> dict:
    """Load the checked-in authoritative JSON without runtime trigonometry."""

    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _domain_hashes(payload: dict) -> dict[str, str]:
    """Return every RC1 identity domain for one valid v4-lite payload."""

    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    return {
        "authoritative": authoritative_input_hash(payload),
        "runtime_projection": v4_lite_runtime_projection_hash(parsed),
        "mesh": v4_lite_mesh_hash(parsed, mesh),
        "solver_policy": v4_lite_solver_policy_hash(parsed),
        "validation_policy": v4_lite_validation_policy_hash(parsed),
    }


def test_checked_in_authoritative_fixture_has_frozen_canonical_bytes() -> None:
    """The same parsed JSON bytes must identify the fixture on every OS."""

    payload = _fixture_payload()
    canonical_bytes = canonical_json_bytes(payload)

    assert CANONICALIZATION_ID == "dayu-canonical-json-v1"
    assert not canonical_bytes.startswith(b"\xef\xbb\xbf")
    assert not canonical_bytes.endswith(b"\n")
    assert hashlib.sha256(canonical_bytes).hexdigest() == _AUTHORITATIVE_HASH
    assert authoritative_input_hash(payload) == snapshot_hash(payload)


def test_canonical_hash_ignores_mapping_order_but_not_numeric_semantics() -> None:
    """Key order is presentation; a changed engineering number is identity."""

    first = {"z": 3, "nested": {"b": 2, "a": 10.0}}
    reordered = {"nested": {"a": 10.0, "b": 2}, "z": 3}
    changed = {"nested": {"a": 10.0001, "b": 2}, "z": 3}

    assert authoritative_input_hash(first) == authoritative_input_hash(reordered)
    assert authoritative_input_hash(first) != authoritative_input_hash(changed)


def test_pump_curve_and_control_changes_are_authoritative() -> None:
    """Pump physics and command policy changes must alter input identity."""

    baseline = make_v4_lite_d1_payload()
    curve_changed = copy.deepcopy(baseline)
    curve_changed["structures"]["pumps"][0]["head_curve"]["points"][1][
        "head_m"
    ] += 0.001
    control_changed = copy.deepcopy(baseline)
    control_changed["structures"]["pumps"][0]["control"][
        "minimum_run_seconds"
    ] += 1.0

    assert authoritative_input_hash(curve_changed) != authoritative_input_hash(
        baseline
    )
    assert authoritative_input_hash(control_changed) != authoritative_input_hash(
        baseline
    )


def test_hash_domains_change_only_with_their_declared_ownership() -> None:
    """Metadata, mesh identity, and solver policy have explicit hash owners."""

    baseline = _fixture_payload()
    baseline_hashes = _domain_hashes(baseline)

    provenance_changed = copy.deepcopy(baseline)
    provenance_changed["provenance"]["engine_commit"] = "rc1-metadata-change"
    provenance_hashes = _domain_hashes(provenance_changed)
    assert provenance_hashes["authoritative"] != baseline_hashes["authoritative"]
    for domain in (
        "runtime_projection",
        "mesh",
        "solver_policy",
        "validation_policy",
    ):
        assert provenance_hashes[domain] == baseline_hashes[domain]

    mesh_changed = copy.deepcopy(baseline)
    mesh_changed["sections"][0]["profile_hash"] = "f" * 64
    mesh_hashes = _domain_hashes(mesh_changed)
    assert mesh_hashes["authoritative"] != baseline_hashes["authoritative"]
    assert mesh_hashes["runtime_projection"] != baseline_hashes[
        "runtime_projection"
    ]
    assert mesh_hashes["mesh"] != baseline_hashes["mesh"]
    assert mesh_hashes["solver_policy"] == baseline_hashes["solver_policy"]
    assert mesh_hashes["validation_policy"] == baseline_hashes[
        "validation_policy"
    ]

    solver_changed = copy.deepcopy(baseline)
    solver_changed["solver"]["maximum_time_step_seconds"] = 0.05
    solver_hashes = _domain_hashes(solver_changed)
    assert solver_hashes["authoritative"] != baseline_hashes["authoritative"]
    assert solver_hashes["runtime_projection"] != baseline_hashes[
        "runtime_projection"
    ]
    assert solver_hashes["mesh"] == baseline_hashes["mesh"]
    assert solver_hashes["solver_policy"] != baseline_hashes["solver_policy"]
    assert solver_hashes["validation_policy"] == baseline_hashes[
        "validation_policy"
    ]
