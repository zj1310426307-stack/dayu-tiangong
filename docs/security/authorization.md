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

The first Security Admin is optional and explicit: after migration, `app-bootstrap` consumes `DAYU_BOOTSTRAP_SECURITY_ADMIN_ISSUER` and `..._SUBJECT`. It creates an initial binding only when no active Security Admin exists; later role changes use the protected role-binding API. Client actor/reviewer/creator fields retained for backward-compatible request parsing are overwritten or ignored in favor of the authenticated principal.
