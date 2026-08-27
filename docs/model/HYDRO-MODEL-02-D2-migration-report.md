# HYDRO-MODEL-02-D2 Migration Report

## Lineage

- Revision: `20260828_0020`
- Parent: `20260818_0019`
- Policy: additive only; no legacy column/table is deleted or renamed on upgrade.

## Added authoritative bindings

- `simulation_case.v4_configuration`;
- `boundary_condition.hydraulic_node_id` with Dataset Version composite FK;
- Gate upstream/downstream hydraulic Section IDs;
- Pump hydraulic Section ID, curve policy/unit/source/hash, system loss, and outlet stage.

## Added task lifecycle/provenance

Solver/capability/adapter/result schema, execution mode/phase, runtime/mesh/policy/
registry hashes, artifact state, shadow group/role, last event, accepted-step count, and
categorized numerical retry counts were added as nullable or defaulted fields so legacy
rows remain valid.

## Added tables

`simulation_task_group`, `hydraulic_task_section_result`,
`hydraulic_task_gate_result`, `hydraulic_task_pump_result`,
`hydraulic_task_control_event`, and `hydraulic_task_artifact`, with task/time indexes,
identity FKs, uniqueness constraints, and state/hash/count checks.

## Downgrade boundary

Downgrade to `20260818_0019` removes D2-only tables, fields, constraints, and bindings.
It intentionally does not preserve D2-only results while leaving all legacy schema/data
in place. Hosted CI executes fresh upgrade, downgrade to 0019, re-upgrade, and a
single-head assertion against PostgreSQL 16 with PostGIS and TimescaleDB.

## Evidence status

The interactive Windows host has no Docker CLI, so it cannot supply honest local
PostGIS migration evidence. The authoritative real-service result is the hosted
`PostGIS migration` job in Actions run `33113201345`: fresh upgrade, schema assertion,
downgrade to `20260818_0019`, re-upgrade to head, and single-head assertion all passed.
