# HYDRO-MODEL-02-D1 Current Pump/Gate Audit

- Audit date: 2026-08-26
- Base: `main@c00a05fa508f3f186e87f05dd26b67ea88cfc0fc`
- Branch: `feature/HYDRO-MODEL-02-D1-pump-strong-coupling`
- Scope: Pump Q-H/Q-efficiency strong coupling and one-Branch Gate/Pump closure

## 1. Compatibility baseline

The remote baseline was refreshed before development. `HEAD` and `origin/main` were both `c00a05f`, ahead/behind was `0/0`, and the worktree was clean. The focused frozen suite passed before modification:

```text
326 passed in 112.06s
```

The suite covered `tests/model02`, the legacy Pump/Gate domain tests, the v3 24-hour Gate/Pump demonstration, and dispatch tests. D1 must remain an explicit opt-in route; `dayu.model-input.v1/v2/v3`, legacy `OnOffPump`, and v4-lite-1 through v4-lite-6 remain frozen.

## 2. Static Pump parameters

There are two Pump models with different ownership:

1. `model/structure/pump.py::PumpModel` is the legacy equipment/dispatch model. It stores design flow per unit, unit limits, minimum run/stop time, maximum starts, an operating-head envelope, and an efficiency curve.
2. `model/solver/finite_volume/structures.py::OnOffPump` is the v4-lite finite-volume structure. It stores only Pump identity, one source-cell index, `design_flow`, fixed enabled state, and an optional one-shot threshold control.

The v4-lite input mirrors the second model through `ExternalPumpInput`: public Pump identity, Branch/Section binding, external outlet, ON/OFF state, `design_flow_m3_s`, and fixed/one-shot control.

## 3. Current Pump runtime

The finite-volume runtime is an external sink. `OnOffPump.evaluate_stage()` ignores stage hydraulics and returns:

```text
enabled -> flow = design_flow
disabled -> flow = 0
```

`integrator._forward_euler_stage_raw()` subtracts this flow from the bound cell mass and subtracts `Q_pump * local_velocity` from its advective momentum. A negative updated area rejects the trial and enters the existing time-step retry path. Accepted Stage 1/Stage 2 flows are trapezoidally integrated into `pump_outflow_volume`.

The Pump is not an internal transfer. There is no target cell, downstream device face, or target momentum flux in the v4-lite runtime.

## 4. Q-H and Q-efficiency support

The legacy equipment model has a generic piecewise-linear `interpolate_curve()` and computes power from a supplied head and an efficiency curve indexed by flow ratio. It does not solve a Pump curve against a system curve.

The finite-volume Pump has no Q-H curve, no Q-efficiency curve, no system-loss model, no identical-unit parallel law, no root bracket, and no operating-point evidence. It therefore does not use current stage water levels to determine Pump discharge.

The existing v4-lite result intentionally enforces constant ON flow. `MvpPumpSeries` rejects more than one non-zero ON flow, which is incompatible with hydraulic D1 behavior and must remain frozen for pre-D1 policies.

## 5. Current power and energy

The legacy `PumpModel.evaluate()` calculates:

```text
P_in = rho * g * Q * H / efficiency
energy = P_in * elapsed_seconds / 3600
```

This calculation is outside the finite-volume stage operator and receives head as an external argument. The v4-lite path emits only time/status/flow and no Pump power, efficiency, head, or cumulative energy. The finite-volume accepted-step budget has both RK stage flows but no stage Pump power/evidence.

## 6. Pump control and event semantics

The finite-volume Pump supports fixed ON/OFF and accepted-state one-shot start. The controller latch is synchronized only after an accepted conservative step; RK stages and rejected trials read an immutable committed command. The bracketed policy can replay from the previous accepted state and atomically commit simultaneous Gate/Pump one-shot events at the accepted right bracket.

There is no stop transition, hysteresis, minimum runtime/stop time, or maximum-start state machine in the finite-volume path. The legacy mutable `PumpControlState` is not used by v4-lite and is not suitable as the second physical state authority for stage coupling.

## 7. Gate completed-interface scope

`FixedGate` supports the explicit `submerged-orifice-energy-momentum-v1` policy. At every RK stage it solves the restricted total-head/orifice equation and supplies one mass flux, two side-specific `Q^2/A + gI1` momentum fluxes, reaction evidence, convergence evidence, and subcritical/submergence gates. A controlled completed Gate remains an impermeable completed interface through the located event step and applies the new opening only to the next accepted subinterval.

Both API and core preflight currently require exactly one completed-interface Gate and no Pump. This is the deliberate C2b/C2c boundary that D1 must extend only for one explicitly versioned Gate+external-Pump capability.

## 8. v4-lite routing and ownership

- `model/api/v4_lite.py` owns the strict snapshot contract and version-specific fail-closed scope.
- `model/adapters/v4_lite.py` owns deterministic mesh/runtime projection, input/policy hashes, and result projection.
- `model/solver/finite_volume/integrator.py` owns per-stage boundary, Gate, Pump, flux/source, and Manning evaluation.
- `model/solver/finite_volume/solver.py` owns accepted-state control, event replay, retries, water balance, and runtime quality gates.
- `model/result/mvp.py` independently validates result semantics and evidence.

The existing version checks have accumulated in `v4_lite.py`. D1 will add a lightweight capability manifest/registry for the new route while leaving the frozen legacy validation branches intact.

## 9. D1 change boundary

D1 will add pure typed Pump curve/system/operating-point/evidence objects, an accepted-state hysteresis controller, an explicit external-sink hydraulic Pump, per-stage power/energy evidence, and one v4-lite D1 capability. Stage 2 must re-evaluate the Pump against its own source stage and time-varying explicit outlet stage.

D1 will not change legacy `PumpModel` or `OnOffPump`, reinterpret old snapshots, add a backend/API route, implement internal Pump transfer, add wet/dry or reverse flow, generalize Gate physics, or claim a general Pump station/network solver.

## 10. Mandatory fail-closed gates

The D1 route must reject malformed/non-finite/non-monotone curves, invalid efficiency, unit-count violations, invalid hysteresis timing, missing outlet stage, duplicate/conflicting placement, dry source cells, unsupported Gate scope, missing/no-root/non-converged operating points, retry/event exhaustion, and failed water balance. No failure may fall back to design flow, mass-only Gate, clamping, extrapolation, or a nearest curve point.
