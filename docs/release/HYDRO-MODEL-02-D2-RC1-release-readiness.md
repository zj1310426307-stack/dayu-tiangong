# HYDRO-MODEL-02-D2-RC1 Release Readiness

- Date: 2026-08-28
- Scope: RC1 task-attempt, retry, freeze-integrity, Dataset constraint, Shadow, and
  Result/Artifact recovery hardening
- Decision: **NOT READY — Pending Hosted CI and final protection gate**

## Confirmed candidate gates

| Gate | Status |
|---|---|
| Model-engine regression | Confirmed: **118 passed / 35 skipped** |
| Full repository regression | Confirmed: **799 passed / 106 skipped** |
| MODEL02 numerical guard | Confirmed: **355 passed** |
| Real PostGIS/Redis Hosted-equivalent fault list | Confirmed: **122 passed** |
| Fresh migration `0021 -> 0020 -> 0021` / single head | Confirmed: **PASS / 20260828_0021** |
| Docker dual-Worker success E2E | Confirmed: **2 passed** |
| Docker scheduler/runtime health | Confirmed: **all services healthy** |
| Python compileall | Confirmed: **PASS** |
| OpenAPI generated-client contract | Confirmed: **9 passed; no drift** |
| Frontend typecheck/build | Confirmed: **PASS / PASS** |

These results support the candidate implementation but do not by themselves authorize
an RC1 release.

## Blocking release gates

| Gate | Status | Promotion rule |
|---|---|---|
| Migration 0021 local round-trip | **PASS** | Fresh empty database completed `0021 -> 0020 -> 0021`; one head confirmed |
| Complete Docker E2E | **PASS** | Current RC1 code passed real success/fault chains with both Worker routes and beat recovery |
| Hosted CI | **Pending main-agent confirmation** | Confirm all required success and fault-recovery jobs on the final RC1 commit |
| GitHub main protection | **Pending main-agent confirmation** | Confirm required contexts after the final workflow is present; do not rely on an earlier protection snapshot |

Any Pending row keeps the release decision at **NOT READY**. No historical D2 run can
substitute for a current RC1-head run.

## Release promotion checklist

- [x] Candidate code and local contract surfaces implemented.
- [x] Confirmed local/model/PG/OpenAPI/frontend evidence recorded without adding
  overlapping counts.
- [x] Migration 0021 local round-trip confirmed by the main agent.
- [x] Complete Docker success and fault E2E confirmed by the main agent.
- [ ] Hosted hydraulic-platform/fault-recovery/MODEL02/legacy/frontend checks confirmed
  on the final RC1 commit.
- [ ] GitHub required checks and protection re-confirmed for all final contexts.
- [ ] Final commit/PR evidence reviewed without merging as part of this document task.

## Accurate current statement

> HYDRO-MODEL-02-D2-RC1 has implemented the candidate consistency hardening and has
> confirmed local regression, fresh migration round-trip, real PostGIS/Redis fault,
> and complete Docker success evidence. Hosted CI on the final pushed head and final
> GitHub protection remain Pending; therefore RC1 is not yet declared PASS or
> release-ready.

## Continuing NO-GO

The candidate does not add production IAM/RBAC, multi-tenancy, remote object-store
durability, full disaster recovery, distributed database/file transactions, engineering
calibration, real command dispatch, or scientific capability beyond the frozen D1
scope.
