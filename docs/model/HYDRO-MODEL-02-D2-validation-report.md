# HYDRO-MODEL-02-D2 Validation Report

## Frozen D1 comparison

The v4 platform projection produces the same six-hour D1 result with and without
callbacks:

| Evidence | Frozen value |
|---|---:|
| Gate open | 2940 s |
| Pump start | 7740 s |
| Pump stop | 12540 s |
| Accepted steps | 381 |
| Pump external volume | 22.023440130973746 m³ |
| Pump input energy | 0.12252120603722051 kWh |
| Relative water-balance error | 4.748482309112566e-16 |
| Water-balance status | pass |

## Local validation

The configured project Python environment completed `724 passed / 73 skipped` in the
full `tests + backend/tests` aggregate. The explicit skips require unavailable local
PostGIS/DGIS/QGIS services and are not counted as local passes. The suite includes
native-v4 contracts, registry,
readiness, projection/freeze, callback/cancel, result/artifact quality, API/shadow
contracts, full MODEL-02, Gate/Pump integration, and Phase 4 Gate regressions. Frontend
typecheck and production build passed; OpenAPI regeneration was deterministic.

The real PostGIS/Redis/dual-Worker test is deliberately skipped locally because this
host has no Docker command. Local static migration inspection is not counted as a real
database PASS.

## Hosted integration contract

`hydraulic-platform` runs five named jobs: Backend v4 contract, PostGIS migration,
Worker integration, Frontend OpenAPI, and D1 regression. The Worker test requires real
PostGIS, Redis, a legacy Celery Worker, a dedicated v4 Worker, and a live backend. It
executes readiness, preview, API task create/enqueue/poll, Worker claim/progress/success,
authoritative database rows, summary/Section/Gate/Pump/Event API reads, artifact manifest,
download, and hash verification.

Hosted `hydraulic-platform` run `33113201345` passed all five jobs, including migration
and Worker integration. Hosted `model02` run `33113201378` passed Ubuntu, Windows,
Legacy hydraulic, and Frontend contract. Final branch-head checks remain enforced by
PR #11 before merge.
