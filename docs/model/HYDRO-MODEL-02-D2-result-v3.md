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
events, retry diagnostics, water balance, and the projection manifest. Canonical JSONL
ordering, UTF-8 encoding, gzip `mtime=0`, byte size, record count, and SHA-256 make the
file deterministic and independently checkable.

Publication has three boundaries rather than one cross-system transaction:

1. write/fsync and verify a temporary file; persist all result rows and `prepared`
   Artifact metadata using the active execution token, then commit;
2. atomically rename to the deterministic final file under `DAYU_STORAGE_ROOT`;
3. CAS the task to `success/published` and Artifact metadata to `published` in one
   database transaction.

Normal summaries, series, manifests, and downloads require a successful task and
published Artifact metadata. Download additionally resolves the root-relative key
inside `DAYU_STORAGE_ROOT` and rechecks byte length and SHA-256 before returning the
file.

Crashes between prepared commit, rename, and final CAS enter the deterministic
reconciliation contract. The CLI is JSON dry-run by default and modifies state only
with `--apply`; it never scans outside the configured storage root or auto-promotes a
scientific failure. Cases A-F and the stale/retry gate are specified in
`HYDRO-MODEL-02-D2-RC1-result-artifact-reconciliation.md` and
ADR-HYDRO-D2-RC1-0004.

For the frozen D1 six-hour case the expected output is 20 Sections × 25 output times,
25 Gate rows, 25 Pump rows, 3 events, and 1,530 artifact records.

These contracts describe the RC1 candidate implementation and do not declare fault
tests, hosted services, or the release gate PASS.
