# HYDRO-MODEL-02-D2-RC1 Audit

## Audit status

This review compares the RC1 candidate implementation with the P0/P1 findings in the
RC1 execution brief. Code paths and confirmed local evidence are recorded separately
from release gates. The current decision is **release Pending**: no RC1 PASS is claimed
until Hosted CI and GitHub protection are confirmed for the final pushed RC1 head.

Confirmed evidence available to this audit:

- `tests/model_engine`: **118 passed / 35 skipped**;
- full repository regression: **799 passed / 106 skipped**;
- `tests/model02`: **355 passed**;
- Hosted-equivalent D2 fault list on real PostGIS/Redis: **122 passed**;
- fresh PostgreSQL `0021 -> 0020 -> 0021` round-trip and one head: **PASS**;
- Docker success E2E: **2 passed**, with backend, Redis, legacy/v4 Workers, and beat
  scheduler healthy;
- Python compileall: **PASS**;
- OpenAPI contract/update suite: **9 passed**, with no generated-client drift;
- frontend typecheck and production build: **PASS**.

These suites overlap and must not be added into one synthetic total. Skips are not
passes.

## P0 findings

| ID | Root cause | Code closure | Relevant tests | Hosted evidence | Status |
|---|---|---|---|---|---|
| P0-1 Celery retry/claim conflict | Celery autoretry redelivered after the first delivery had committed `queued -> running`; the second delivery could not reclaim the task. Worker loss also needed durable stale-lease and queued-delivery recovery. | `worker/tasks.py` removes autoretry ownership and uses late acknowledgement; `worker/lifecycle.py` performs token-fenced bounded requeue; `worker/recovery.py`, Celery beat, and the Compose scheduler recover stale running leases then only queued rows with a null delivery marker. Successful publication records `queue_job_id`, preventing queue amplification. | `test_v4_execution_attempt.py`, `test_v4_task_state_machine.py`, and real `test_v4_worker_fault_e2e.py`; included in the 122-pass PostGIS/Redis list. | **Pending** — current RC1 workflow/head not yet pushed. | Implemented; local/real-service evidence confirmed; release Pending. |
| P0-2 retry semantic collision | Legacy/manual task retry and rejected numerical trials shared `retry_count`, so lifecycle and numerical evidence were ambiguous. | `backend/app/gis/models.py`, `model_engine/schemas.py`, `service.py`, `router.py`, `worker/lifecycle.py`, and `worker/tasks.py` separate execution-attempt, manual, infrastructure, and numerical counters. Legacy `retry_count` remains compatibility-only for native v4. | `test_v4_manual_retry.py`, `test_v4_task_state_machine.py`, `test_v4_rc1_schema_metadata.py`, `test_v4_task_contract.py`, and frontend contract coverage. | **Pending**. | Implemented; local evidence confirmed; release Pending. |
| P0-3 legacy solver provenance spoof | v1-v3 and internal task producers could omit or persist caller-owned route identity; a malformed queued v4 route could be misclassified as a duplicate forever. | `model/solver/registry.py` resolves v1-v4 and supplies five-field task provenance to public, Dispatch, Optimization, and Shadow builders. Native-v4 claim validates all five fields; a queued mismatch is CAS-failed without an attempt, while a true duplicate is a no-op. | `test_solver_registry.py`, `test_v4_worker_capability.py`, `test_v4_sync_run_guard.py`, `test_v4_task_contract.py`, `test_v4_shadow.py`, and real malformed-route E2E. | **Pending**. | Implemented; local/real-service evidence confirmed; release Pending. |
| P0-4 frozen evidence was not fully revalidated | Dispatch Plan readiness checked stored hash shape but did not recompute the frozen snapshot; other identity domains needed an explicit recompute/trust boundary. | `dispatch/validator.py`, `dispatch/service.py`, and `model_engine/v4_service.py` recompute the Dispatch Plan hash and Pump curve identity. Dataset accepts only approved/published persisted GIS-core identity; Profile remains explicitly `persisted/import-validated` because historical algorithms are not unambiguously reproducible. No full-D2 Dataset recomputation is claimed. | `test_v4_freeze_integrity.py`, `test_v4_snapshot_freeze.py`, `test_v4_readiness.py`, and `test_v4_dataset_integrity.py`. | **Pending**. | Implemented within the documented trust boundary; local evidence confirmed; release Pending. |
| P0-5 capability limitations override | Mutable Case configuration could be interpreted as redefining the solver's scientific scope. | `model/solver/registry.py`, `model/api/v4.py`, `model/adapters/v4.py`, `v4_service.py`, and `v4_result.py` keep scope/exclusions/known limitations Registry-owned and keep `case_notes` separate and provenance-only. | `test_solver_registry.py`, `test_v4_runtime_projection.py`, `test_v4_task_contract.py`, and freeze-integrity coverage. | **Pending**. | Implemented; local evidence confirmed; release Pending. |
| P0-6 final cancel/success race | Final success used a normal ORM commit and could overwrite cancellation; an old attempt could also rename the canonical Artifact after stale recovery. | `worker/lifecycle.py`, `worker/tasks.py`, and `v4_result.py` require status, `cancel_requested=false`, and token CAS. Artifact bytes first enter token/hash-bound attempt staging; task/Artifact row locks, token/metadata/hash checks, canonical promote, and final publication close the old-attempt rename race. | `test_v4_finalization_races.py` includes a real barrier race; `test_v4_execution_attempt.py` and `test_v4_reconciliation.py` cover terminal/recovery windows. | **Pending**. | Implemented; real PostGIS fault evidence confirmed; release Pending. |

## P1 findings

| ID | Root cause | Code closure | Relevant tests | Hosted evidence | Status |
|---|---|---|---|---|---|
| P1-1 Dataset composite identity | Result/Event rows could identify a Gate, Pump, or Branch without proving it belonged to the task Dataset Version. | `backend/app/gis/models.py`, `v4_result.py`, and additive migration `20260828_0021` add same-Dataset composite FKs for Section-result Branch, Gate result, Pump result, and typed Gate/Pump Events, with supporting uniqueness/checks/index metadata. | `test_v4_dataset_integrity.py`, `test_v4_rc1_schema_metadata.py`, and `test_v4_postgis_worker_integration.py`; real fault list 122 passed and fresh migration round-trip passed. | **Pending** — Hosted migration job not yet run on final head. | Constraint/migration code and local PG evidence confirmed; release Pending. |
| P1-2A multiple active Profiles | Selecting a latest/first Profile could silently choose among competing active sources. | `model_engine/v4_service.py` requires exactly one active Profile and emits distinct missing/multiple readiness errors. Persisted Profile identity remains import-validated rather than falsely recomputed. | `test_v4_readiness.py`, `test_v4_postgis_worker_integration.py`, and the confirmed model-engine/PG suites. | **Pending**. | Implemented; local evidence confirmed; release Pending. |
| P1-2B duplicate boundaries and Case asset ambiguity | A first matching boundary or Dataset-wide unique Gate/Pump could be selected without a unique Case/frozen identity. | `model_engine/v4_service.py` requires exactly one upstream Q and downstream H binding, validates hydraulic node roles, and resolves positive frozen `gate_id`/`pump_id` in the Case Dataset Version and selected Branch. | `test_v4_readiness.py`, `test_v4_freeze_integrity.py`, `test_v4_postgis_worker_integration.py`, and backend Phase 4 regression coverage. | **Pending**. | Implemented; local evidence confirmed; release Pending. |
| P1-3 heartbeat null overwrite | Phase-only heartbeats could erase the last accepted simulation time/CFL. | `worker/lifecycle.py` updates optional telemetry only when supplied; `worker/tasks.py` retains accepted-step telemetry through serializing/finalization phases. | `test_v4_task_state_machine.py` and `test_v4_finalization_races.py`. | **Pending**. | Implemented; local evidence confirmed; release Pending. |
| P1-4 Artifact reconciliation | A crash between DB prepared commit, file rename, and final CAS had no deterministic recovery path; stale recovery could race an old rename. | `v4_result.py`, `v4_reconciliation.py`, `reconcile_v4_task.py`, and Worker lifecycle implement token/hash-bound attempt staging, locked canonical promotion, Cases A-F, default dry-run, explicit `--apply`, root-bounded quarantine, and retry gating. Stale staging is quarantined, never auto-published. | `test_v4_reconciliation.py`, barrier `test_v4_finalization_races.py`, and `test_v4_task_state_machine.py`; included in 122-pass real fault list and Docker E2E. | **Pending** — Hosted fault job not yet run on final head. | Implemented; local/real-service evidence confirmed; release Pending. |
| P1-5 v4 `storage_level` false option | The API exposed summary/key-section choices that native v4 did not implement. | `model_engine/schemas.py` defaults v4 to `full` and rejects other v4 values; legacy schemas retain their compatibility behavior. Frontend v4 submits `full`. | `test_v4_task_contract.py`, OpenAPI suite, and frontend contract/typecheck/build. | **Pending**. | Implemented; interface evidence confirmed; release Pending. |
| P1-6 Shadow atomicity and lifecycle | Group, v3 task, and v4 task committed independently, so a later failure could leave orphan rows and ambiguous group state. | `model_engine/service.py` exposes a no-commit builder; `shadow.py` stages group/tasks/roles in one transaction and derives group lifecycle; ORM/migration add one-role-per-group uniqueness. | `test_v4_shadow.py`, `test_solver_registry.py`, and related model-engine coverage. | **Pending**. | Implemented; local evidence confirmed; release Pending. |

## Release-blocking gates

| Gate | Audit state |
|---|---|
| Migration 0021 local fresh upgrade/downgrade/re-upgrade/single-head | **PASS — `20260828_0021`** |
| Complete Docker PostGIS/Redis/legacy Worker/v4 Worker/scheduler/API success and fault E2E | **PASS — 2 success E2E + 122 fault tests; all services healthy** |
| Hosted hydraulic-platform, model02 cross-platform, frontend, and fault-recovery checks on final RC1 head | **Pending main-agent confirmation** |
| GitHub required checks and protection for the final RC1 workflow contexts | **Pending main-agent confirmation** |

Until every row above is confirmed against the final RC1 commit, the independent audit
decision remains **NO-GO / Pending**, not RC1 PASS.

## Scope boundary

The audit does not approve general multi-Branch Saint-Venant flow, wet/dry, reverse or
supercritical flow, internal Pump hydraulics, positive Manning, nonzero bed slope,
non-identical Profiles, engineering calibration, production IAM, remote Artifact
durability, or distributed crash recovery. The D1 scientific envelope remains
unchanged.
