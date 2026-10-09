# HYDRO-DATA-REAL-01-CLOSE Baseline Audit

- Audit date: 2026-10-09
- Baseline: `origin/main@01b01c949b09a0b05434758510080a9e0712edd6`
- Branch: `phase/hydro-data-real-01-close`
- Working tree at start: clean
- PR #24: merged as `1875cef75fb388933b80a310332bdaa3640fb905`
- PR #25: merged as `01b01c949b09a0b05434758510080a9e0712edd6`
- Open pull requests at start: none

## Existing capability map

| Capability | Existing implementation | Baseline conclusion |
|---|---|---|
| REAL-01 readiness | `backend/app/dataset/real01.py` and `GET /api/v1/model-data/dataset-versions/{id}/real-01-readiness` | Implemented, read-only and fail-closed for missing base domains. Several checks are count-based and need engineering-semantic hardening. |
| REAL-01 freeze | `backend/app/dataset/service.py` and `POST /api/v1/model-data/dataset-versions/{id}/freeze-real-01` | Implemented through the Dataset Version service; it does not create a solver task. No platform IAM identity is available, so reviewer authorization cannot be proven from the request body alone. |
| Engineering graph hash | `backend/app/hydraulic/snapshot.py` and `DatasetVersion.engineering_content_hash` | Implemented as canonical full-graph SHA-256. Clone-only identifiers currently prevent equal-content clone hash equality. |
| Engineering graph clone | `backend/app/dataset/engineering_graph.py` | Version-local IDs are remapped. The baseline incorrectly copies `HydraulicExternalResult`, and changes case/import identities that enter the hash. |
| Hydraulic import preview/commit | `backend/app/hydraulic/service.py` | Preview persists evidence without domain writes. Commit locks the job, revalidates, and runs within the route transaction. Import failures roll back through the shared transaction wrapper. |
| Dataset Version lifecycle | `backend/app/dataset/lifecycle.py`, `backend/app/dataset/service.py` | Only writable Draft/Review versions can be changed; approved/frozen versions require clone-to-draft. |
| Unified hydraulic QA | `backend/app/hydraulic/validators/hydraulic_check.py`, `backend/app/hydraulic/service.py::run_validation` | Persisted error/warning/info/passed findings exist. The baseline readiness accepts any historical passed run, without proving it represents the current engineering graph. |
| Frontend readiness view | `frontend/src/pages/data-center/DataCenterPages.tsx` through generated OpenAPI client | Displays domain completion, gaps, freeze state, engineering hash, D-Flow disabled state and production not-authorized state. |
| D-Flow safety boundary | capability registry and routing gates | `pilot_execution_enabled=false` and `production_eligible=false`; this task must not change either value. |

## Real engineering source access

The controlled project reference area contains only a partial Gaoming River source set: one centerline file and one cross-section workbook. No complete five-river network, two-gate design package, full boundary series, initial-condition package, observation package, or approved review evidence was found. `HYDRO_VALIDATION_CASE_ROOT` is not configured.

The two accessible source files are inventoried by SHA-256 only in the close-out source inventory. They are not copied into Git and are not treated as a complete REAL-01 dataset.

## Required fixes established by G0

1. Bind a passed QA run to the exact engineering graph hash and reject stale QA evidence.
2. Make equal-content clone hashes stable by excluding clone-only import identity and preserving version-scoped Simulation Case names.
3. Stop cloning external model results or historical execution/acceptance evidence.
4. Strengthen readiness checks for topology, Branch direction/chainage, Cross Section placement and ordered Station/Elevation points, Gate provenance/parameters, boundary time-series evidence, Scenario/initial-condition evidence, and source review evidence.
5. Add regression coverage for missing CRS/datum, disconnected topology, invalid section placement, missing Gate sill, missing boundaries/source evidence, stale QA, freeze immutability, clone remapping/hash stability, transaction rollback, D-Flow fail-closed, and the no-real-data status boundary.
6. Keep the final project result at `FRAMEWORK_PASS_DATA_REQUIRED` unless complete, reviewed five-river/two-gate data becomes available and the real PostGIS admission workflow succeeds.

## Baseline safety findings

- No unrelated local modifications were present.
- No production database mutation, Dataset Version freeze, solver run, D-Flow pilot, dispatch optimization, PLC/SCADA connection, tag, or merge is authorized by this task.
- The repository contains templates and synthetic tests; they cannot be reported as real engineering acceptance evidence.
