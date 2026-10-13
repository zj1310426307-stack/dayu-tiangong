"""Verify bearer tokens and resolve trusted, server-owned authorization."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from pathlib import Path
from typing import Annotated, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.security.config import AuthConfigurationError, load_auth_settings
from app.security.permissions import permissions_for_roles
from app.security.service import observe_principal


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Carry only verified identity fields and local authorization grants."""

    id: int
    issuer: str
    subject: str
    display_name: str
    email: str | None
    authentication_method: str
    roles: tuple[str, ...]
    permissions: frozenset[str]


bearer = HTTPBearer(auto_error=False, scheme_name="OIDC bearer token")


def _unauthorized(detail: str = "authenticated bearer token required") -> HTTPException:
    """Return a generic challenge without leaking verifier internals."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _claims_from_token(token: str) -> tuple[dict[str, object], str]:
    """Verify an OIDC token or the explicitly enabled development credential."""

    try:
        settings = load_auth_settings()
    except AuthConfigurationError as exc:
        raise _unauthorized("authentication is not safely configured") from exc
    if settings.development_identity_allowed:
        if not compare_digest(token, settings.dev_auth_token or ""):
            raise _unauthorized("invalid bearer token")
        return (
            {
                "iss": settings.dev_issuer,
                "sub": settings.dev_subject,
                "name": settings.dev_display_name,
                "email": settings.dev_email,
            },
            "development",
        )
    if not settings.oidc_configured:
        raise _unauthorized("authentication provider is not configured")
    try:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg", ""))
        if algorithm not in settings.oidc_algorithms:
            raise _unauthorized("token signing algorithm is not allowed")
        if settings.oidc_public_key_file:
            key = Path(settings.oidc_public_key_file).read_text(encoding="utf-8")
        else:
            key = PyJWKClient(settings.oidc_jwks_url or "").get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=list(settings.oidc_algorithms),
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "sub", "iss"]},
        )
    except HTTPException:
        raise
    except (OSError, jwt.PyJWTError) as exc:
        raise _unauthorized("invalid bearer token") from exc
    token_use = claims.get("token_use") or claims.get("typ")
    if token_use is not None and str(token_use).lower() not in {"access", "at+jwt"}:
        raise _unauthorized("an access token is required")
    return claims, "oidc"


def get_authenticated_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_database_session)],
) -> AuthenticatedPrincipal:
    """Resolve issuer/subject and local roles; all protected APIs fail closed."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    claims, method = _claims_from_token(credentials.credentials)
    issuer = str(claims.get("iss") or "")
    subject = str(claims.get("sub") or "")
    if not issuer or not subject:
        raise _unauthorized("token has no stable issuer/subject identity")
    display_name = str(claims.get("name") or claims.get("preferred_username") or subject)
    email = str(claims["email"]) if claims.get("email") else None
    entity, roles = observe_principal(
        session,
        issuer=issuer,
        subject=subject,
        display_name=display_name,
        email=email,
        authentication_method=method,
    )
    if not entity.active:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="principal is inactive")
    session.commit()
    return AuthenticatedPrincipal(
        id=entity.id,
        issuer=entity.issuer,
        subject=entity.subject,
        display_name=entity.display_name,
        email=entity.email,
        authentication_method=entity.authentication_method,
        roles=roles,
        permissions=frozenset(permissions_for_roles(roles)),
    )


def require_permission(permission: str) -> Callable[..., AuthenticatedPrincipal]:
    """Build a centralized FastAPI dependency for one explicit permission."""

    def dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    ) -> AuthenticatedPrincipal:
        if permission not in principal.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"permission required: {permission}",
            )
        return principal

    return dependency
