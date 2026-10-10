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

Review records are append-only and snapshot reviewer principal id, issuer, subject, display name, decision, comment, and graph hash. Freeze re-computes REAL-01 readiness, requires matching QA evidence, loads the latest approved review, and rejects missing or stale evidence. All Dataset content writes continue to use the shared lifecycle guard, so review/approved/published/retired versions cannot be modified in place.

Security audit events use the authenticated principal, never the request `reviewer` value. Derived display-name fields on `dataset_version` are compatibility snapshots and are not authorization data. A new engineering graph requires a cloned Draft and a new QA/review/freeze cycle.
