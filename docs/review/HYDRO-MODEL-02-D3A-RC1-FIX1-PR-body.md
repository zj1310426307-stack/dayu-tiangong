## FIX1A Summary

- supersedes FIX1's interpretation of global peak-Q without deleting its historical evidence
- records global peak-Q argmax time, sample, section and chainage at every mesh level
- classifies the global peak as a `non-smooth-global-extremum` because the argmax drifts in time and chainage
- excludes global peak-Q from smooth Richardson acceptance and adds fixed-monitor peak-Q convergence at the exact 2850 m monitor
- upgrades the checked artifact and shipping collector to `dayu.d3a-final-convergence.v3`
- keeps the core hydraulic equations, Manning/bed/nonprismatic operators, Gate/Pump equations, runtime envelope, friction predictor, D2 task platform, API, OpenAPI and frontend contracts unchanged

## Current Local Evidence

- baseline head: `4ecfd3bead769af38381f4d4b6a9b3523a64feef`
- baseline audit commit: `5e48c0a`
- FIX1A implementation commit: `d8cd87b`
- FIX1A artifact SHA-256: `60c6279d2675de6fbba30be806eb20bedc5a8e2044e425f4f1a09e6d00d6c149`
- Python 3.12 science: 9 passed / 0 failed / 0 skipped
- Python 3.11 science: 9 passed / 0 failed / 0 skipped
- MODEL02: 375 passed
- legacy/D1: 26 passed
- D3A model-engine contracts: Python 3.11 43 passed; Python 3.12 43 passed
- all ten FIX1A completion gates: true

The global peak-Q argmax moves from `(7200 s, 250 m)` on coarse to
`(4500 s, 1250 m)` on medium and `(4500 s, 972.222... m)` on fine; fine CFL/2
moves it again to `1027.777... m`. It is therefore recorded but not used as
smooth spatial-convergence evidence.

Fixed-monitor peak-Q has `p=2.2157067924` and a `0.141618%` Richardson fine-grid
estimated relative error. The legacy global peak-Q diagnostic's `13.99%` value
is explicitly retained as a known limitation and marked invalid as a smooth
error bound.

## Hosted Status

Evidence head `d20275a39c63336c2b24e68a483c52a0d877b351` passed all four
workflows:

- model02 push `33304871002`: SUCCESS
- hydraulic-platform push `33304871124`: SUCCESS
- model02 pull request `33304874227`: SUCCESS
- hydraulic-platform pull request `33304874197`: SUCCESS

Hosted Python 3.11 science passed 82/82 and Python 3.12.14 shipping science
passed 51/51 for both event types. Downloaded checked, push and PR v3 artifacts
match after excluding runtime and near-machine-precision balance residuals. The
push image records the exact evidence head; the PR image records merge ref
`bc27f97c2a3b210340b029c83c127a27b3d7f1b0`.

Status: `FIX1A GATES PASS / MERGE READY FOR INDEPENDENT REVIEW / PR NOT MERGED`.

## Scope

Validation-only: single Branch, fully wet, forward subcritical flow with
`Fr<=0.8`, positive effective Manning roughness, explicit descending bed,
gradual non-identical tabulated Profiles, one completed-interface Gate and one
external Q-H/Q-efficiency Pump. This does not claim multi-Branch networks,
wetting/drying, reverse or supercritical flow, internal Pumps, calibration,
forecasting or production water decisions.

PR #12 remains OPEN and NOT MERGED. No D3A tag is created, and no D3B branch is
created or started by this work.
