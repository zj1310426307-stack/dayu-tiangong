## FIX1 Summary

- supersedes the pre-FIX1 60/70/80 convergence artifact without deleting its historical evidence
- freezes a pre-run 18/54/162, factor-three nested grid family with exact Gate face, Pump control-volume centroid, and monitor centroid on every level
- adds positive observed orders, Richardson/asymptotic estimates, fine-grid error estimates, and explicit separation of Gate-event spatial error from the 5 s event-locator tolerance
- adds `dayu.d3a-final-convergence.v2`, a dedicated FIX1 long test, and a shipping collector that rejects v1 or incomplete evidence
- keeps the core hydraulic equations, Manning/bed/nonprismatic operators, Gate/Pump equations, runtime envelope, friction predictor, D2 task platform, API, OpenAPI, and frontend contracts unchanged

## Current Evidence

- FIX1 implementation/evidence head: `d0aa74860471acfeb92a6cccaae5385059702cd9`
- FIX1 artifact SHA-256: `90fb93102d46604b37751b4f3d3b1fdeb99d9333512d80748739355e10c13f0a`
- Python 3.12.13 immutable shipping image: 7 passed / 0 failed / 0 skipped
- MODEL02: 375 passed
- D2/native-v4 contracts: 152 passed / 33 external-service gated skipped
- legacy/D1: 26 passed
- OpenAPI generated client: 0 drift
- frontend typecheck and production build: PASS
- all seven FIX1 completion gates: true

Smooth observed orders are all finite and positive. Peak Q has `p=0.302299`, below the preferred 0.7 level, and its 13.99% Richardson fine-grid estimated relative error is explicitly disclosed; the frozen grid was not changed after seeing results.

## Hosted Status

Evidence head `d0aa74860471acfeb92a6cccaae5385059702cd9` passed all four workflows:

- model02 push `33272555233`: SUCCESS
- hydraulic-platform push `33272555234`: SUCCESS
- model02 pull request `33272557735`: SUCCESS
- hydraulic-platform pull request `33272557769`: SUCCESS

This includes Python 3.11 `D3A scientific validation`, Python 3.12 `D3A shipping science`, Ubuntu/Windows MODEL02, D1/D2, PostGIS/Worker, frontend, and OpenAPI gates. The push shipping artifact records the exact evidence head and passed 49/49 tests; downloaded science values match the checked artifact except for machine-dependent runtime timings.

Status: `FIX1 GATES PASS / MERGE READY FOR INDEPENDENT REVIEW`.

## Scope

Validation-only: single Branch, fully wet, forward subcritical flow with `Fr<=0.8`, positive effective Manning roughness, explicit descending bed, gradual non-identical tabulated Profiles, one completed-interface Gate, and one external Q-H/Q-efficiency Pump. This does not claim multi-Branch networks, wetting/drying, reverse or supercritical flow, internal Pumps, calibration, forecasting, or production water decisions.

PR #12 remains OPEN and NOT MERGED. No D3A tag is created, and no D3B branch is created or started by this work.
