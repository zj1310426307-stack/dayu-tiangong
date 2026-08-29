# HYDRO-MODEL-02-D2-RC2 Validation Report

## Candidate decision

RC2 validation is **PASS** locally and on GitHub Hosted runners for implementation
candidate `5e6a0aed399ad4a5b17614e21f4923a1aacfaf98`. The exact
`D2 shipping runtime` job passed twice for that SHA, its immutable evidence artifact
is available, and main protection now contains the preserved nine contexts plus the
exact tenth shipping context. PR #11 remains open and is **MERGE READY FOR
INDEPENDENT REVIEW**; this task does not authorize merge or tag creation.

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
| Hosted exact `D2 shipping runtime` | PASS twice on candidate SHA: runs `33156277870` and `33156280523`; jobs `98799690207` and `98799698419` |
| Immutable Hosted evidence | PASS: artifact `d2-runtime-build-identity` (`9679812945`), SHA-256 digest `6187b466bf5e1b29f6ea41675b3c33f0840a060c9bb45821f444db1e725db9d5`, not expired |
| Existing Hosted required checks | PASS on candidate SHA; all Linux, Windows, frontend, contract, migration, Worker, D1 and D2 fault gates succeeded |
| Main protection 9 -> 10 contexts | PASS after first shipping success: strict mode retained, all nine contexts preserved, exact `D2 shipping runtime` appended with GitHub Actions app binding |

The 816-pass full-suite count is authoritative and is not added to overlapping
targeted suite counts. Local Docker used the pre-commit audit SHA only to validate
the injection and matching mechanism; it is not release evidence. Hosted built and
exercised the committed implementation candidate SHA above. Any later
documentation-only commit must still pass the protected PR checks before merge.
