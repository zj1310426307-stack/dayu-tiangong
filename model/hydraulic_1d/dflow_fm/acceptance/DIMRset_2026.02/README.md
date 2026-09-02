# DIMRset_2026.02 controlled-runtime acceptance

Review date: 2026-09-02

This directory is the source-controlled trust root for the development-only
`D-Flow FM + DIMR + FBC` controlled Gate path. It does not contain native
binaries or large Solver outputs.

## Locked identity

- Delft3D tag/commit: `DIMRset_2026.02` / `5a4649830b1e5072caf019fb4850bbdefd9ad431`
- D-Flow FM / DIMR / FBC / HYDROLIB-core: `1.2.184` / `2.00` / `1.6.1` / `1.0.1`
- runtime manifest SHA-256: `52e12a2ea2078a5d01373604bda90781b5c77e7b817297489eb6fd8c030699c8`
- reviewed OCI digest: `sha256:e53a7c22cdce6a63f39357006ba73f2254ace24979c1f374ba111ee52d5b12b9`
- build classification: `NON_BIT_REPRODUCIBLE`; the pinned upstream binaries embed build timestamps. No upstream source patch was used.

## Native cases

| Case | Result | Reviewed fact |
|---|---|---|
| Official D-Flow example 01 | PASS | official D-Flow executable, DIMR entry point |
| Official D-Flow + FBC example 10 | PASS | official coupling and FBC output |
| DF01 | PASS | Dayu model → native run → strict unified H/Q parser |
| DRTC-S01 | PASS | explicit true/frozen-initial fallback transitions at 0/240/480 s; balance residual `6.77e-16` |
| G01 | PASS | two static openings change Gate Q and upstream head; both balances finite and below 0.5% |
| G02 | PASS | FBC schedule transitions at 0/240/480 s; balance residual `5.46e-15` |
| G03 | PASS | water-level threshold changes Gate opening at 360 s; balance residual `9.13e-16` |

Two parallel public-engine G03 runs produced the same control trace SHA-256
`d60ef6273d7d7ec2144b42a10080ffacfc1c7d58df2289573753d55861195405`
and the same timing-independent numerical-result SHA-256
`7dc288bce8bbf86d938ce28bb78846d35b9fdf7393f5cdf7f42c1a0ce967dc92`.
The complete result-envelope hash intentionally includes measured runtime
seconds and is therefore not used as the numerical determinism identity.

## Lifecycle and worker

- cancellation: PASS, `DFLOW_CANCELLED`, owned container cleanup confirmed;
- timeout: PASS, `DFLOW_TIMEOUT`, owned container cleanup confirmed;
- two-job concurrency: PASS, isolated workspaces and identical numerical hash;
- orphan recovery: PASS, exact cidfile + owner-label container removed;
- real Redis/Celery/PostgreSQL worker: PASS, one execution attempt persisted
  33 H/Q rows, 10 finite active Gate rows and 2 control events atomically.

Large native workspaces are retained only under the project verification area
and are excluded from Git. Evidence classification remains
`SYNTHETIC_NUMERICAL_ONLY`; `real_engineering_validation`,
`real_equipment_command`, and `plc_scada_connected` remain false.

The public upstream example 01 used for the executable/runtime gate is a 2D
D-Flow FM case. No public, standalone official 1D example was found in the
locked upstream tree, so this evidence is deliberately not described as an
official 1D benchmark. Dayu DF01 is the real native 1D adapter/parser gate.

## Deliberately unsupported

- Pump dynamic control (`PUMP_NATIVE_CONTROL_LIMITED`;
  P01/P02 not enabled, P03 `BLOCKED_BY_NATIVE_CONTROL_SEMANTICS`);
- hysteresis, minimum hold, cooldown;
- multiple rules for one actuator, priority/tie-break arbitration;
- manual/rule conflict or merger semantics;
- production Gate/Pump capability and real equipment control.
