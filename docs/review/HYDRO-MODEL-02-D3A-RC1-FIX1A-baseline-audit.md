# HYDRO-MODEL-02-D3A-RC1-FIX1A Baseline Audit

- Date: 2026-08-30
- Baseline head: `4ecfd3bead769af38381f4d4b6a9b3523a64feef`
- Branch: `feature/HYDRO-MODEL-02-D3A-engineering-single-river`
- PR: #12 remains OPEN and NOT MERGED

## Finding

The FIX1 global `peak_discharge_m3s` values were computed as maxima across all
section/time samples, but the artifact did not record their argmax coordinates.
A read-only replay of the unchanged frozen 18/54/162 grid family found:

| Level | abs(Q) (m3/s) | Time (s) | Section chainage (m) |
| --- | ---: | ---: | ---: |
| coarse | 0.22199067209519152 | 7200 | 250 |
| medium | 0.24541315711441320 | 4500 | 1250 |
| fine | 0.26221666161760204 | 4500 | 972.2222222222222 |

Both time and chainage drift. The three values therefore do not represent the
same space-time observable and cannot remain a smooth Richardson acceptance
metric. The FIX1 `p=0.302299` and `13.99%` fine estimated relative error remain
historical diagnostics and an explicit known limitation, not a validated error
bound.

## Frozen FIX1A decision

1. Record global peak-Q absolute/signed value, argmax time, section id and
   chainage for every level.
2. Reclassify global peak-Q as a non-smooth global extremum because argmax drift
   is observed.
3. Add peak discharge at the exact fixed 2850 m monitor to the smooth spatial
   convergence table.
4. Version the release artifact as `dayu.d3a-final-convergence.v3`; retain v2 as
   historical FIX1 evidence.
5. Fail closed if a future run does not reproduce the drift classification:
   that branch requires additional refinement rather than automatic acceptance.
6. Re-run the existing Python 3.11 and Python 3.12 science checks without
   renaming their protected contexts.

## Non-goals

No hydraulic equations, physical/control inputs, grid family, runtime envelope,
friction predictor, D2 platform, API/OpenAPI or frontend contract may change.
PR #12 is not merged; no D3A tag or D3B branch is created.
