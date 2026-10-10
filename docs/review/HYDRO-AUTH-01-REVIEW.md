# HYDRO-AUTH-01 Final Review

## Scope conclusion

Trusted principal, OIDC/JWT verification, local RBAC, protected engineering mutations, hash-bound Dataset review/freeze, immutable audit evidence, one-time administrator bootstrap, OpenAPI Bearer contract, and minimal frontend identity/permission UX are implemented. No REAL-02, D-Flow pilot, optimization, PLC, or SCADA capability was enabled.

## Security conclusion

- Client reviewer/actor/role data is not an authorization source.
- No Authorization returns 401; insufficient role returns 403.
- Invalid signature, expiry, issuer, and audience fail closed.
- Production cannot activate development identity.
- Review and freeze actor evidence stores principal issuer and subject.
- Freeze requires matching current graph, current QA, and approved review hashes.

## Deployment decision

Status is `FRAMEWORK_PASS_IDP_CONFIGURATION_REQUIRED` until a real OIDC Provider, audience, trust anchor, and initial Security Admin identity are supplied by the deployment owner. This is an allowed partial state: protected APIs remain closed, and no anonymous administrator exists.

The additive migration was exercised against a disposable PostgreSQL 17/PostGIS 3.5 database from an empty schema through `20261010_0038`, downgraded to `20260928_0037`, and upgraded to head again. The issuer/subject identity and server-owned role binding integration test passed, and the existing Engineering-03 structure API round trip was upgraded to use a signed OIDC token plus a database-owned Engineer role. The isolated containers and volumes were then removed.

## Compatibility

Public health/tiles/selected read APIs are unchanged. Existing actor/reviewer request properties remain parse-compatible where needed but are ignored or overwritten. Migration `20261010_0038` is additive. Frontend OIDC acquisition is intentionally external to this task; the generated client exposes an in-memory token setter and `/auth/me` integration.
