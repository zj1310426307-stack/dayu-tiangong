# HYDRO-MODEL-02-D2-RC2 Release Readiness

- Date: 2026-08-28
- Scope: runtime build identity, immutable Python 3.12 release environment, and
  bounded queued-delivery recovery
- Current decision: **LOCAL PASS / HOSTED PENDING — PR #11 remains OPEN**

## Promotion gates

- [x] RuntimeBuildIdentity is the single version/commit/build authority.
- [x] CI and release reject anything except a lowercase 40-character Git SHA.
- [x] Legacy and native-v4 Workers fail closed before solving a mismatched task.
- [x] Task, snapshot, result, and Artifact provenance expose reproducible build identity.
- [x] The local shipping smoke runs Backend and both Workers from one
  OCI-revision-labelled Python 3.12 image; Hosted confirmation remains below.
- [x] Queued recovery handles a lost message with non-null `queue_job_id` at a bounded rate.
- [x] Migration 0022 round-trip and single-head checks pass on fresh PostGIS.
- [x] Local Worker integration, D2 fault recovery, D1 regression, full repository,
  frontend contract, and frontend OpenAPI gates pass.
- [ ] Exact Hosted `D2 shipping runtime` passes on the final candidate SHA.
- [ ] Only after that success, main protection preserves the existing nine required
  contexts and appends the exact tenth context.
- [ ] PR #11 remains not merged and no D2 tag exists.

RC2 does not authorize merge or tag creation. After all boxes have observed evidence,
the only permitted status is “MERGE READY FOR INDEPENDENT REVIEW.”
