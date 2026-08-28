# HYDRO-MODEL-02-D2 Migration Report

## Lineage

- D2 base revision: `20260828_0020`;
- RC1 candidate revision: `20260828_0021`;
- 0021 parent: `20260828_0020`;
- 0020 parent: `20260818_0019`;
- policy: additive strengthening; migration 0020 is not rewritten.

## D2 base bindings in 0020

Revision 0020 introduced:

- `simulation_case.v4_configuration`;
- `boundary_condition.hydraulic_node_id` with a Dataset Version composite FK;
- Gate upstream/downstream hydraulic Section IDs;
- Pump hydraulic Section ID, curve policy/unit/source/hash, system loss, and outlet
  stage;
- task Registry/projection provenance, shadow group/role, native result tables, Control
  Events, and Artifact metadata.

It also created `simulation_task_group`, `hydraulic_task_section_result`,
`hydraulic_task_gate_result`, `hydraulic_task_pump_result`,
`hydraulic_task_control_event`, and `hydraulic_task_artifact`.

## RC1 Dataset and Shadow strengthening in 0021

Revision 0021 adds guarded same-Dataset identities:

| Child evidence | Composite identity |
|---|---|
| Section result | `(branch_id, dataset_version_id)` -> hydraulic Branch |
| Gate result | `(canonical_gate_id, dataset_version_id)` -> Gate |
| Pump result | `(canonical_pump_id, dataset_version_id)` -> Pump |
| Gate Control Event | `(canonical_gate_id, dataset_version_id)` -> Gate |
| Pump Control Event | `(canonical_pump_id, dataset_version_id)` -> Pump |

Gate and Pump receive supporting unique `(id, dataset_version_id)` keys. Control Events
gain a non-null `dataset_version_id`, typed `canonical_gate_id` and
`canonical_pump_id`, and checks requiring the typed identity to agree with
`structure_type` and the compatibility `canonical_structure_id`.

For Shadow Groups, 0021 constrains the durable status vocabulary and makes
`(comparison_group_id, group_role)` unique. The application creation path complements
these database constraints by staging the group, both tasks, and both roles in one
transaction with one commit and rollback-all failure behavior.

## Fail-fast upgrade boundary

Before installing the new constraints, 0021 rejects existing contradictions:

- missing or cross-Dataset Gate/Pump result assets;
- missing or cross-Dataset Section-result Branches;
- invalid or cross-Dataset typed Control Event assets;
- unknown Shadow Group states or duplicate group roles.

The migration does not silently relabel contradictory evidence. Existing Control Event
rows are backfilled from their task's Simulation Case Dataset Version only after the
preflight proves the typed asset identity is valid.

## Downgrade boundary

Downgrade from 0021 removes only RC1 strengthening and returns to 0020. It has an
explicit guard against truncating active RC1-only Artifact reconciliation states.
Downgrade from 0020 to 0019 then removes D2-only tables, fields, constraints, and
bindings while retaining legacy schema/data; D2-only results are not preserved.

## Evidence status

Local RC1 validation created a fresh dedicated PostgreSQL database, upgraded all
revisions through 0021, downgraded exactly to 0020, re-upgraded to 0021, and confirmed
`20260828_0021` as the single head. A separate fault-test database containing an
RC1-only reconciliation state was intentionally rejected by the downgrade guard,
confirming that evidence is not silently truncated.

The local migration gate is **PASS**. RC1 still must not be declared PASS until the
same 0021 upgrade/schema checks run successfully in Hosted PostgreSQL 16 with PostGIS
and TimescaleDB on the final pushed commit. Historical 0020 Actions evidence is not
used as substitute evidence.
