# HYDRO-MODEL-02-D2 Current Platform Audit

- Audit date: 2026-08-28
- D2 base: `cc6936d9d48d64c46a78ba85bed77c473e20cff3`
- Development branch: `feature/HYDRO-MODEL-02-D2-v4-task-platform`
- Scientific scope: D1 restricted single-Branch, fully wet, forward, strictly
  subcritical Gate/external-Pump case only

## Executive finding

The repository already has durable task rows, immutable input snapshots, Redis/Celery
dispatch, atomic task claim, cooperative cancellation for legacy solvers, heartbeats,
stale-task failure, result tables, an atomic local file service, FastAPI routes, a
generated TypeScript client, and task/result pages. It does not yet have a platform
solver registry, a native `dayu.model-input.v4` builder, v4 Worker capability routing,
`dayu.hydraulic-result.v3`, authoritative v4 result tables, registered evidence
artifacts, or v3/v4 shadow grouping.

The existing v4-lite-7 numerical path is suitable as the frozen D1 runtime. It is not
a platform contract: `HydraulicEngine.run` explicitly rejects callbacks for v4-lite,
and its direct result is `dayu.hydraulic-result.mvp`.

## Required audit answers

1. **SimulationCase storage.** `public.simulation_case` binds a case to one
   `dataset_version` and a primary boundary condition; `simulation_case_boundary`
   adds explicit boundary roles. Dispatch policy is a separate versioned
   `dispatch_plan` with actions/rules and an immutable frozen snapshot.
2. **SimulationTask schemas.** `SimulationTaskCreate` accepts v1, v2, and v3.
   `simulation_task` stores schema, frozen JSON, SHA-256, engine identity, lifecycle,
   progress, heartbeat, cancellation, retry, diagnostics, and result locator.
3. **freeze_task_input.** Creation reads the case in the caller's transaction,
   builds v1/v2/v3, validates the v3-to-v2 projection, adds engine provenance, then
   hashes canonical JSON. Workers consume the stored snapshot rather than rebuilding it.
4. **v3 adaptation.** `build_model_input_v3` reads authoritative `hydraulic.*` rows,
   freezes a verified compatibility mapping, and `adapt_v3_to_v2` produces the legacy
   runtime projection. The v3 snapshot remains authoritative.
5. **v4-lite direct-only boundary.** `HydraulicEngine.run` routes
   `dayu.model-input.v4-lite` directly to `run_v4_lite`, rejects legacy overrides,
   and rejects `cancel_check`/`progress_callback`. No database builder or task route
   currently creates v4-lite snapshots.
6. **Worker claim.** `claim_task` uses a conditional SQL `UPDATE` from `queued` to
   `running`, recording worker/start/heartbeat data. A duplicate claim rolls back.
7. **Heartbeat/cancel/recovery.** The Worker passes database-backed cancel and progress
   callbacks to legacy engines. Queued cancellation is terminal; running cancellation
   becomes `cancel_requested`. Stale running work is marked failed for manual retry,
   without execution-phase-aware recovery.
8. **Progress callback.** The current callback signature is
   `(simulation_time, cfl)`. It maps simulation time to 5–95% and commits every callback;
   there is no accepted-step metadata, phase, retry breakdown, or write throttling.
9. **Current persistence.** v1/v2/v3 results are flattened into
   `simulation_result`, `junction_result`, and `structure_result`; dispatch events are
   written only when a `dispatch_run` owns the task.
10. **Result identity.** v3 uses the frozen compatibility mapping to resolve
    authoritative hydraulic node/section IDs into legacy public result foreign keys.
    It never relies on coincident integer IDs. D2 must avoid this compatibility
    projection and persist authoritative hydraulic IDs directly.
11. **DAYU_STORAGE_ROOT.** `app.files.service` resolves a single configured root,
    rejects absolute/escaping paths, and provides fsync plus atomic replace. The
    default root is `backend/storage`.
12. **Artifact registration.** No hydraulic artifact metadata table exists. Storage
    currently has file primitives only.
13. **Frontend flow.** `HydraulicConfigPage` creates a v3 task and enqueues it;
    `HydraulicTasksPage` polls task rows and supports cancel/retry; the result page
    fetches one section's H/Q/velocity series. No solver selector, v4 readiness,
    execution phase, Gate/Pump detail, events, or artifact manifest exists.
14. **OpenAPI generation.** `frontend/scripts/update-openapi.mjs` reads a running
    FastAPI OpenAPI document, validates a required-path list, then generates the only
    frontend API client. Generated code is not to be hand-edited.
15. **D2 migration need.** One additive migration is required for task solver/hash/
    phase fields, Pump placement and curve identity, v4 Section/Gate/Pump/Event rows,
    artifact metadata, and shadow group membership. No legacy column is removed or renamed.
16. **Compatibility boundary.** v1 remains the legacy single-river route; v2 remains
    the legacy network route; v3 remains authoritative input adapted to v2. Native v4
    must route only through a registered v4-to-v4-lite-7 adapter and must fail closed
    instead of falling back.
17. **Failure/recovery boundary.** Existing retries can redeliver infrastructure
    failures but v4 needs hash revalidation before solve, idempotent replacement behind
    state gates, deterministic prepared/published artifacts, phase-aware stale handling,
    and protection of an already successful result.

## Data gaps

- `public.pump` has Q-H and efficiency JSON plus unit/runtime metadata, but lacks a
  required hydraulic section placement, explicit curve policy/unit/source revision,
  stable curve hash, outlet-stage process, and system-loss contract.
- `public.gate` has chainage and geometry but no explicit hydraulic section-face pair.
- `SimulationCase` has no native v4 numerical/validation policy; those values must be
  frozen through a typed platform contract, not accepted as untracked Worker overrides.
- Existing task diagnostics do not classify CFL, positivity, event, Gate, Pump, or
  minimum-dt retries.

## Environment finding

Node.js 24 is available. The interactive shell has no `python` or `docker` command.
Python validation can use the configured bundled workspace runtime; real PostGIS,
Redis, Celery legacy Worker, and Celery v4 Worker integration remains `BLOCKED` until
an approved runtime is available. Static SQL or mocks will not be reported as a real
migration/Worker PASS.

## Implementation boundary

D2 will add a pure-Python platform solver registry, a strongly typed v4 contract, a
database builder/readiness service, a pure v4-to-v4-lite-7 projection, dedicated v4
Worker capability, result/artifact services, additive FastAPI routes, regenerated
OpenAPI types, and focused frontend panels. It will not change D1 expected values or
expand the D1 scientific envelope.
