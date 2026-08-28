# HYDRO-MODEL-02-D2 Known Limitations

D2 is platform integration of the already frozen D1 scientific subset. It is
validation software, not a calibrated production water-decision system. RC1 integrity
work does not expand that scope and is not declared PASS by this document.

## Registry-owned capability

The Solver Registry is authoritative for solver routing, machine-readable capability
scope and exclusions, and stable human-readable limitations. D2 remains limited to one
confirmed Branch, fully wet forward strictly subcritical flow, flat bed, identical
Profile geometry, Manning n=0, one completed-interface Gate, one external
Q-H/Q-efficiency Pump, identical same-type parallel units, and validation-only use.

`case_notes` is separate Case-specific context. It can describe the selected Case but
cannot override Registry scope, exclusions, solver identity, or scientific
limitations.

Explicit scientific NO-GO items remain:

- Junctions, multiple Branches, loops, wetting/drying, reverse flow, supercritical flow,
  hydraulic jumps, or general river networks;
- internal-transfer Pump hydraulics, multiple Gates/Pumps, heterogeneous or
  variable-speed units, new curve interpolation, new Gate regimes, or continuous Gate
  control;
- positive Manning, nonzero bed slope, non-identical Profiles, engineering calibration,
  HEC-RAS/MIKE comparison, MPC/GA optimization, PLC/SCADA, or real command dispatch.

## Frozen-identity boundary

- Dispatch Plan frozen snapshots and Pump curve identities are recomputed during
  readiness/freeze.
- The Pump curve hash covers policy, unit, ordered Q-H points, ordered Q-efficiency
  points, and source revision. System loss and outlet stage are outside that hash but
  remain required and are protected by the complete frozen source hash.
- Dataset Version accepts only an `approved` or `published` persisted GIS-core identity;
  RC1 does not claim a full recomputation over all D2 content.
- Profile hashes are `persisted/import-validated`; historical import algorithms cannot
  be reconstructed unambiguously. The actual frozen Profile points still participate
  in the runtime mesh hash.
- Frozen `gate_id` and `pump_id` remove implicit Dataset-wide asset selection but do not
  prove calibration or field commissioning.

## Shadow, migration, and operational boundary

Shadow pair creation is atomic within the application database: one group, independent
v3/v4 tasks, and both roles commit together or roll back together. Shadow output remains
diagnostic only; v3 is not truth for v4.

Candidate migration `20260828_0021` adds same-Dataset composite FKs for native Section,
Gate, Pump, and typed Control Event identities plus unique Shadow roles. Its hosted
migration round-trip is still a required gate; the earlier 0020 migration run cannot be
used as 0021 evidence.

Public-production IAM/RBAC, multi-tenancy, remote object-store durability, automatic
artifact retention, complete crash recovery, and deployment disaster recovery remain
NO-GO. The local file backend still requires a durable deployment-provided
`DAYU_STORAGE_ROOT`.

See `HYDRO-MODEL-02-D2-RC1-freeze-integrity.md` and
`HYDRO-MODEL-02-D2-RC1-known-limitations.md` for the RC1 evidence and claim boundaries.
