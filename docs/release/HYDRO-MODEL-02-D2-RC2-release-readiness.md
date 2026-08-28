# HYDRO-MODEL-02-D2-RC2 Release Readiness

- Date: 2026-08-28
- Scope: runtime build identity, immutable Python 3.12 release environment, and
  bounded queued-delivery recovery
- Implementation candidate: `5e6a0aed399ad4a5b17614e21f4923a1aacfaf98`
- Current decision: **MERGE READY FOR INDEPENDENT REVIEW — PR #11 remains OPEN**

## Promotion gates

- [x] RuntimeBuildIdentity is the single version/commit/build authority.
- [x] CI and release reject anything except a lowercase 40-character Git SHA.
- [x] Legacy and native-v4 Workers fail closed before solving a mismatched task.
- [x] Task, snapshot, result, and Artifact provenance expose reproducible build identity.
- [x] Local and Hosted shipping gates run Backend and both Workers from one
  OCI-revision-labelled Python 3.12 image.
- [x] Queued recovery handles a lost message with non-null `queue_job_id` at a bounded rate.
- [x] Migration 0022 round-trip and single-head checks pass on fresh PostGIS.
- [x] Local Worker integration, D2 fault recovery, D1 regression, full repository,
  frontend contract, and frontend OpenAPI gates pass.
- [x] Exact Hosted `D2 shipping runtime` passed twice on the implementation candidate
  SHA in runs `33156277870` and `33156280523`.
- [x] Only after that success, main protection preserved the existing nine required
  contexts and appended the exact tenth context.
- [x] Hosted artifact `d2-runtime-build-identity` (`9679812945`) is present and not
  expired for the implementation candidate SHA.
- [x] PR #11 remains not merged and no D2 tag exists.

RC2 does not authorize merge or tag creation. After all boxes have observed evidence,
the only permitted status is “MERGE READY FOR INDEPENDENT REVIEW.”
