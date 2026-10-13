# HYDRO-AUTH-01-FIX-01 Review

## Implemented security boundaries

- Explicit Dataset review round and scope. Every REAL-01 resubmission creates a fresh round. Freeze reads the latest decision across all actions within that round and requires approval plus current graph/QA/review Hash equality.
- Reviewer commands use `review_round` and `expected_decision_id`. Shared Dataset row locking and these preconditions serialize competing decisions and Return/Freeze. Rejection is terminal; cloning starts a fresh Draft with round zero.
- Legacy Standard 1D approval retains validation/mapper/warning policy but produces separately scoped evidence. It cannot substitute for REAL-01 approval or reapprove a version already in REAL-01 review.
- Application/publisher role evidence privileges are SELECT/INSERT only; UPDATE/DELETE/TRUNCATE are revoked, including inherited role grants. Bootstrap corrects grants every time. Non-owner triggers protect review/audit/marker modifications even after an erroneous future grant. Runtime owner or privileged inherited membership is rejected.
- Initial admin creation uses a persistent singleton and transactional advisory lock. Upgrade consumes it for any historical admin binding/grant. Normal restart cannot reactivate a revoked binding or disabled principal. Owner recovery is documented and was not executed.

## Migration and compatibility

Revision `20261013_0039` follows 0038 without rewriting history. Original Principal, Role Binding, Review, Audit and Dataset fields survive downgrade/upgrade with identical values. Ambiguous review history receives no valid current round. Existing certified Dataset statuses are unchanged. Downgrade deliberately does not restore excessive evidence privileges.

The Review API requires round and latest-decision preconditions. The generated OpenAPI client is synchronized. Existing review versions with ambiguous history should be cloned into a new Draft and reviewed afresh. A separately authorized operator may handle exceptional lifecycle recovery according to the deployment runbook; no automatic migration grants validity.

## Verification

- Baseline: all three reported risks reproduced in disposable PostgreSQL/PostGIS before implementation.
- FIX-01: 24 real PostgreSQL tests passed, including AUTH-FIX-T01–T20, inherited-grant trigger protection, application non-owner privileges, old/unscoped approval denial and history-preserving migration roundtrip.
- Original Security/Dataset/REAL-01: 42 passed.
- Identity/Engineering Graph Clone/Engineering/Production/Dispatch PostGIS plus hydraulic regressions: 68 passed.
- Compile and Ruff: PASS. OpenAPI generated twice without drift: SHA-256 `7F1D71FCB292FA6C85C0BAD6ABB344E7EFDE324057A2BC3048FACA9FC44CA8EA`.
- Frontend typecheck/build and final GitHub Actions are checked against the final PR head; final counts and commit are recorded in project delivery evidence and PR #27.
- All temporary test containers and their dedicated volume were removed. No platform persistent database or real engineering dataset was modified.

## Remaining boundary

Real OIDC Provider configuration is still required for production authentication. This task closes ordinary application-login evidence tampering; database owners, superusers and approved deployment operators remain privileged and require operational credential control. No Solver, production pilot or device-control scope changed. PR #27 remains OPEN for human merge review.
