# HYDRO-MODEL-02-D2 Worker Lifecycle

> RC2 addendum: a queued task now has a separate delivery lease
> (`delivery_attempt_count`, `last_delivery_time`). A non-null `queue_job_id` is only
> a historical publish marker. Stale queued work with no active execution token is
> eligible for compare-and-swap redelivery at intervals of at least 90 seconds,
> including when that marker is non-null. The third unclaimed delivery is the last;
> a later stale scan fails the task with `D2_DELIVERY_RETRY_LIMIT`. After claim,
> legacy and native-v4 Workers match the frozen runtime build before solving.

## Routing, claim, and lease

Native v4 uses the dedicated Celery queue `hydraulic-v4-d1`. The Worker declares only
the D1 solver and capability. Its atomic claim requires `queued`, the exact v4 schema,
and all five Registry provenance fields: solver, capability, runtime adapter, result
schema, and Registry hash. The legacy claim explicitly excludes v4 while retaining
pre-schema tasks whose schema column is null.

Every winning claim increments `execution_attempt_count` and creates a unique
`active_execution_token`. Duplicate delivery loses the queued-state CAS and does not
execute the model. A still-queued row with invalid v4 route provenance is atomically
failed without an attempt instead of being mistaken for a duplicate. Heartbeat,
terminal transition, stale recovery, and final success
are token-fenced; an old delivery cannot mutate a later attempt.

## Execution phases

```text
validating_snapshot -> projecting_runtime -> solving -> serializing
-> persisting -> publishing_artifact -> finalizing
```

After claim, the Worker recomputes the source, runtime, mesh, solver-policy,
validation-policy, Registry, solver, capability, and adapter identities. It never
rebuilds input from mutable business rows and never falls back to a legacy solver.

## Progress and heartbeat

Progress is reported at accepted SSP-RK2 step boundaries. Durable writes are throttled
by progress increment, elapsed wall time, or final simulated time. Each write may
include simulation time, CFL, accepted steps, categorized numerical retries, phase,
and the last accepted event. Progress is monotonic. Phase-only heartbeats do not clear
the last accepted hydraulic telemetry, and terminal states set progress to 100.

## Cancellation and finalization

Cooperative checks exist during solving, event/structure iteration, Artifact building,
and persistence/publication boundaries. A queued task cancels immediately. A running
task enters `cancel_requested` and becomes `cancelled` at a safe checkpoint using its
token.

Final success requires a CAS over task ID, `running`, the active token, and
`cancel_requested=false`. Success cannot overwrite a cancellation that won first, and
a late cancellation cannot overwrite success. Rejected numerical trials are never
reported as accepted progress.

## Retry domains

- Numerical retry stays inside one solver execution and token. It uses
  `numerical_retry_count` plus CFL, positivity, event-refinement, Gate, Pump, and
  minimum-dt diagnostics.
- Infrastructure retry applies to connection, timeout, OS/database-operational
  failures and stale non-finalization Worker leases. The database first performs a
  clean token CAS back to `queued`; only then does the task publish a Celery retry and
  record its `queue_job_id`. At most two such requeues are allowed. There is no Celery
  `autoretry_for` wrapper.
- Manual retry is an explicit API transition from reviewed `failed`/`cancelled` to
  `queued`. It increments `manual_retry_count`, preserves frozen evidence, clears
  attempt telemetry, and is blocked by an active lease or a non-clean v4 Artifact.

The legacy `retry_count` remains compatibility state and is not the native-v4
numerical retry counter. Numerical input, frozen-hash, capability, and quality-contract
failures are terminal for the attempt.

## Stale recovery and Artifact gate

Celery late-acknowledges tasks, rejects delivery on Worker loss, and a 30-second beat
task first recovers stale running leases and then republishes old queued rows only when
their `queue_job_id` is null. Recovery CAS-checks status, token, retry count, and the
exact stale heartbeat. A solving-stage stale attempt within budget is cleanly requeued,
increments `infrastructure_retry_count`, and resets attempt telemetry; an exhausted
attempt fails. A stale cancellation becomes `cancelled`. Staleness during `persisting`,
`publishing_artifact`, or `finalizing` sets `reconciliation_required` on the task and
prepared/publishing Artifact rows.

The queued recovery CAS also requires a null delivery marker. Successful broker
publication writes the job ID; publication failure retains null and refreshes the
queue timestamp for a later bounded retry. Legitimately queued work is therefore not
republished every scan interval.

Manual retry for v4 then remains blocked until the bounded reconciler returns the
Artifact to null, `none`, or `failed`. A successful task is immutable. Full state and
recovery diagrams are in `HYDRO-MODEL-02-D2-RC1-task-state-machine.md` and
`HYDRO-MODEL-02-D2-RC1-result-artifact-reconciliation.md`.

This document describes current RC1 candidate behavior; it does not declare test,
hosted-CI, or release PASS.
