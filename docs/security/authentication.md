# Authentication

Set `AUTH_MODE=oidc` for a real deployment and configure `OIDC_ISSUER`, `OIDC_AUDIENCE`, plus either `OIDC_JWKS_URL` or `OIDC_PUBLIC_KEY_FILE`. `OIDC_ALLOWED_ALGORITHMS` is an explicit signed allow-list and defaults to `RS256`; `none` is rejected. The verifier requires a stable `iss` and `sub`, an unexpired token, the configured audience, and a valid signature. If `token_use`/`typ` is supplied, it must describe an access token.

`GET /api/v1/auth/me` returns only the verified identity snapshot, local roles, and resolved permissions. It never returns an access token, Authorization header, key, or IdP secret.

Development authentication is intentionally two-keyed. It works only in a development build and requires both the development mode and explicit enable flag. A release/production build with development auth configured fails during application construction. `AUTH_MODE=disabled` does not create an anonymous user: protected endpoints return 401.

The frontend generated client keeps an access token in memory through `setAuthAccessToken`; acquisition and refresh remain the responsibility of the deployment OIDC client. No real token or key belongs in the repository.
