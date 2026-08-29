"""Pure model-input adapters with no backend or database dependency."""

from model.adapters.v3 import adapt_v3_to_v2
from model.adapters.v4 import V4RuntimeProjection, project_v4_to_v4_lite
from model.adapters.v4_lite import (
    MESH_HASH_SCHEMA,
    MESH_HASH_SCHEMA_V2,
    RUNTIME_PROJECTION_HASH_SCHEMA,
    SOLVER_POLICY_HASH_SCHEMA,
    VALIDATION_POLICY_HASH_SCHEMA,
    build_v4_lite_mesh,
    run_v4_lite,
    v4_lite_mesh_hash,
    v4_lite_runtime_projection_hash,
    v4_lite_solver_policy_hash,
    v4_lite_validation_policy_hash,
)

__all__ = [
    "MESH_HASH_SCHEMA",
    "MESH_HASH_SCHEMA_V2",
    "RUNTIME_PROJECTION_HASH_SCHEMA",
    "SOLVER_POLICY_HASH_SCHEMA",
    "VALIDATION_POLICY_HASH_SCHEMA",
    "adapt_v3_to_v2",
    "project_v4_to_v4_lite",
    "V4RuntimeProjection",
    "build_v4_lite_mesh",
    "run_v4_lite",
    "v4_lite_mesh_hash",
    "v4_lite_runtime_projection_hash",
    "v4_lite_solver_policy_hash",
    "v4_lite_validation_policy_hash",
]
