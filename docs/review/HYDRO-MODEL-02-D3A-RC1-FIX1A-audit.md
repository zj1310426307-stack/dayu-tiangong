# HYDRO-MODEL-02-D3A-RC1-FIX1A Audit

- Date: 2026-08-30
- Baseline: `4ecfd3bead769af38381f4d4b6a9b3523a64feef`
- Baseline audit commit: `5e48c0a`
- PR: #12 remains OPEN and NOT MERGED
- Current local status: `LOCAL FIX1A GATES PASS / HOSTED PENDING / PR NO-GO`

## Classification audit

The unchanged 18/54/162 family places global peak-Q at:

| Level | Time (s) | Section chainage (m) | abs(Q) (m3/s) |
| --- | ---: | ---: | ---: |
| coarse | 7200 | 250 | 0.22199067209519152 |
| medium | 4500 | 1250 | 0.24541315711441320 |
| fine | 4500 | 972.2222222222222 | 0.26221666161760204 |
| fine CFL/2 | 4500 | 1027.7777777777778 | 0.26223702008907920 |

The argmax changes in both space and time across the spatial sequence and also
changes chainage under fine-grid time refinement. FIX1A therefore classifies it
as `non-smooth-global-extremum`; it is recorded but excluded from the smooth
acceptance table.

The FIX1 legacy diagnostic (`p=0.3022986331`, Richardson fine estimated relative
error `13.992205%`) is retained as the explicit `13.99%` known limitation and is
marked invalid as a smooth error bound.

## Replacement Q evidence

Peak Q at the exact fixed 2850 m monitor is `0.185626630754`,
`0.223881120602`, and `0.227234800516 m3/s`. Differences decrease from
`0.038254489848` to `0.003353679914 m3/s`; observed order is `2.2157067924`,
with fine estimated relative error `0.141618%`.

## Contract and fail-closed audit

- schema is `dayu.d3a-final-convergence.v3`;
- every level records global peak absolute/signed Q, time, sample, section id,
  section chainage, control-volume centroid and tie count;
- smooth metrics contain fixed-monitor Q and do not contain global peak-Q;
- no-drift classification fails closed and requires a pre-frozen finer level;
- the collector rejects v1/v2 or missing/misclassified FIX1A evidence;
- all ten completion gates are true in the checked v3 artifact.

## Local verification

| Suite | Result |
| --- | --- |
| Python 3.12 FIX1A science | 9 passed |
| Python 3.11 FIX1A science | 9 passed |
| MODEL02 non-long | 375 passed |
| legacy hydraulic | 26 passed |
| D3A model-engine contracts Python 3.11 | 43 passed |
| D3A model-engine contracts Python 3.12 | 43 passed |
| workflow YAML / Python AST | PASS |
| v2 collector negative control | rejected as required |

The two interpreter artifacts differ only in three near-machine-precision
`relative_water_balance_error` values; all classification, mesh, argmax,
convergence and gate fields match. Those residuals remain below the unchanged
`1e-10` scientific tolerance and are not authoritative bitwise identities.

## Scope audit

Only the reference/test evidence path, collector, model02 workflow, checked
artifact and D3A documentation change. Hydraulic equations, Manning, bed and
nonprismatic operators, Gate/Pump equations, runtime envelope, friction
predictor, D2 platform, API/OpenAPI and frontend remain unchanged.

Hosted Python 3.11 and Python 3.12 checks must still pass at the final PR head.
Until then PR #12 remains NO-GO and must not be merged; no D3A tag or D3B branch
is created.
