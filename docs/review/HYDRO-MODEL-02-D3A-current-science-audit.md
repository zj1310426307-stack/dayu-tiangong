# HYDRO-MODEL-02-D3A Current Science Audit

- Date: 2026-08-29
- Base: D2-RC2 main merge `a40a9f8a5728d6d03c127409491a38321540ac99`
- Scope: read-only audit of the existing finite-volume kernel and D2 platform seal
- Decision: reuse the existing FV kernel; unlock only through explicit versioned capabilities and independent science gates

## Executive finding

The repository already contains the principal numerical building blocks needed by
D3A: cell-local semi-implicit Manning friction, per-cell absolute-stage geometry,
hydrostatic reconstruction, a linear hydraulic-function face path for restricted
non-prismatic flow, SSP-RK2, completed-interface Gate coupling, and the external
Q-H/Q-efficiency Pump. D2 deliberately prevents those experimental policies from
entering the native platform route. D3A therefore needs capability-specific
readiness, evidence, and a small number of composition changes; it must not create a
parallel solver.

## Manning audit

1. `friction.py` implements
   `dQ/dt = -g n^2 Q|Q| / (A R^(4/3))`, equivalent to
   `Sf = n^2 Q|Q| / (A^2 R^(4/3))` and momentum source `-g A Sf`.
2. Positive `n` is already supported. `FiniteVolumeCell` accepts finite `n >= 0`,
   and `apply_manning_friction` evaluates every cell independently.
3. The update is a split, sign-preserving semi-implicit stage operation:
   `Qf = Q* / (1 + dt k |Q*|)`. It is recomputed after each forward-Euler operator
   inside SSP-RK2 and is not claimed to be a globally second-order IMEX method.
4. Stage evidence defines `mu = dt k |Q*|`. The existing C3c network policy uses
   `mu <= 0.1` as a retry/accuracy gate. The native single-Branch D1 route does not
   yet expose the same maximum/retry diagnostics as a capability-owned contract.
5. Runtime ownership is cell scalar `FiniteVolumeCell.manning_n`. The existing
   `roughness.py` can assign longitudinal, face-aligned chainage zones, but it does
   not represent lateral compound-channel conveyance.
6. D2 platform readiness rejects every section whose `default_manning_n != 0.0`.
   `ModelInputV4`, `ValidationPolicy`, and the Registry are also Literal-bound to the
   D1 capability. The D1 completed-interface preflight in `solver.py` independently
   requires zero friction.
7. Junction-adjacent zero-friction cells are specific to the C3 network route and do
   not constrain a single Branch. They must not be copied into D3A.
8. D3A-1 should retain the existing source algorithm, add an independent source-only
   analytic gate, make the friction-number limit capability-owned, and relax only the
   D3A completed-interface scope. Replacing the algorithm is not justified.

## Bed-slope audit

1. The FV kernel consumes absolute `FiniteVolumeCell.bed_elevation`. In the current
   v4-lite adapter this is derived from `geometry.minimum_stage`, while platform
   Profiles are built from stored point elevations.
2. Every mesh cell stores bed elevation and enforces equality with the geometry's
   minimum stage to prevent double application of an offset.
3. `geometry_source.py` provides a common linear hydraulic-function face geometry,
   side-aware `I1`, and a matching non-prismatic pressure source. The standard path
   uses hydrostatic reconstruction and side pressure corrections.
4. `reconstruction.py` reconstructs both sides over the higher adjacent bed and
   adds side-specific hydrostatic pressure corrections; it is not a post-flux slope
   patch.
5. Existing tests cover restricted sloping/prismatic equilibrium and
   non-prismatic lake at rest, but not the D3A S1/S2/S3 suite under an explicit bed
   authority and the final Gate/Pump composition.
6. D1 platform readiness freezes flat bed through identical absolute Profile points,
   the D1 capability manifest, and completed-interface solver preflight.
7. The current runtime policy is named `profile-minimum-elevation-v1`. Treating the
   minimum surveyed Profile point as authoritative bed would be unsafe for D3A
   engineering data and is explicitly not an acceptable production migration.
8. D3A-2 needs an additive, nullable `bed_elevation_m` plus source/confirmation
   identity. Historical rows must remain unconfirmed and readiness must fail closed;
   synthetic fixtures will provide explicit values.

## Non-identical Profile audit

1. `FiniteVolumeMesh` permits a different geometry object in every cell. Tabulated
   geometry already validates monotone offsets and reversible A/H behaviour.
2. `hydraulic_path_interface_flux` projects both cell stages into one deterministic
   face geometry before HLL/Rusanov evaluation, retaining discharge and avoiding an
   artificial mass flux at equal absolute stage.
3. Hydrostatic pressure `I1` is native where available or evaluated through the
   deterministic integral of area with absolute stage.
4. `geometry_pressure_source` supplies the matching left/right face moment
   difference for a non-prismatic control volume.
5. The existing C1 moving-water policy is a restricted fully wet, frictionless,
   forward-subcritical Bernoulli reference. It intentionally excludes Manning,
   structures, and general abrupt geometry.
6. D2 readiness rejects differing Profile signatures, and the D1 capability freezes
   `identical-profile`.
7. The per-cell geometry, linear face path, geometry pressure source, mesh hashing,
   and restricted lake/moving tests are reusable.
8. Missing D3A gates are the combined slope+friction source consistency, independent
   variable-section standard-step reference, smoothness policy, and Gate/Pump tests
   that use each side's actual geometry.

## D3A-0 capability decision

The Registry now owns an ordered `dayu.solver-capability-catalog.v1`. D1 remains the
only supported executable v4 registration. D3A-1, D3A-2, and D3A-3 are explicit
catalog entries with stable IDs, validation-policy IDs, adapter IDs, scope,
exclusions, and warnings, but start as `blocked`. `resolve_capability` never infers a
capability from Manning, bed, or Profile data, and rejects blocked entries unless a
caller explicitly asks only to inspect catalog metadata.

Each later science gate will change exactly one entry to supported and add its
executable route only after local independent evidence and Hosted validation. The D1
manifest and its frozen input semantics remain unchanged.

## Reuse map

| Concern | Existing owner | D3A action |
|---|---|---|
| Manning source | `finite_volume/friction.py` | retain algorithm; add M1/M2 and capability diagnostics |
| Scalar/longitudinal roughness | `mesh.py`, `roughness.py` | expose section-effective values; keep lateral zoning excluded |
| Bed reconstruction | `reconstruction.py` | retain; bind to explicit bed authority and S1/S2/S3 |
| Non-prismatic face/source | `geometry_source.py` | retain restricted formulation; add P1/P2/P3 and composition evidence |
| SSP-RK2/retry | `integrator.py`, `solver.py` | capability-owned friction/source gates and retry summaries |
| Gate/Pump | `structures.py`, `pump.py`, `solver.py` | relax only capability-specific guards and verify absolute-stage use |
| Platform selection | `solver/registry.py`, `api/v4.py`, `v4_service.py` | explicit selector; never auto-upgrade |
| Provenance | Registry/build identity/projection hashes | add roughness, bed, and geometry policy identities |

## Continuing NO-GO

This audit does not unlock positive Manning, slope, or non-identical Profiles. It
does not establish wetting/drying, reverse or supercritical flow, Junctions, general
networks, lateral compound roughness, abrupt section topology, calibration, or
production decision support.
