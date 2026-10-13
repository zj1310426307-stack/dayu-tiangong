"""Load the fail-closed authentication configuration from deployment settings."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv


class AuthConfigurationError(RuntimeError):
    """Reject an unsafe or internally inconsistent authentication configuration."""


def _enabled(value: str | None) -> bool:
    """Interpret only explicit affirmative values as enabled."""

    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AuthSettings:
    """Hold public authentication settings without secrets or token material."""

    build_mode: str
    auth_mode: str
    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_jwks_url: str | None
    oidc_public_key_file: str | None
    oidc_algorithms: tuple[str, ...]
    dev_auth_enabled: bool
    dev_auth_token: str | None
    dev_issuer: str
    dev_subject: str
    dev_display_name: str
    dev_email: str | None

    @property
    def development_identity_allowed(self) -> bool:
        """Allow a development identity only behind both required controls."""

        return (
            self.build_mode == "development"
            and self.auth_mode == "development"
            and self.dev_auth_enabled
            and bool(self.dev_auth_token)
        )

    @property
    def oidc_configured(self) -> bool:
        """Report whether all OIDC trust anchors needed for verification exist."""

        return bool(
            self.auth_mode == "oidc"
            and self.oidc_issuer
            and self.oidc_audience
            and (self.oidc_jwks_url or self.oidc_public_key_file)
            and self.oidc_algorithms
        )


def load_auth_settings() -> AuthSettings:
    """Read authentication settings and reject production use of development auth."""

    build_mode = getenv("DAYU_BUILD_MODE", getenv("BUILD_MODE", "development")).strip().lower()
    auth_mode = getenv("AUTH_MODE", "disabled").strip().lower()
    if auth_mode not in {"disabled", "development", "oidc"}:
        raise AuthConfigurationError("AUTH_MODE must be disabled, development, or oidc")
    dev_enabled = _enabled(getenv("DAYU_DEV_AUTH_ENABLED"))
    if build_mode != "development" and (auth_mode == "development" or dev_enabled):
        raise AuthConfigurationError(
            "development authentication is forbidden unless DAYU_BUILD_MODE=development"
        )
    algorithms = tuple(
        item.strip()
        for item in getenv("OIDC_ALLOWED_ALGORITHMS", "RS256").split(",")
        if item.strip()
    )
    if not algorithms or any(item.lower() == "none" for item in algorithms):
        raise AuthConfigurationError(
            "OIDC_ALLOWED_ALGORITHMS must be an explicit signed allow-list"
        )
    return AuthSettings(
        build_mode=build_mode,
        auth_mode=auth_mode,
        oidc_issuer=getenv("OIDC_ISSUER") or None,
        oidc_audience=getenv("OIDC_AUDIENCE") or None,
        oidc_jwks_url=getenv("OIDC_JWKS_URL") or None,
        oidc_public_key_file=getenv("OIDC_PUBLIC_KEY_FILE") or None,
        oidc_algorithms=algorithms,
        dev_auth_enabled=dev_enabled,
        dev_auth_token=getenv("DAYU_DEV_AUTH_TOKEN") or None,
        dev_issuer=getenv("DAYU_DEV_AUTH_ISSUER", "urn:dayu:development"),
        dev_subject=getenv("DAYU_DEV_AUTH_SUBJECT", "local-engineer"),
        dev_display_name=getenv("DAYU_DEV_AUTH_DISPLAY_NAME", "Local Engineer"),
        dev_email=getenv("DAYU_DEV_AUTH_EMAIL") or None,
    )


def validate_auth_configuration() -> None:
    """Fail application construction when the selected trust mode is incomplete or unsafe."""

    settings = load_auth_settings()
    if settings.auth_mode == "oidc" and not settings.oidc_configured:
        raise AuthConfigurationError(
            "AUTH_MODE=oidc requires issuer, audience, and a JWKS URL or public key file"
        )
    if settings.auth_mode == "development" and not settings.development_identity_allowed:
        raise AuthConfigurationError(
            "development authentication requires the explicit enable flag and token"
        )
