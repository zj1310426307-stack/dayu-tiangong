# HYDRO-MODEL-02-D2-RC1 Known Limitations

## Status

This is a boundary document for the current RC1 candidate implementation. It does not
state that RC1 has passed, that migration `20260828_0021` has completed hosted
round-trip validation, or that PR #11 is ready to merge.

## Scientific boundary remains unchanged

The machine-readable Registry remains authoritative. Native v4 is limited to:

- `single-branch`;
- `fully-wet`;
- `forward-strictly-subcritical`;
- `flat-bed`;
- `identical-profile`;
- `manning-n-zero`;
- `one-completed-interface-gate`;
- `one-external-qh-qeta-pump`;
- `identical-parallel-pump-units`;
- `validation-only`.

Registry exclusions remain:

- `multi-branch-or-junction`;
- `wetting-drying`;
- `reverse-or-supercritical-flow`;
- `internal-pump`;
- `multiple-gates-or-pumps`;
- `calibration-or-production-decision`.

`case_notes` is Case-specific context only. It cannot override the Registry scope,
exclusions, solver route, or known limitations.

## Frozen-evidence limitations

- Dispatch Plan and Pump curve identities are recomputed before freeze, but hashes are
  mutation evidence rather than signatures or proof of upstream authorship.
- Dataset Version validation accepts only `approved` or `published` persisted GIS-core
  identities. RC1 does not recompute one digest over all D2 tables.
- Profile hashes are trusted as `persisted/import-validated`. Historical import hash
  algorithms cannot be reconstructed unambiguously, even though the actual frozen
  Profile points participate in the runtime mesh hash.
- `Pump.curve_hash` covers curve policy, unit, ordered Q-H points, ordered Q-efficiency
  points, and source revision. `system_loss` and `outlet_stage` are frozen and protected
  by the source snapshot hash, but are outside the curve-hash domain.
- Frozen `gate_id` and `pump_id` prevent Case-wide implicit asset selection; they do not
  prove calibration, field commissioning, or equipment availability.

See `HYDRO-MODEL-02-D2-RC1-freeze-integrity.md` for the exact trust matrix.

## Dataset constraints and migration boundary

Candidate migration `20260828_0021` adds same-Dataset composite foreign keys for
Section-result Branches, Gate results, Pump results, and typed Gate/Pump Control Events.
It also adds typed Event identity checks and one-role-per-shadow-group uniqueness.

The migration fails fast on contradictory existing rows rather than silently blessing
them. Until the 0021 fresh-upgrade, downgrade, re-upgrade, and single-head checks run in
the required hosted PostgreSQL/PostGIS/TimescaleDB environment, those constraints must
not be described as release-validated.

## Shadow and operational boundary

Shadow pair creation is one local database transaction and rolls back all staged rows
on failure. This does not make task enqueueing, Worker execution, artifacts, or any
external system part of a distributed transaction. Comparison remains diagnostic:
legacy v3 is not truth for native v4, and neither path is approved for production water
decisions.

Public-production IAM/RBAC, multi-tenancy, remote object-store durability, automatic
artifact retention, full disaster recovery, engineering calibration, external-model
comparison, PLC/SCADA integration, and real command dispatch remain NO-GO.
