# Authorization

Authorization is a server-owned Role Binding from an `identity_principal` row to one of five roles.

| Role | Effective permissions |
|---|---|
| `viewer` | `dataset.read`, `audit.read` |
| `engineer` | read, edit, clone, submit review, audit read |
| `engineering_reviewer` | read, review/approve, audit read |
| `dataset_freezer` | read, freeze, publish, retire, audit read |
| `security_admin` | read, audit read, role management |

Roles do not imply each other. In particular, Security Admin cannot approve engineering data, Reviewer cannot freeze, and Freezer cannot edit. Token `roles`, `groups`, and similarly named claims are ignored.

The first Security Admin is optional and explicit: after migration, `app-bootstrap` consumes `DAYU_BOOTSTRAP_SECURITY_ADMIN_ISSUER` and `..._SUBJECT` only if the persistent `security_bootstrap_state` singleton has never been consumed. Existing historical admin bindings or grants consume it during upgrade, including revoked or disabled identities. An advisory transaction lock serializes first initialization. Normal restarts never restore revoked bindings or disabled principals. See [bootstrap/recovery](security-admin-bootstrap-recovery.md) for controlled owner recovery.

Client actor/reviewer/creator fields retained for backward-compatible parsing are overwritten or ignored. Dataset reviewer commands additionally carry the server-published round and latest decision ID; these are concurrency preconditions, not identity or permission grants. The runtime database login is non-owner and cannot modify historical review/audit rows or insert/delete bootstrap markers. Privileged inherited roles cause hardening to fail rather than accepting an unsafe role graph.
