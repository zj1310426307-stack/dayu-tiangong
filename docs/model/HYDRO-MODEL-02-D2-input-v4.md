# HYDRO-MODEL-02-D2 Native Input v4

## Purpose

`dayu.model-input.v4` is the authoritative platform snapshot for the frozen D1
single-Branch Gate/external-Pump capability. It is not the direct numerical
`v4-lite-7` DTO and it never passes through the v3-to-v2 legacy adapter.

## Authoritative sources

The database builder reads DatasetVersion, SimulationCase, hydraulic Network,
Branch/Reach, CrossSection/Profile/Point, BoundaryCondition, Gate, Pump, and one frozen
DispatchPlan. It does not infer identity from map proximity, list order, frontend
indices, legacy compatibility mappings, or coincident integer values.

The typed top-level contract contains:

```text
schema_version / solver_selection / dataset_version / simulation_case
coordinate_reference / network / branches / reaches
cross_sections / cross_section_profiles / initial_state / boundaries
structures.gates / structures.pumps / control_plan
numerical_policy / validation / provenance
capability_scope / capability_exclusions / case_notes / known_limitations
```

`capability_scope`, `capability_exclusions`, and known limitations are Registry-owned.
`case_notes` is a separate Case annotation and is provenance-only in the runtime
projection; it cannot override Registry capability.

## Readiness and frozen identities

The readiness service validates platform data and D2 scope, then invokes the same
strict v4 projection/parser used for execution. P0 findings are structured by code,
severity, entity, field path, and message. Any error prevents task creation.

The frozen capability requires exactly one confirmed Branch, 3–200 identical Profiles,
Manning n=0, fully wet forward strictly subcritical initial state, explicit Q(t)/H(t)
boundaries covering the duration, one completed-interface Gate, and one external
hydraulic Q-H/Q-efficiency Pump with registered policies and frozen controls.

The Dispatch Plan must be frozen for the same Case and Dataset Version. Readiness,
preview, and freeze recompute:

```text
snapshot_hash(frozen_snapshot) == frozen_snapshot_hash
```

The frozen `plan.evaluation_config.native_v4` inside `DispatchPlan.frozen_snapshot`
must explicitly contain positive `gate_id` and `pump_id` values. Those exact assets are
resolved in the Case Dataset Version and must bind to Sections on the selected Branch.
D2 no longer selects a Dataset-wide first or only Gate/Pump implicitly.

## Projection and hash domains

`project_v4_to_v4_lite` is pure and produces the D1 runtime plus a manifest. The source
snapshot is retained independently. The following identities are recomputable from the
frozen input/runtime:

- authoritative source input hash;
- runtime projection hash;
- mesh hash;
- solver-policy hash;
- validation-policy hash;
- Registry hash.

Pump curve readiness separately recomputes `Pump.curve_hash` from curve policy ID,
unit, ordered Q-H points, ordered Q-efficiency points, and source revision. System loss
and outlet stage are required and frozen, but are outside the curve-hash domain and are
instead protected by the complete source input hash.

Not every upstream identity is recomputed:

- Dataset Version requires a canonical hash and `approved` or `published` status, but
  RC1 trusts that persisted GIS-core identity and does not claim full D2 content
  recomputation;
- Profile requires exactly one active row and a canonical hash recorded as
  `persisted/import-validated`; historical import hash algorithms are not
  unambiguously reconstructable. The mesh hash still covers the actual frozen points.

Only explicit non-physical contract defaults may be defaulted. Missing physical,
boundary, Gate, Pump, curve, placement, or control values fail closed.

## Task freeze and Registry routing

The API freezes the complete canonical source in the task-creation transaction.
`task.config` contains storage/execution metadata only; v4 rejects legacy runtime
overrides. Workers never rebuild from mutable business tables. After claim, the v4
Worker revalidates the frozen source and runtime hash domains and refuses mismatches.

Task creation resolves every v1-v4 schema through the server-side Registry. An omitted
solver ID is server-selected; an explicit solver ID is only an equality assertion.
Task provenance is written from the resolved registration, not copied from the client.

The established routes remain:

- v1: `legacy-single-river-rusanov-v1`;
- v2: `legacy-network-continuity-manning-v1`;
- v3: the same legacy network solver through `v3-to-v2-v1`;
- v4: `saint-venant-fv-hll-ssp-rk2-d1-v1`, capability
  `single-branch-gate-external-pump-d1-v1`, adapter
  `v4-to-v4-lite-7-d1-v1`.

## Shadow creation

A diagnostic shadow pair validates both inputs, stages its group and independent v3/v4
tasks, assigns both roles, and commits once. The internal builder only flushes. Any
failure rolls back all rows, preventing an orphan legacy task. This is database
atomicity only; it does not make later queue execution a distributed transaction.

Detailed evidence boundaries are recorded in
`HYDRO-MODEL-02-D2-RC1-freeze-integrity.md`. These RC1 candidate changes do not expand
the D1 scientific scope and do not, by themselves, establish RC1 PASS.
