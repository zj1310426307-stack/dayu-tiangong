# HYDRO-MODEL-02-D2 Validation Report

> RC2 superseding gate: D2 additionally requires immutable runtime build matching,
> migration 0022, bounded recovery of stale queued messages even with a non-null job
> marker, and the Python 3.12 Hosted `D2 shipping runtime` job. Current evidence is
> tracked in `HYDRO-MODEL-02-D2-RC2-validation-report.md`; older runs are not reused.

## Current RC1 validation snapshot

The active D2 candidate includes RC1 consistency changes beyond the historical D2
hosted runs. Current evidence is tied to validated implementation head `aab8d6a` and
does not reuse historical D2 runs.

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
| Hosted `hydraulic-platform` / `model02` | **PASS — PR runs `33142739966` / `33142739961`** |

The validation views overlap and are not summed. Skips are recorded as skips,
not successes.

## RC1 gates

| Gate | Status |
|---|---|
| Migration 0021 local upgrade/downgrade/re-upgrade/single-head | **PASS** |
| Complete Docker PostGIS/Redis/dual-Worker/scheduler/API/Artifact success and fault E2E | **PASS** |
| Hosted hydraulic-platform, fault-recovery, MODEL02 cross-platform, legacy, OpenAPI, and frontend jobs | **PASS on `aab8d6a`** |
| GitHub required checks and branch protection for final RC1 contexts | **PASS — strict, 9 required contexts, force-push/deletion disabled** |

The current decision is **RC1 PASS / ready for independent review**. PR #11 remains
OPEN; merge and D2 tag creation are not authorized by this report.
Detailed evidence and root-cause mapping are maintained in
`HYDRO-MODEL-02-D2-RC1-validation-report.md` and
`../review/HYDRO-MODEL-02-D2-RC1-audit.md`.

## Boundary

The RC1 work does not expand the frozen D1 scientific scope. Production IAM,
multi-tenancy, remote Artifact durability, distributed crash recovery, engineering
calibration, and real command dispatch remain outside this validation.
