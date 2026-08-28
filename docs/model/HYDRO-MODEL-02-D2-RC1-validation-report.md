# HYDRO-MODEL-02-D2-RC1 Validation Report

## Current decision

The RC1 candidate has confirmed local, fresh-migration, PostGIS/Redis fault, and full
Docker success evidence. Hosted checks and final branch-protection configuration have
not yet run on the unpushed final commit. Current status is therefore **Pending /
NO-GO for RC1 release**; this report does not declare
`HYDRO-MODEL-02-D2-RC1 PASS`.

## Confirmed evidence

| Validation scope | Confirmed result | Interpretation |
|---|---:|---|
| `tests/model_engine` | **118 passed / 35 skipped** | Complete local model-engine contracts; integration-only skips are not passes |
| Full repository regression | **799 passed / 106 skipped** | Backend and root tests completed with no failure/error using a project-local pytest temp root |
| `tests/model02` | **355 passed** | D1/MODEL-02 numerical regression remains locally green |
| Hosted-equivalent D2 fault list on real PostGIS/Redis | **122 passed** | Includes attempt, stale Worker recovery, delivery-marker recovery, finalization races, Dataset FKs, Registry/freeze, Shadow, and manual retry |
| Fresh PostgreSQL migration | **PASS** | Empty DB upgraded to 0021, downgraded to 0020, re-upgraded to 0021, and reports one head |
| Docker dual-Worker success E2E | **2 passed** | Readiness/preview/create/enqueue/claim/progress/success/results/Artifact/download passed with Backend, Redis, legacy Worker, v4 Worker, and beat scheduler healthy |
| Python compileall | **PASS** | `model` and `backend/app` compile without syntax error |
| OpenAPI contract/update suite | **9 passed; no drift** | Generated client matches the current backend contract |
| Frontend typecheck | **PASS** | Type-level frontend contract completed |
| Frontend production build | **PASS** | Production bundle completed |

The rows above are overlapping validation views and must not be summed into a global
test count.

## Covered RC1 behavior

The confirmed suites exercise the implemented candidate surfaces for:

- database-owned execution attempts and token CAS;
- duplicate delivery, invalid queued route rejection, stale-token rejection, periodic
  stale-lease recovery, and null-only delivery-marker recovery;
- separate numerical, infrastructure, and manual retry semantics;
- manual retry reset and successful-task immutability;
- server Registry-owned v1-v4 solver provenance;
- Dispatch Plan and Pump identity recomputation plus the documented Dataset/Profile
  trust boundary;
- Registry-owned capability scope/exclusions and separate `case_notes`;
- terminal cancel/success races and last accepted heartbeat telemetry;
- same-Dataset result identities and typed Event constraints;
- token/hash-bound attempt staging, locked canonical promotion, deterministic
  reconciliation, and stale-rename/new-attempt exclusion;
- v4 `storage_level=full` enforcement;
- one-transaction Shadow creation and derived group lifecycle;
- OpenAPI/generated-client/frontend compatibility.

This coverage statement describes the relevant test surfaces; only the counts in the
confirmed-evidence table are asserted here.

## Remaining release gates

| Gate | Status | Required evidence before promotion |
|---|---|---|
| Migration 0021 local round-trip | **PASS** | Fresh `0021 -> 0020 -> 0021`; single head `20260828_0021` |
| Complete Docker success and fault E2E | **PASS** | Current code passed real PostGIS/Redis dual-Worker success and 122-test fault lists; scheduler and all runtime services healthy |
| Hosted CI on final RC1 head | **Pending** | Current hydraulic-platform, fault-recovery, MODEL02 Ubuntu/Windows, legacy, OpenAPI, and frontend jobs |
| GitHub branch protection | **Pending** | Main-agent confirmation that all final workflow contexts are required and protection remains active |

Historical D2 hosted run IDs do not validate the uncommitted/current RC1 candidate and
are not reused as RC1 evidence.

## Scientific and operational boundary

RC1 changes task consistency, frozen evidence handling, Dataset identity constraints,
and local Artifact recovery only. It does not expand the D1 scientific capability and
does not establish production calibration, high availability, IAM, remote object-store
durability, or a distributed transaction.
