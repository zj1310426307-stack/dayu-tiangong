# HYDRO-MODEL-02-D2-RC1 Validation Report

## Current decision

The RC1 candidate has confirmed local, fresh-migration, PostGIS/Redis fault, full
Docker, and Hosted evidence. The validated implementation head is
`aab8d6a0cd99bb6b6113525c7cc2c313d6685b2e`; both push and pull-request runs passed,
including the exact `D2 fault recovery` job. Main protection remains strict and now
requires all original eight contexts plus `D2 fault recovery`. Current status is
therefore **HYDRO-MODEL-02-D2-RC1 PASS / release-ready for independent review**.
PR #11 remains OPEN and this report does not authorize merge or tagging.

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
| Hosted `hydraulic-platform` | **PASS** | PR run [`33142739966`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33142739966); includes Backend, migration, Worker, `D2 fault recovery`, OpenAPI, and D1 regression |
| Hosted `model02` | **PASS** | PR run [`33142739961`](https://github.com/zj1310426307-stack/dayu-tiangong/actions/runs/33142739961); Ubuntu, Windows, legacy, and frontend contract all passed |

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
| Hosted CI on validated RC1 implementation head | **PASS** | `aab8d6a`; PR runs `33142739966` and `33142739961`, plus matching push runs `33142737984` and `33142738012` |
| GitHub branch protection | **PASS** | Strict mode; 9 required checks; original 8 preserved; admins enforced; force-push/deletion disabled |

Historical D2 hosted run IDs are not reused as RC1 evidence. The evidence-only report
commit that records these results must itself pass the unchanged required checks before
handoff; it does not change runtime, migration, frontend, or workflow behavior.

## Scientific and operational boundary

RC1 changes task consistency, frozen evidence handling, Dataset identity constraints,
and local Artifact recovery only. It does not expand the D1 scientific capability and
does not establish production calibration, high availability, IAM, remote object-store
durability, or a distributed transaction.
