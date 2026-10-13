# HYDRO-AUTH-01 Security Baseline

## Pre-change finding

The platform previously had no trusted application principal, JWT verifier, local role binding, or authorization dependency. Dataset approval/freeze and GIS governance accepted actor/reviewer strings supplied by the client. Database service roles limited SQL privileges but did not identify the human making an engineering decision.

## Frozen contract

- Identity key: immutable OIDC `issuer + subject`.
- Authentication: signed access-token verification using PyJWT; issuer, audience, expiry, signing algorithm and JWKS/public-key trust anchor are checked.
- Authorization: roles are stored locally and never taken from token role/group claims.
- Production: protected APIs fail closed when OIDC is disabled or incomplete.
- Development identity: available only when `DAYU_BUILD_MODE=development`, `AUTH_MODE=development`, `DAYU_DEV_AUTH_ENABLED=1`, and an explicit token are all present.
- Review and freeze: review, current QA, and current engineering graph must carry the same hash.
- Audit: issuer, subject, principal id, display-name snapshot, action, state transition, and graph hash are stored; bearer material is never stored.

Public health, GIS tiles, and public read paths remain available. Privileged mutation paths require an authenticated permission.
