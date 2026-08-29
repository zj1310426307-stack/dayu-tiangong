# HYDRO-MODEL-02-D2-RC1 Freeze Integrity Boundary

## Status and purpose

This document records the implemented RC1 candidate behavior for native-v4 frozen
input integrity. It is not an RC1 release declaration, a hosted-CI result, or evidence
of any larger scientific capability.

The important distinction is between evidence that RC1 recomputes and identity that it
deliberately trusts as persisted. A syntactically valid SHA-256 value is not, by itself,
treated as proof that every upstream D2 row has been reconstructed.

## Evidence classes

| Evidence | RC1 treatment | Boundary |
|---|---|---|
| Frozen Dispatch Plan | Recompute `snapshot_hash(frozen_snapshot)` and compare it with `frozen_snapshot_hash` | Mismatch is a readiness error |
| Pump curve identity | Recompute the canonical curve payload and compare it with `Pump.curve_hash` | Only the fields listed below are in this hash domain |
| Dataset Version identity | Require a lowercase SHA-256 `content_hash` and status `approved` or `published`, then trust the persisted GIS-core identity | RC1 does not claim full D2 content recomputation |
| Profile identity | Require exactly one active Profile and a lowercase SHA-256 `profile_hash`, marked `persisted/import-validated` | Historical import hash policies cannot be reconstructed unambiguously |
| Solver Registry | Resolve the route on the server and recompute the Registry hash | Client solver IDs are consistency assertions, not provenance sources |
| Frozen v4 source/runtime | Recompute source, runtime projection, mesh, solver-policy, validation-policy, and Registry hash domains | These hashes protect the frozen payload; they are not signatures |

## Dispatch Plan revalidation

Readiness, preview, and task freeze all pass through the database assessment. A usable
plan must be `frozen`, belong to the same Simulation Case and Dataset Version, contain a
mapping-valued frozen snapshot, and have a canonical lowercase SHA-256 digest.

The stored digest is then revalidated:

```text
snapshot_hash(plan.frozen_snapshot) == plan.frozen_snapshot_hash
```

A mismatch produces `D2_CONTROL_PLAN_HASH_MISMATCH` and prevents native-v4 task
creation. The authoritative Gate and Pump selection is read from the already frozen
path:

```text
plan.frozen_snapshot.plan.evaluation_config.native_v4.gate_id
plan.frozen_snapshot.plan.evaluation_config.native_v4.pump_id
```

Both IDs must be positive integers. Each asset is resolved by its frozen ID together
with the Simulation Case Dataset Version, and its hydraulic Section bindings must
belong to the selected Branch. The resulting source snapshot freezes the public Gate
and Pump identities; later mutable-table selection is not used by the Worker.

## Pump curve hash domain

`Pump.curve_hash` is recomputed from one canonical payload with exactly these inputs:

```text
policy_id
unit
head_curve.points[]         = {flow_m3s, head_m}
efficiency_curve.points[]   = {flow_m3s, efficiency}
source_revision
```

Point order is explicit; readiness does not sort the arrays or invent missing values.
For D1, the policy must be `d1-piecewise-linear-qh-qeta-si-v1`, the unit must be `SI`,
and the source revision must be nonblank. Changing any field above changes the
recomputed identity.

`system_loss` and `outlet_stage` are required and are frozen into the native-v4 input,
but they are not members of `Pump.curve_hash`. They are subsequently protected as part
of the complete source snapshot hash. This distinction prevents the curve hash from
being described as a hash of every Pump runtime field.

## Dataset and Profile trust boundary

Dataset Version readiness accepts only `approved` or `published` rows with a canonical
lowercase SHA-256 `content_hash`. It emits
`D2_DATASET_HASH_PERSISTED_IDENTITY` to state that the value is the persisted GIS-core
Dataset identity. RC1 does not reconstruct all D2 hydraulic/control content and does
not claim that the persisted Dataset digest covers every D2 table.

For each Cross Section, readiness requires exactly one active Profile. The persisted
`profile_hash` must be a canonical lowercase SHA-256 value and is copied into the
source contract with:

```text
profile_hash_trust = "persisted/import-validated"
```

`D2_PROFILE_HASH_PERSISTED_IDENTITY` records that historical import hash policies are
not unambiguously reconstructable from current rows. The runtime mesh hash still
covers the actual frozen Profile points used by the numerical projection; that does
not turn the historical `profile_hash` itself into an RC1 recomputation.

## Registry authority and Case notes

Task creation resolves v1, v2, v3, and v4 through the server-side Solver Registry. An
omitted solver ID is server-selected; an explicitly supplied ID must equal the
registered route. The task row receives the resolved solver, capability, runtime
adapter, result schema, and Registry hash from the server.

For native v4, `capability_scope`, `capability_exclusions`, and human-readable known
limitations are emitted from the Registry. The strong v4 parser requires the scope and
exclusion tuples to match the active Registry exactly. `case_notes` is a separate
tuple copied from `SimulationCase.v4_configuration`; it is provenance-only in the
runtime projection and cannot add, remove, or override Registry capability.

## Shadow transaction boundary

Shadow creation validates both builders and then stages the group, independent v3 and
v4 tasks, and both role bindings in one database transaction. The internal task
builder only constructs and flushes; it does not commit. Success performs one commit,
while any failure rolls back the group and both tasks, so a v4 freeze failure cannot
leave an orphan v3 task.

Migration `20260828_0021` additionally makes `(comparison_group_id, group_role)` unique.
The comparison service derives `pending`, `running`, `ready`, `failed`, or `cancelled`
from child states. A diagnostic `not_ready` response can still describe an incomplete
or non-comparable pair; shadow output never designates legacy v3 as truth.

This atomicity is limited to creation in the application database. It is not a
distributed transaction with Celery, a remote artifact store, or external systems.

## Claims explicitly not made

- no RC1 PASS or release-readiness claim;
- no full D2 Dataset content-hash recomputation;
- no unambiguous recomputation of historical Profile hashes;
- no cryptographic signing or external provenance attestation;
- no change to the frozen D1 scientific scope;
- no production calibration, dispatch approval, IAM, or disaster-recovery claim.
