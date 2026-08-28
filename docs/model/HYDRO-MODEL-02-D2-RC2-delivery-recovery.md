# HYDRO-MODEL-02-D2-RC2 Delivery Recovery

## Decision

`queue_job_id` is historical evidence that a broker accepted a publication; it is
not proof that the message still exists. RC2 therefore recovers stale queued tasks
from durable delivery leases even when `queue_job_id` is non-null.

## Durable state

Migration `20260828_0022` adds:

- `delivery_attempt_count`, initially zero and never negative;
- `last_delivery_time`, the most recent reserved publication time;
- an index on `(status, last_delivery_time)` for bounded scans.

Every initial, manual-retry, infrastructure-retry, or recovery publication first
reserves a delivery attempt and time in the database. A successful broker call then
records its job ID. A failed call leaves the task queued, clears the marker, and
stores bounded infrastructure evidence for periodic recovery.

## Recovery policy

The periodic scan considers only tasks with:

```text
status = queued
active_execution_token IS NULL
cancel_requested = false
last delivery older than the configured stale interval
```

The default minimum interval is 90 seconds and the hard limit is three delivery
attempts. Eligibility does not depend on `queue_job_id` being null. Reservation uses
a compare-and-swap over status, active token, attempt count, and observed delivery
time, so concurrent scanners cannot amplify one attempt.

At the limit, the queued task becomes `failed` with
`D2_DELIVERY_RETRY_LIMIT`. Running, cancellation-requested, cancelled, successful,
and failed tasks are never republished by queued recovery.

## Duplicate safety

Low-frequency duplicates are safe because RC1 already owns the
`queued -> running` atomic claim and one active execution token. The winning message
creates the only attempt; later deliveries are idempotent no-ops. RC2 does not claim
exactly-once broker semantics or a distributed database/broker transaction.
