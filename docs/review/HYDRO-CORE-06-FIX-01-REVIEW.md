# HYDRO-CORE-06-FIX-01 Review

## 1. Baseline

- Branch: `refactor/hydro-core-06-engine-routing`
- Baseline: `98957e3b07a9ba8b60656181767a94b2bb3ca5a3`
- Target PR: [#24](https://github.com/zj1310426307-stack/dayu-tiangong/pull/24)

## 2. Final Commit

Recorded by the delivery report after this review is committed and the PR checks finish. This review does not invent a commit identity before Git creates it.

## 3. Changed Files

- `model/hydraulic_1d/capabilities.py`, `hydraulic_engine_capabilities.yaml`, `registry.py`
- `tests/hydraulic_1d/test_explicit_engine_routing.py`
- `frontend/src/pages/hydraulic/HydraulicPages.tsx`
- `README.md`, hydraulic architecture/review documents, and REAL-01 readiness template documents.

## 4. Problem Statement

The routing implementation was already frozen, but its audit text described the pre-migration baseline, D-Flow evidence wording could be read too broadly, the registered `pilot` class looked executable, Gate/Pump capabilities were only coarse `GATE`/`PUMP`, and REAL-01 lacked a field-level readiness contract.

## 5. Runtime Evidence Correction

| Evidence | Status | Boundary |
|---|---|---|
| MASCARET official / reviewed runtime acceptance | PASS | Existing production acceptance evidence remains the only production route evidence. |
| D-Flow adapter / dispatch contracts | PASS | Software contracts only. |
| D-Flow source-controlled controlled-runtime acceptance | PASS | Accepted synthetic subset only. |
| D-Flow synthetic numerical evidence | PASS | Registered cases only; no engineering inference. |
| D-Flow official external runtime acceptance | NOT VERIFIED by HYDRO-CORE-06 | No independent engineering acceptance in this phase. |
| D-Flow real engineering validation | NOT STARTED | No real data, calibration, or independent event. |
| D-Flow production eligibility | FALSE | Cannot be promoted by CI or synthetic evidence. |

## 6. Pilot Boundary

`pilot_contract_supported=true` and `pilot_execution_enabled=false` are now explicit in the Engine Catalog for D-Flow FM. The only executable D-Flow task remains the frozen `synthetic` controlled route. REAL-02 must implement a separate pilot entry after REAL-01 data readiness; neither route may fallback to another Engine.

## 7. Capability Changes

Existing `HydraulicStructure.operation_rule_type` is the only new derivation input:

- `fixed` → `GATE_FIXED` / `PUMP_FIXED`
- `time_series` → `GATE_SCHEDULE` / `PUMP_SCHEDULE`
- `water_level_controlled` or `scenario_specific` → `GATE_RULE` / `PUMP_RULE`

The base structure requirement remains present, so a subtype cannot bypass structure support. MASCARET marks all six detailed capabilities `UNSUPPORTED`. D-Flow accepts the existing audited synthetic Gate fixed/schedule/single-threshold-rule and Pump fixed/schedule subsets. `PUMP_RULE` remains `UNVERIFIED` and fails closed. The task-book's suggested “Gate rule without evidence” case differs from this repository because the source-controlled `DRTC-S01/G03/GP03` cases already prove the narrow Gate threshold subset; the unverified Pump-rule test provides the same fail-closed regression boundary without discarding valid evidence.

## 8. REAL-01 Readiness Contract

`docs/hydraulics/pilot-data-readiness.md` now covers required data domains, metadata, status values, blockers, source-to-Domain mapping, and execution boundaries. `templates/real-engineering-pilot-manifest.yaml` is intentionally blank except for explicit missing/not-available state; no real river, Gate, Pump, boundary, or observation data was added.

## 9. Migration Verification

An isolated PostGIS instance upgraded to `20260924_0036`, downgraded to `20260910_0035`, then upgraded to `20260924_0036`. The isolated container, network, and volume were removed after verification. No application migration was added because FIX-01 changes no persisted schema.

## 10. Test Results

| Check | Result |
|---|---|
| Python compile | PASS |
| Ruff changed Python files | PASS |
| Routing/capability/task/worker/MASCARET/D-Flow/frontend-contract regression | PASS: 77 passed, 7 existing runtime-gated skips |
| Frontend Docker TypeScript + production build | PASS |
| OpenAPI generated-client drift | PASS |
| YAML capability/template parse | PASS |
| PostGIS migration roundtrip | PASS |

## 11. Hosted CI

Before FIX-01, PR #24 was `OPEN / CLEAN / MERGEABLE` with all required checks successful, including `hydraulic-platform`, `model02`, and `D-Flow Dispatch Development`. New commit checks are required before merge and are recorded by the delivery report.

## 12. Known Limitations

The D-Flow accepted subsets are synthetic and source-controlled. MASCARET Gate/Pump support remains unsupported. No public production control, real equipment command, PLC/SCADA connection, calibration, independent validation, or automatic Engine fallback exists.

## 13. Deferred Work

- REAL-01 real engineering import and QA
- Calibration and independent validation
- REAL-02 D-Flow Pilot execution
- Production eligibility review
- Optimization and PLC/SCADA integration

## 14. Final Acceptance Matrix

| Item | Status |
|---|---|
| Explicit Engine Routing | PASS |
| Frozen Task Identity | PASS |
| Legacy Migration | PASS |
| MASCARET Production Route | PASS |
| D-Flow Synthetic Route | PASS |
| D-Flow Pilot Contract | PASS |
| D-Flow Pilot Execution | DEFERRED |
| D-Flow Production | NOT ELIGIBLE |
| Gate Capability Granularity | PASS |
| Pump Capability Contract | PASS / UNVERIFIED EXECUTION for `PUMP_RULE` |
| PostGIS Migration | PASS |
| Runtime Evidence Semantics | PASS |
| REAL-01 Data Contract | PASS |
| Real Engineering Import / Calibration / Independent Validation | NOT STARTED |
| Optimization / PLC-SCADA | DISABLED / DISCONNECTED |

## 15. Next Phase Gate

`HYDRO-CORE-06-FIX-01 = PASS` for this closure scope once hosted CI passes. The next task is `HYDRO-DATA-REAL-01`, which may only prepare real engineering data in the unified Domain; it must not open D-Flow production or Pilot execution.
