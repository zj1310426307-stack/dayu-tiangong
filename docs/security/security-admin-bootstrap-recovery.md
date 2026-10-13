# Security Admin bootstrap and controlled recovery

## Initial deployment

Run Alembic 0039 as the deployment owner, then existing QGIS/application bootstrap. Configure the trusted initial administrator issuer and subject explicitly. Bootstrap takes a transaction advisory lock, creates the initial binding plus ROLE_GRANTED audit, and inserts `initial_security_admin` into `security_bootstrap_state` atomically. The marker is read-only for `dayu_backend`. Clearing environment variables after initialization is recommended; leaving them set does not restore a revoked account.

0039 consumes the marker if any historical Security Admin role binding or grant exists, regardless of active status. Repeat startup is idempotent. An existing disabled target principal consumes initial bootstrap without activation. No role or principal is reactivated by normal bootstrap. If runtime ownership, privileged inherited roles or grants cannot be made safe, bootstrap fails and deployment requires operator correction.

## Emergency recovery

Recovery requires separately approved deployment-owner credentials and a change ticket. It is not a public API and is not triggered by a zero-active-admin count.

1. Verify the requester's authority and the intended OIDC issuer/subject out of band; record why all normal administrators are unavailable.
2. Back up identity/role/audit state. In an owner transaction, locate/create the verified principal. Explicitly document any decision to reactivate a disabled principal.
3. Grant/reactivate only its `security_admin` binding. Append `ROLE_GRANTED` security audit using that principal's stable id, issuer and subject and details containing `source=controlled_owner_recovery`, the ticket and operator reference. Never edit past audit rows.
4. Preserve the bootstrap singleton. Do not delete it or use ordinary bootstrap environment variables as recovery.
5. Verify login via the real IdP, `/auth/me`, and least-privilege role management. Confirm this role still cannot approve or freeze engineering data.

This task provides the runbook; no recovery was executed against any platform database. Owners/superusers can modify database history and are outside the ordinary-runtime-account threat boundary. Restrict and audit those credentials separately.

## Migration compatibility

0039 is additive. Principal, role, review, audit and Dataset rows remain intact. Existing reviews receive NULL round/scope; current Dataset round defaults to zero. Existing certified Dataset status is unchanged. For a legacy version still in review with no round, an explicitly authorized operator may return it to Draft with a new audit record; the Engineer must then resubmit, obtain current QA and a new review. Do not assign old approvals to the new round.

Downgrade removes additive round metadata and triggers but retains original evidence rows. Revoked evidence ACLs are deliberately not widened by downgrade. Upgrade after downgrade treats all unknown historical decisions as inert and consumes admin bootstrap from historical bindings/grants.
