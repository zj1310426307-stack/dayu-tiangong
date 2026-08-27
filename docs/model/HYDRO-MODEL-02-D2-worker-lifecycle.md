# HYDRO-MODEL-02-D2 Worker Lifecycle

## Routing and claim

Native v4 uses the dedicated Celery queue `hydraulic-v4-d1`. The Worker declares only
the D1 solver and capability. Its atomic conditional claim requires the exact v4 schema,
solver, capability, queued state, and task ID. The legacy claim explicitly excludes v4
while retaining pre-schema tasks whose schema column is NULL.

## Execution phases

```text
validating_snapshot → projecting_runtime → solving → serializing
→ persisting → publishing_artifact → finalizing
```

After claim, the Worker recomputes the source, runtime, mesh, solver-policy,
validation-policy, registry, solver, capability, and adapter identities. It never
rebuilds input from authoritative business rows and never falls back to a legacy solver.

## Progress and heartbeat

Progress is reported only at accepted SSP-RK2 step boundaries. Durable writes are
throttled by progress increment, elapsed wall time, or final simulated time. Each write
may include simulation time, CFL, accepted steps, categorized retries, phase, and last
accepted event. Progress is monotonic; every terminal status is 100.

## Cancellation

Cooperative checks exist at accepted-step boundaries, event refinement, Gate and Pump
root iterations, artifact generation, and persistence/publication boundaries. A queued
task cancels immediately; a running task enters `cancel_requested` and becomes
`cancelled` at a safe checkpoint. Rejected numerical trials are never reported as
accepted progress and incomplete artifacts are not published.

## Retry and stale recovery

Infrastructure connection/timeouts may use bounded Celery autoretry. Numerical input,
hash, capability, quality, and persistence contract failures are terminal. Diagnostics
separate CFL reduction, positivity, event refinement, Gate solver, Pump solver, and
minimum-dt failure counts.

Stale recovery records the last phase. Solving-stage failure requires manual retry;
persisting/publishing/finalizing failure explicitly requires result/artifact
reconciliation. A successful task is immutable and unique constraints protect against
duplicate result delivery.

