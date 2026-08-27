# HYDRO-MODEL-02-D2 Hydraulic Result v3

## Contract

`dayu.hydraulic-result.v3` is the platform result identity for native-v4 tasks. The
bounded summary exposes input/result schema, solver/capability/adapter IDs, source and
projection hashes, canonicalization, engine provenance, numeric platform, water
balance, diagnostics, row counts, known limitations, and artifact manifests.

## Relational series

Normal UI reads use output-interval rows only:

- `hydraulic_task_section_result`: authoritative Section H/Q/V/control volume;
- `hydraulic_task_gate_result`: opening, flow, face stages, head loss, force evidence,
  and regime;
- `hydraulic_task_pump_result`: state, units, operating point, efficiency, power,
  cumulative energy, iterations, and regime;
- `hydraulic_task_control_event`: accepted Gate/Pump commands and pre/post evidence.

The legacy `simulation_result`, `junction_result`, and `structure_result` tables are not
used for native-v4 output.

## Pre-persistence quality gates

Persistence rejects non-finite values, non-positive control volumes, failed or
out-of-tolerance water balance, Pump head-residual failure, incomplete Gate/Pump stage
evidence, provenance mismatch, non-monotonic output/event axes, or decreasing cumulative
energy. Stage counts must equal two evaluations per accepted SSP-RK2 step for each
structure.

## Evidence artifact

Full stage evidence is `dayu.hydraulic-stage-evidence.v1`, media type
`application/x-ndjson+gzip`. It includes Gate and Pump stage evaluations, control
events, retry diagnostics, water balance, and the projection manifest. Publication is
deterministic, atomic, hash-verified, and path-bounded as specified by
ADR-HYDRO-D2-0002.

For the frozen D1 six-hour case the expected output is 20 Sections × 25 output times,
25 Gate rows, 25 Pump rows, 3 events, and 1,530 artifact records.

