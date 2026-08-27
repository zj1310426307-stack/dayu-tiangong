# HYDRO-MODEL-02-D2 Known Limitations

D2 is platform integration of the already frozen D1 scientific subset. It is validation
software, not a calibrated production water-decision system.

Supported scope is limited to one confirmed Branch, fully wet forward strictly
subcritical flow, flat bed, identical Profile geometry, Manning n=0, one
completed-interface Gate, one external Q-H/Q-efficiency Pump, same-type parallel units,
and the D1 control/numerical policies.

Explicit NO-GO items:

- Junctions, multiple Branches, loops, wetting/drying, reverse flow, supercritical flow,
  hydraulic jumps, or general river networks;
- internal-transfer Pump hydraulics, multiple Gates/Pumps, heterogeneous or variable-
  speed units, new curve interpolation, new Gate regimes, or continuous Gate control;
- positive Manning, nonzero bed slope, non-identical Profiles, engineering calibration,
  HEC-RAS/MIKE comparison, MPC/GA optimization, PLC/SCADA, or real command dispatch;
- public-production IAM/RBAC, multi-tenancy, remote object-store durability, automatic
  artifact retention, or a complete crash-reconciliation daemon.

Shadow output is diagnostic only: v3 is not truth for v4. The current file artifact
backend assumes a durable `DAYU_STORAGE_ROOT` supplied by deployment. Published-file
integrity is checked on download, but operational backup and disaster recovery remain a
deployment responsibility.

D3A may consider positive Manning, nonzero bed slope, and non-identical Profiles while
retaining the one-Branch/full-wet/subcritical/one-Gate/one-Pump boundary. D2 does not
pre-implement that expansion.

