# HYDRO-MODEL-02-D2-RC2 Validation Report

## Candidate decision

Local RC2 validation is **PASS**. Hosted validation remains pending until the
committed PR head completes the exact `D2 shipping runtime` job. The PR therefore
remains open and RC2 is not yet merge-ready. Historical D2/RC1 runs are not used as
RC2 evidence.

## Required evidence

| Gate | Observed result |
|---|---|
| Runtime identity and Worker mismatch contracts | PASS in host and Python 3.12 shipping-image contract suites |
| Queued non-null-marker recovery and amplification limit | PASS in real PostGIS/Redis fault suite; 164 tests passed with zero skips/failures |
| Migration `0022 -> 0021 -> 0022`, one head | PASS on fresh TimescaleDB/PostGIS; final head `20260828_0022` |
| Full model-engine and repository regressions | PASS: 922 collected, 816 passed, 106 environment-gated skips, 0 failures/errors |
| Frozen D1/MODEL02 numerical evidence | PASS: MODEL02 355 passed; shipping image rechecked 2940 / 7740 / 12540 / 381, Pump volume/energy and water balance |
| OpenAPI generated client / frontend typecheck and build | PASS: generator hash unchanged (`FCC281B5...D98E`); typecheck and Vite production build passed |
| Docker shared image / OCI revision / Python 3.12 | PASS locally: CPython 3.12.13, OCI revision injection, identical Backend/legacy/v4 Worker identity, Compose shared SHA image |
| Real shipping-image native-v4 success E2E | PASS: 2/2 against temporary PostGIS, Redis, Backend and both Workers |
| Hosted exact `D2 shipping runtime` | Pending final candidate SHA |
| Existing Hosted required checks | Pending final candidate SHA |
| Main protection 9 -> 10 contexts | Must occur only after exact shipping job succeeds |

The 816-pass full-suite count is authoritative and is not added to overlapping
targeted suite counts. Local Docker used the pre-commit audit SHA only to validate
the injection and matching mechanism; it is not release evidence. Hosted must build
the committed PR SHA before this report can declare merge readiness.
