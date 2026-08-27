# HYDRO-MODEL-02-D2 Release Readiness

- Date: 2026-08-28
- Branch: `feature/HYDRO-MODEL-02-D2-v4-task-platform`
- Base / D1 merge: `cc6936d9d48d64c46a78ba85bed77c473e20cff3`
- D1 tag: `hydro-model-02-d1-rc1`
- Pull request: `#11` — https://github.com/zj1310426307-stack/dayu-tiangong/pull/11
- Merge status: **NOT MERGED**

## Release controls

Main requires PRs, strict up-to-date status checks, conversation resolution, blocks
force push/deletion, enforces administrators, and requires zero approvals for the
single-maintainer repository. The four retained D1 checks are MODEL02 Ubuntu/Windows,
Legacy hydraulic, and Frontend contract. After stable hosted success, Backend v4
contract, PostGIS migration, Worker integration, and Frontend OpenAPI were added as
required checks without removing the D1 checks. Full evidence is in
`MAIN_BRANCH_PROTECTION_VERIFICATION.md`.

## D2 gates

| Gate | Status |
|---|---|
| Solver registry / input v4 / pure projection | implemented; local contract tests pass |
| Readiness / preview / immutable freeze | implemented; fail closed |
| Dedicated Worker / progress / cancel / heartbeat | implemented |
| Result v3 / authoritative persistence | implemented |
| Deterministic stage evidence / safe download | implemented |
| API / generated OpenAPI / frontend | implemented; local checks pass |
| Diagnostic v3/v4 shadow | implemented |
| Real migration round-trip | passed — run `33113201345` |
| Real PostGIS/Redis/dual-Worker/API E2E | passed — run `33113201345` |
| D1/model02 cross-platform guard | passed — run `33113201378` |
| D2 pull request | #11, OPEN, NOT MERGED |

## Scientific evidence

The frozen D1 events remain 2940/7740/12540 seconds with 381 accepted steps, Pump
volume 22.023440130973746 m³, energy 0.12252120603722051 kWh, and relative water-balance
error 4.748482309112566e-16. D2 adds platform orchestration only.

## Current decision

`HYDRO-MODEL-02-D2 PASS — release candidate ready for independent PR review.`

PR #11 must remain unmerged in this delivery. Known scientific and platform NO-GO
items are listed in `HYDRO-MODEL-02-D2-known-limitations.md`; D3A remains gated on
independent review of D2.
