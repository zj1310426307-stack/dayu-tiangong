"""Pure native-v4 to frozen D1 v4-lite-7 runtime projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from model.adapters.v4_lite import (
    build_v4_lite_mesh,
    v4_lite_mesh_hash,
    v4_lite_runtime_projection_hash,
    v4_lite_solver_policy_hash,
    v4_lite_validation_policy_hash,
)
from model.api.v4 import ModelInputV4, parse_model_input_v4
from model.api.v4_lite import V4LiteInput, parse_v4_lite_input
from model.provenance import CANONICALIZATION_ID, snapshot_hash
from model.solver.registry import registry_hash


@dataclass(frozen=True, slots=True)
class V4RuntimeProjection:
    """Carry the validated source, runtime input, and independently recomputable hashes."""

    source: ModelInputV4
    runtime: V4LiteInput
    source_snapshot: dict[str, Any]
    runtime_snapshot: dict[str, Any]
    manifest: dict[str, Any]


def project_v4_to_v4_lite(snapshot: Mapping[str, Any]) -> V4RuntimeProjection:
    """Project native v4 directly to v4-lite-7 without v3/v2 or guessed values."""

    source = parse_model_input_v4(snapshot)
    source_snapshot = source.model_dump(mode="json")
    runtime_snapshot = {
        "schema_version": "dayu.model-input.v4-lite",
        "dataset_version": source.dataset_version.model_dump(mode="json"),
        "coordinate_reference": source.coordinate_reference.model_dump(mode="json"),
        "solver": source.numerical_policy.model_dump(mode="json"),
        "river": source.branches[0].model_dump(mode="json"),
        "sections": [
            item.model_dump(mode="json") for item in source.cross_sections
        ],
        "initial_state": source.initial_state.model_dump(mode="json"),
        "boundary": source.boundaries.model_dump(mode="json"),
        "structures": source.structures.model_dump(mode="json"),
        "provenance": {
            "engine_version": source.provenance.engine_version,
            "engine_commit": source.provenance.engine_commit,
            "validation_policy_version": source.validation.validation_policy_version,
        },
    }
    runtime = parse_v4_lite_input(runtime_snapshot)
    mesh = build_v4_lite_mesh(runtime)
    manifest = {
        "schema_version": "dayu.v4-runtime-projection-manifest.v1",
        "source_schema_version": source.schema_version,
        "source_input_hash": snapshot_hash(source_snapshot),
        "runtime_schema_version": runtime.schema_version,
        "runtime_adapter_id": source.solver_selection.runtime_adapter_id,
        "runtime_projection_hash": v4_lite_runtime_projection_hash(runtime),
        "mesh_hash": v4_lite_mesh_hash(runtime, mesh),
        "solver_policy_hash": v4_lite_solver_policy_hash(runtime),
        "validation_policy_hash": v4_lite_validation_policy_hash(runtime),
        "registry_hash": registry_hash(),
        "canonicalization_id": CANONICALIZATION_ID,
        "copied_fields": [
            "dataset_version",
            "coordinate_reference",
            "branches[0]",
            "cross_sections",
            "initial_state",
            "boundaries",
            "structures",
            "numerical_policy",
        ],
        "defaulted_fields": [],
        "blocked_fields": [
            "legacy_runtime_overrides",
            "v3_adapter",
            "v2_fallback",
        ],
    }
    return V4RuntimeProjection(
        source=source,
        runtime=runtime,
        source_snapshot=source_snapshot,
        runtime_snapshot=runtime.model_dump(mode="json"),
        manifest=manifest,
    )

