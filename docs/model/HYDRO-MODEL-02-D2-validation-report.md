# HYDRO-MODEL-02-D2 Validation Report

## Current RC1 validation snapshot

The active D2 candidate includes RC1 consistency changes beyond the historical D2
hosted runs. Those historical runs must not be treated as evidence for the current RC1
working tree.

| Validation scope | Current confirmed result |
|---|---:|
| `tests/model_engine` | **118 passed / 35 skipped** |
| Full repository regression | **799 passed / 106 skipped** |
| `tests/model02` | **355 passed** |
| Real PostGIS/Redis Hosted-equivalent fault list | **122 passed** |
| Fresh migration `0021 -> 0020 -> 0021` / one head | **PASS / `20260828_0021`** |
| Docker dual-Worker success E2E | **2 passed; all runtime services healthy** |
| Python compileall | **PASS** |
| OpenAPI contract/update | **9 passed; no generated-client drift** |
| Frontend typecheck | **PASS** |
| Frontend production build | **PASS** |

The validation views overlap and are not summed. Skips are recorded as skips,
not successes.

## Pending RC1 gates

| Gate | Status |
|---|---|
| Migration 0021 local upgrade/downgrade/re-upgrade/single-head | **PASS** |
| Complete Docker PostGIS/Redis/dual-Worker/scheduler/API/Artifact success and fault E2E | **PASS** |
| Hosted hydraulic-platform, fault-recovery, MODEL02 cross-platform, legacy, OpenAPI, and frontend jobs | **Pending main-agent confirmation** |
| GitHub required checks and branch protection for final RC1 contexts | **Pending main-agent confirmation** |

The current decision is **Pending / NO-GO for RC1 release**. No RC1 PASS is declared.
Detailed evidence and root-cause mapping are maintained in
`HYDRO-MODEL-02-D2-RC1-validation-report.md` and
`../review/HYDRO-MODEL-02-D2-RC1-audit.md`.

## Boundary

The RC1 work does not expand the frozen D1 scientific scope. Production IAM,
multi-tenancy, remote Artifact durability, distributed crash recovery, engineering
calibration, and real command dispatch remain outside this validation.
