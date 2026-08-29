# ADR-HYDRO-D2-RC1-0003: Task Attempt and Execution Lease

- Status: accepted for the RC1 candidate implementation
- Date: 2026-08-28

## Context

Celery delivery is at-least-once. The same task ID can therefore be delivered more
than once, an old Worker can resume after recovery, and cancellation can race with
result finalization. A task status alone cannot distinguish these executions. The old
`retry_count` field also conflates legacy compatibility with native-v4 numerical,
infrastructure, and operator-initiated retries.

## Decision

1. The database owns each execution attempt. Claim is one conditional update from
   `queued` to `running`; it increments `execution_attempt_count` and assigns a new
   opaque `active_execution_token`.
2. Claim is schema-specific. Native v4 additionally requires exact equality for all
   five Registry provenance fields: solver, capability, runtime adapter, result
   schema, and Registry hash. A still-queued v4 row with a corrupt route is CAS-marked
   `failed` without creating an attempt; the legacy claim explicitly excludes v4.
3. Heartbeat, failure/cancellation completion, stale recovery, and final success use
   compare-and-set predicates containing the task ID, the active token, and the
   allowed current state. Success additionally requires `cancel_requested=false`.
4. A duplicate delivery cannot claim an already running or terminal task and returns
   an idempotent no-op. This is distinct from an invalid queued route, which fails
   deterministically instead of entering a redelivery loop. An old token cannot update
   the heartbeat, finish a newer attempt, or publish success.
5. On terminal completion or infrastructure requeue, the active token is moved to
   `last_execution_token` and cleared. A later claim always receives a different
   token.
6. Cancellation is also compare-and-set. `queued` becomes terminal `cancelled`;
   `running` becomes `cancel_requested`. If final success wins first, cancellation
   cannot overwrite it. If cancellation wins first, the final success CAS is rejected.
7. Retry domains remain separate:

   | Domain | Meaning | Attempt effect |
   |---|---|---|
   | Numerical | Solver trial reduction/refinement inside one execution | Same task delivery and token; updates `numerical_retry_count` and categorized counters |
   | Infrastructure | Connection, timeout, operating-system, database-operational failure, or stale Worker lease | Database requeues first, then Celery redelivers; at most two clean requeues |
   | Manual | Explicit retry of a reviewed `failed` or `cancelled` task | CAS-reset to `queued`, increment `manual_retry_count`, then create a new execution attempt on claim |

8. Native-v4 manual retry preserves all frozen input and provenance identities while
   clearing attempt-scoped telemetry. The legacy `retry_count` remains a compatibility
   counter and is not reused as the native-v4 numerical counter.
9. Manual retry fails closed unless the task is `failed` or `cancelled`, has no active
   lease, and its v4 Artifact state is clean (`none`, `failed`, or null). A successful
   task is immutable. `prepared`, `publishing`, `published`, `orphaned`, and
   `reconciliation_required` must be reconciled rather than replayed.
10. Stale recovery uses status, token, retry count, and the observed heartbeat in one
    CAS. A stale non-finalization `running` attempt within the infrastructure budget is
    cleanly requeued, its attempt telemetry is reset, and its delivery marker is
    cleared. Exhausted attempts fail. A stale cancellation becomes `cancelled`. A
    stale finalization window sets `artifact_status=reconciliation_required` and
    blocks retry.
11. Celery uses late acknowledgement, rejects delivery on Worker loss, and runs one
    30-second beat task. The task first recovers stale running leases and then
    republishes only old queued rows whose `queue_job_id` delivery marker is null.
    Successful publication records the marker; failed publication leaves it null for
    a bounded future recovery. This prevents both permanent queued gaps and unbounded
    duplicate-message growth.

## Consequences

The task database, rather than Celery's delivery count, is the authority for attempts
and retry eligibility. This prevents stale Workers from overwriting newer work, but it
does not provide broker exactly-once delivery, process fencing outside the database, or
a distributed transaction between the database, Celery, and file storage.

This ADR records implemented RC1 candidate semantics. It is not a test, hosted-CI, or
release PASS statement.
