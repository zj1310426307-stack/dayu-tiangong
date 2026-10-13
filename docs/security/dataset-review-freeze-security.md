# Dataset Review and Freeze Security

The protected lifecycle is:

```text
editable Draft
  -> current-hash QA PASS
  -> Engineer submits Review
  -> Engineering Reviewer approves exact Hash A
  -> Dataset Freezer freezes only if current graph == QA hash == review Hash A
  -> immutable Approved Dataset Version
```

Each Engineer submission increments `current_review_round` and sets `current_review_scope=real01`. Decisions snapshot this explicit round, scope, reviewer identity and graph hash. Freeze re-computes REAL-01 readiness, requires matching QA evidence, and reads **all** decisions in the current round ordered by monotonic ID; only the latest `approve/approved` decision authorizes freezing. Historical NULL rounds, prior-round approvals and Standard 1D evidence never authorize REAL-01 freezing.

Return appends a decision and moves the version to Draft. A new submission increments the round even if the engineering Hash is unchanged; a new approval is required. Rejected versions remain terminal and must be cloned. No history row is modified or deleted. Concurrent lifecycle actions use `lock_dataset_version()` throughout their transaction. A Review request must include `review_round` and `expected_decision_id` (null for the first decision). A later Return/Reject must name the latest approval ID. A stale precondition fails with `REVIEW_CONTEXT_STALE`; competing Reviewer decisions or Return/Freeze cannot both commit.

The legacy `approve-for-calculation` entry point retains Standard 1D validation, mapper and warning rules, but creates a new `standard_1d` review round from a writable Draft and records its scope in both decision and audit. It does not certify REAL-01 or freeze a Dataset. A REAL-01 submission/decision must use the dedicated workflow. Existing Approved/Published versions retain their status. Versions migrated from 0038 with ambiguous historic approvals must be explicitly returned using a current submission context or handled by an authorized deployment operator; unknown history is never silently grandfathered.

`dayu_backend` and its publisher membership have SELECT/INSERT only on `dataset_review` and `security_audit_event`, with no UPDATE/DELETE/TRUNCATE. Application bootstrap reapplies this after blanket grants. Non-owner triggers additionally reject historical modifications if a later grant regresses. Table owners/superusers remain privileged. All Dataset content writes continue to use the shared lifecycle guard, so review/approved/published/retired versions cannot be modified in place.

Security audit events use the authenticated principal, never the request `reviewer` value. Derived display-name fields on `dataset_version` are compatibility snapshots and are not authorization data. A new engineering graph requires a cloned Draft and a new QA/review/freeze cycle.
