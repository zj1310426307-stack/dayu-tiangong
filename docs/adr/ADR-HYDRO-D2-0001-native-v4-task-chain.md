# ADR-HYDRO-D2-0001: Native v4 Platform Task Chain

- Status: accepted for implementation
- Date: 2026-08-28

## Context

The D1 solver is a validated direct `v4-lite-7` numerical contract. The platform task
chain supports only v1/v2/v3, with v3 intentionally adapted to v2. Treating v4 as v3,
or exposing v4-lite directly through HTTP, would erase solver capability, authoritative
identity, and recovery boundaries.

## Decision

1. Add a pure-Python registry mapping input schema, solver ID, capability ID, and
   runtime adapter ID. Unknown or mismatched combinations fail closed.
2. Define `dayu.model-input.v4` as the authoritative platform DTO. A pure adapter
   projects it to the frozen `dayu.model-input.v4-lite` / `v4-lite-7` runtime.
3. Preserve separate hashes for authoritative input, runtime projection, mesh, solver
   policy, validation policy, registry, profiles, structures, and controls.
4. Route v4 only to the D1 finite-volume solver. It must never call the v3-to-v2 adapter
   and must never fall back to a legacy solver.
5. Keep HTTP handlers thin. Readiness, freeze, state transitions, quality gates, result
   persistence, artifact publication, and shadow orchestration belong to service/worker
   modules.
6. Use the dedicated Celery queue `hydraulic-v4-d1`; legacy workers must not claim v4.
7. Persist v4 output under `dayu.hydraulic-result.v3` in additive authoritative tables.
   Do not coerce it into legacy `simulation_result`.
8. Store full SSP-RK stage evidence as deterministic canonical JSONL.GZ under
   `DAYU_STORAGE_ROOT`; the database stores only its controlled metadata and status.
9. Regenerate the frontend client from FastAPI OpenAPI after every backend contract
   change. Frontend code may only call the generated client.

## Consequences

- Existing v1/v2/v3 HTTP responses and persistence remain unchanged.
- v4 tasks require readiness and immutable snapshots before enqueue.
- A separate result path avoids public compatibility IDs and prevents accidental v3
  semantics from leaking into v4.
- The migration and Worker integration gates require a real PostGIS/Redis environment;
  D2 cannot be declared PASS from static checks alone.
- D1 physics and its frozen benchmark remain the release guard for every D2 change.
