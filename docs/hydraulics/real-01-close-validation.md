# REAL-01-CLOSE Validation

## Decision

`FRAMEWORK_PASS_DATA_REQUIRED`

The admission software was hardened and its executable unit/contract checks pass.
The accessible source set is not a complete, reviewed five-river/two-gate package,
so no real import commit, readiness pass, review decision, or Dataset Version freeze
was attempted. Synthetic fixtures below are test evidence only.

## Validation environment

- Date: 2026-10-09 (Asia/Shanghai)
- Baseline: `origin/main@01b01c949b09a0b05434758510080a9e0712edd6`
- Branch: `phase/hydro-data-real-01-close`
- Python: repository virtual environment
- Docker Desktop: Linux engine recovered after initial startup delay.
- PostGIS integration: current Alembic head and disposable clone/hash transaction PASS.
- Cleanup: the exact disposable container had no mounts and was removed after testing.
- Production/real database mutation: none.

## Admission rules verified in code

- Required `PARTIAL` and `MISSING` domains remain `BLOCKER` findings.
- Project identity requires name, version, creator, and purpose/ownership description.
- CRS evidence requires projected EPSG identity, metre units, explicit axis mapping,
  source CRS, engineering CRS, and known vertical datum.
- A legal bifurcation/confluence is accepted; accidental disconnected components are
  rejected within each network.
- Every Cross Section must resolve to a Branch/Chainage, exactly one active profile,
  reviewed spatial geometry, and strictly increasing left-to-right Station points.
- Manning zones must be positive, traceable, continuous, and cover the active profile.
- Exactly two Gates must have Branch/Chainage, sill, opening width/count/limits/speed,
  coefficient, head-loss factors, and a source reference.
- Upstream admission requires a sourced Q(t), not a peak value. Downstream admission
  requires sourced H(t), a rating curve, or a constant H with applicability evidence.
- Scenario and initial-condition records require explicit source evidence.
- A passed QA run is current only when its stored `engineering_content_hash` equals
  the graph hash recomputed by Readiness.

## Clone and hash contract

- Mutable engineering inputs are cloned with version-local foreign keys remapped.
- `SimulationTask`, solver outputs, external-model results, and historical acceptance
  evidence are not cloned.
- Raw import bytes and clone transaction/display identities do not enter the canonical
  hash; source SHA-256 and engineering configuration do.
- Simulation Case boundary links use deterministic version-local case ordinals, so a
  mandatory clone display-name suffix does not change engineering identity.
- A disposable PostGIS test performs the complete clone, remap, external-result
  exclusion, and equal-hash assertion inside a transaction that always rolls back.

## T01-T16 acceptance matrix

| Test | Result | Evidence / limitation |
|---|---|---|
| T01 missing horizontal CRS | PASS | `_coordinate_contract_ready` rejects missing projected CRS. |
| T02 missing vertical datum | PASS | Unknown/blank datum and incomplete coordinate evidence are rejected. |
| T03 disconnected topology | PASS | Branching graph accepted; disconnected graph rejected. |
| T04 Cross Section cannot locate Branch | PASS | Readiness requires Branch membership, chainage range, spatial geometry, active reviewed profile, and points. |
| T05 Gate sill missing | PASS | `_gate_ready` regression rejects a Gate without invert/sill elevation. |
| T06 upstream Q(t) missing | PASS | Peak/constant-only discharge is rejected; monotone sourced Q(t) is accepted. |
| T07 downstream boundary missing | PASS | Base Readiness requires at least one valid downstream level boundary. |
| T08 source not traceable | PASS | Numeric defaults alone are not evidence; committed import hashes/config/CRS are required. |
| T09 frozen version modified | PASS | Existing locked mutability guard and Dataset service regression remain green. |
| T10 clone engineering graph | PASS | Live migrated PostGIS clone remapped the graph and excluded external results. |
| T11 same-content hash stable | PASS | Source and clone canonical hashes were equal in live PostGIS. |
| T12 engineering change alters hash | PASS | Existing canonical snapshot/hash contract retains engineering values and source hashes. |
| T13 import transaction failure | PASS | Existing Preview/Commit route transaction and rollback contract were audited; no bypass added. |
| T14 unauthorized freeze | NOT_RUN | The application has no trusted IAM/current-user role context; a request-body reviewer string cannot prove authorization. No insecure custom auth was invented. |
| T15 synthetic pass is not real acceptance | PASS | Machine/readable reports remain `FRAMEWORK_PASS_DATA_REQUIRED`. |
| T16 attempt to enable D-Flow Pilot | PASS | No registry/routing setting changed; Pilot and Production remain false/fail-closed. |

## Commands and results

```text
ruff check (changed Python files)                         PASS
pytest test_real01_admission.py test_dataset_service.py  21 passed
pytest full repository backend/root suite                512 passed, 77 skipped
alembic upgrade head (disposable PostGIS)                PASS
pytest test_real01_close_postgis.py (live PostGIS)       1 passed
compileall changed backend modules                       PASS
frontend npm run typecheck                               PASS
frontend npm run build                                   PASS (chunk-size warning)
```

Hosted PR checks are recorded by GitHub after push; this local report does not
predict their result.

## Data safety

- Raw source files remain in the controlled project reference directory.
- Git contains only sanitized logical filenames, SHA-256 values, status, and gaps.
- No real import, freeze, solver execution, D-Flow pilot, dispatch, or device control
  occurred.
