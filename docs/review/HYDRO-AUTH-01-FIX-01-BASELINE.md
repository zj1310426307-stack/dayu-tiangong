# HYDRO-AUTH-01-FIX-01 Baseline

Baseline: `0545e36646d30d84705abcb66010bbe4c5b59916`. PR #27 OPEN, unmerged, CLEAN; 30/30 checks successful. Working tree clean before this task.

## Confirmed findings

The baseline probe was executed against a new isolated `dayu-auth-fix01` PostgreSQL/PostGIS database migrated to 0038, before changing implementation:

```text
BASELINE_OLD_APPROVAL_REUSED=True
BASELINE_EVIDENCE_UPDATE_ALLOWED=True
BASELINE_REVOKED_ADMIN_REACTIVATED=True
```

1. `latest_approved_review` filters approved records and ignores later return/reject and submission context. An unchanged Hash A can regain historical authorization.
2. `_configure_privileges` grants UPDATE/DELETE to both evidence tables through blanket public-schema grants.
3. Bootstrap checks active administrators only and upserts active=true for both principal and binding. Revocation is lost on normal bootstrap.
4. Legacy calculation approval creates review evidence directly; its scope and submission round are absent. It must not silently certify REAL-01.

## Minimum fix

Add forward revision 0039: explicit Dataset current round/scope; immutable decisions carry round/scope; historical decisions remain NULL/unattributed and fail closed. Freeze uses latest decision in current REAL-01 round, with QA/graph Hash unchanged. All lifecycle writes reuse the Dataset row lock. Decision requests carry round and expected latest decision ID to reject concurrent stale actions.

Bootstrap uses a protected, persistent singleton and a transactional lock. Existing historical admin bindings consume bootstrap even when inactive. Runtime grants are SELECT/INSERT on review/audit, SELECT only on bootstrap state; inherited owner access is rejected. Database triggers additionally block non-owner writes if future blanket grants regress.

## Compatibility / tests

Standard 1D calculation review retains its mapper, warning policy and trusted Reviewer but uses separate `standard_1d` evidence; REAL-01 cannot freeze using this evidence. Existing approved/published datasets remain unchanged. History is never promoted to a valid current round. New API round/precondition fields require client regeneration.

Tests: AUTH-FIX-T01–T20, same-hash resubmission, Return/Freeze and Reviewer concurrency using real PostgreSQL locks, actual runtime-login DML denials, repeated bootstrap/revocation/disabled identity, historical migration data retention, clone, existing integration and solver/Worker CI.
