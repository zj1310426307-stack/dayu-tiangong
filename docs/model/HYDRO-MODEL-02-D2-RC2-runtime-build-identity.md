# HYDRO-MODEL-02-D2-RC2 Runtime Build Identity

## Decision

`model/build_identity.py` is the sole authority for the runtime identity that
freezes and executes a hydraulic task. RC2 binds the product version, immutable
Git revision, Solver Registry, and execution mode into one reproducible
`solver_build_id`.

## Canonical fields

| Field | Rule |
|---|---|
| `engine_version` | `dayu-hydraulic-4.0.0`, owned by the build-identity module |
| `engine_commit` | Lowercase 40-character Git SHA in `ci` and `release` |
| `registry_hash` | Recomputed from the server-owned Solver Registry |
| `solver_build_id` | `dayu.solver-build.v1:` plus the canonical hash of schema, version, commit, and Registry hash |
| `build_mode` | `development`, `ci`, or `release` |
| `build_verified` | Derived only from a valid immutable Git SHA |

Development without a repository is explicitly represented as
`development-unverified`; it is allowed for local work, produces a readiness
warning, and is not release evidence. CI and release modes reject missing,
placeholder, mixed-case, or short revisions.

## Freeze and execution boundary

Backend task creation resolves the identity once, writes it to the task row, and
copies it into v4 snapshot provenance. Legacy and native-v4 Workers compare the
frozen engine version, commit, solver build ID, build mode, verification flag, and
Registry hash immediately after claim and before numerical execution.

Any mismatch fails closed as `D2_RUNTIME_BUILD_MISMATCH`. The Worker does not
rewrite provenance, re-freeze input, or silently execute the task on another build.
Successful result diagnostics retain both `task_requested` and `worker_executed`
identity evidence.

## Shipping environment

The backend image is Python 3.12 and receives `ENGINE_COMMIT`,
`DAYU_ENGINE_VERSION`, and `DAYU_BUILD_MODE` at build time. Its OCI source,
version, and revision labels carry no secrets. Compose assigns the same immutable
image tag to Backend, both Workers, scheduler, migration, and bootstrap services.

Hosted jobs inject `${{ github.sha }}` in CI mode. The exact `D2 shipping runtime`
job builds that image, verifies Python 3.12 and the OCI revision, starts Backend and
both Worker routes from it, runs native-v4/PostGIS and frozen D1 checks, and uploads
the `d2-runtime-build-identity` artifact.

## Scope

This identity proves which code/Registry build executed a task. It does not provide
multi-version Worker routing, image-signing policy, production IAM, or scientific
calibration.
