# HYDRO-MODEL-02-D2 Native Input v4

## Purpose

`dayu.model-input.v4` is the authoritative platform snapshot for the frozen D1
single-Branch Gate/external-Pump capability. It is not the direct numerical
`v4-lite-7` DTO and it never passes through the v3-to-v2 legacy adapter.

## Authoritative sources

The database builder reads only DatasetVersion, SimulationCase, hydraulic Network,
Branch/Reach, CrossSection/Profile/Point, BoundaryCondition, Gate, Pump, and a frozen
DispatchPlan. It does not infer identity from map proximity, list order, frontend
indices, legacy compatibility mappings, or coincident integer values.

The typed top-level contract contains:

```text
schema_version / solver_selection / dataset_version / simulation_case
coordinate_reference / network / branches / reaches
cross_sections / cross_section_profiles / initial_state / boundaries
structures.gates / structures.pumps / control_plan
numerical_policy / validation / provenance / known_limitations
```

## Readiness

The readiness service first validates platform data and D2 scope, then calls the same
strict v4 projection/parser used for execution. P0 findings are structured by code,
severity, entity, field path, and message. Any P0 finding prevents task creation.

The frozen capability requires exactly one confirmed Branch, 3–200 identical Profiles,
Manning n=0, fully wet forward strictly subcritical initial state, explicit Q(t)/H(t)
boundaries covering the duration, one completed-interface Gate, and one external
hydraulic Q-H/Q-efficiency Pump with registered policies and frozen controls.

## Projection and hash domains

`project_v4_to_v4_lite` is pure and produces the D1 runtime plus a manifest. The source
snapshot is retained independently. The following identities are recomputable:

- authoritative source input hash;
- runtime projection hash;
- mesh hash;
- solver-policy hash;
- validation-policy hash;
- registry hash;
- Dataset content, Profile, Pump curve, control-plan, and engine provenance carried by
  the source snapshot.

Only explicit non-physical contract defaults may be defaulted. Missing physical,
boundary, Gate, Pump, curve, placement, or control values fail closed.

## Task freeze

The API freezes the complete canonical source in the task-creation transaction.
`task.config` contains storage/execution metadata only; v4 rejects legacy runtime
overrides. Workers never rebuild from mutable business tables. After claim, the v4
Worker recomputes all frozen hash domains and refuses any mismatch.

## Compatibility

v1 remains the single-river legacy solver; v2 remains the legacy network solver; v3
remains authoritative input adapted to v2. The registry routes only v4 to
`saint-venant-fv-hll-ssp-rk2-d1-v1` with capability
`single-branch-gate-external-pump-d1-v1` and adapter
`v4-to-v4-lite-7-d1-v1`.

