"""HYDRO-AUTH-01 T01-T20 fail-closed security matrix."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.dataset.lifecycle import assert_dataset_version_mutable
from app.dataset.real01 import _qa_matches_graph
from app.dataset.service import _assert_freeze_review_matches
from app.security.auth import (
    AuthenticatedPrincipal,
    _claims_from_token,
    get_authenticated_principal,
    require_permission,
)
from app.security.config import AuthConfigurationError, load_auth_settings
from app.security.permissions import ROLE_PERMISSIONS, permissions_for_roles
from app.security.service import record_freeze_audit


def _principal(*roles: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        id=7,
        issuer="https://issuer.example",
        subject="user-7",
        display_name="Trusted User",
        email="user@example.com",
        authentication_method="oidc",
        roles=roles,
        permissions=permissions_for_roles(roles),
    )


def _authorize(permission: str, principal: AuthenticatedPrincipal) -> AuthenticatedPrincipal:
    """Exercise the centralized dependency directly without a database connection."""

    return require_permission(permission)(principal)


@pytest.fixture
def oidc_keys(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setenv("DAYU_BUILD_MODE", "release")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("OIDC_AUDIENCE", "dayu-api")
    monkeypatch.setenv("OIDC_PUBLIC_KEY_FILE", "controlled-test-key.pem")
    monkeypatch.setenv("OIDC_ALLOWED_ALGORITHMS", "RS256")
    monkeypatch.delenv("DAYU_DEV_AUTH_ENABLED", raising=False)
    monkeypatch.setattr(
        "app.security.auth.Path.read_text", lambda *_args, **_kwargs: public_pem.decode()
    )
    return private_pem


def _token(private_key: bytes, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": "https://issuer.example",
        "sub": "user-7",
        "aud": "dayu-api",
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "name": "Trusted User",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_t01_freeze_without_authorization_is_401() -> None:
    with pytest.raises(HTTPException) as caught:
        get_authenticated_principal(None, SimpleNamespace())
    assert caught.value.status_code == 401


def test_t02_spoofed_reviewer_without_principal_is_401() -> None:
    spoofed_body = {"reviewer": "admin"}
    with pytest.raises(HTTPException) as caught:
        get_authenticated_principal(None, SimpleNamespace(body=spoofed_body))
    assert caught.value.status_code == 401


def test_t03_viewer_cannot_freeze() -> None:
    with pytest.raises(HTTPException) as caught:
        _authorize("dataset.freeze", _principal("viewer"))
    assert caught.value.status_code == 403


def test_t04_engineer_cannot_approve() -> None:
    with pytest.raises(HTTPException) as caught:
        _authorize("dataset.approve", _principal("engineer"))
    assert caught.value.status_code == 403


def test_t05_reviewer_can_approve() -> None:
    principal = _principal("engineering_reviewer")
    assert _authorize("dataset.approve", principal) == principal


def test_t06_reviewer_cannot_freeze() -> None:
    with pytest.raises(HTTPException) as caught:
        _authorize("dataset.freeze", _principal("engineering_reviewer"))
    assert caught.value.status_code == 403


def test_t07_freezer_with_matching_approval_passes_guard() -> None:
    review = SimpleNamespace(engineering_content_hash="a" * 64)
    _assert_freeze_review_matches("a" * 64, review)
    principal = _principal("dataset_freezer")
    assert _authorize("dataset.freeze", principal) == principal


def test_t08_freezer_without_approval_fails_closed() -> None:
    with pytest.raises(ValueError, match="缺少工程审核"):
        _assert_freeze_review_matches("a" * 64, None)


def test_t09_changed_hash_denies_freeze() -> None:
    with pytest.raises(ValueError, match="审核哈希"):
        _assert_freeze_review_matches("b" * 64, SimpleNamespace(engineering_content_hash="a" * 64))


def test_t10_stale_qa_hash_is_not_current() -> None:
    run = SimpleNamespace(status="passed", summary={"engineering_content_hash": "a" * 64})
    assert _qa_matches_graph(run, "b" * 64) is False


def test_t11_invalid_jwt_signature_is_401_equivalent(oidc_keys) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(Exception, match="401"):
        _claims_from_token(_token(wrong_key))


def test_t12_expired_jwt_is_401_equivalent(oidc_keys) -> None:
    with pytest.raises(Exception, match="401"):
        _claims_from_token(_token(oidc_keys, exp=datetime.now(UTC) - timedelta(seconds=1)))


def test_t13_wrong_issuer_is_401_equivalent(oidc_keys) -> None:
    with pytest.raises(Exception, match="401"):
        _claims_from_token(_token(oidc_keys, iss="https://attacker.example"))


def test_t14_wrong_audience_is_401_equivalent(oidc_keys) -> None:
    with pytest.raises(Exception, match="401"):
        _claims_from_token(_token(oidc_keys, aud="other-api"))


def test_t15_no_role_binding_denies_privileged_mutation() -> None:
    with pytest.raises(HTTPException) as caught:
        _authorize("dataset.edit", _principal())
    assert caught.value.status_code == 403


def test_t16_token_role_claim_is_not_a_local_grant(oidc_keys) -> None:
    claims, _ = _claims_from_token(_token(oidc_keys, role="dataset_freezer"))
    assert claims["role"] == "dataset_freezer"
    assert "dataset.freeze" not in permissions_for_roles(())


def test_t17_frozen_dataset_cannot_be_modified() -> None:
    session = SimpleNamespace(
        scalar=lambda _statement: SimpleNamespace(id=1, status="approved", is_read_only=False)
    )
    with pytest.raises(ValueError, match="IMMUTABLE"):
        assert_dataset_version_mutable(session, 1)


def test_t18_security_admin_cannot_approve_engineering_data() -> None:
    principal = _principal("security_admin")
    assert "dataset.approve" not in principal.permissions
    with pytest.raises(HTTPException) as caught:
        _authorize("dataset.approve", principal)
    assert caught.value.status_code == 403


def test_t19_production_mode_rejects_dev_auth(monkeypatch) -> None:
    monkeypatch.setenv("DAYU_BUILD_MODE", "release")
    monkeypatch.setenv("AUTH_MODE", "development")
    monkeypatch.setenv("DAYU_DEV_AUTH_ENABLED", "1")
    monkeypatch.setenv("DAYU_DEV_AUTH_TOKEN", "not-a-real-secret")
    with pytest.raises(AuthConfigurationError):
        load_auth_settings()


def test_t20_audit_uses_verified_issuer_and_subject() -> None:
    added: list[object] = []
    session = SimpleNamespace(add=added.append)
    version = SimpleNamespace(id=42)
    principal = _principal("dataset_freezer")
    record_freeze_audit(session, version, principal, "a" * 64, "review")
    event = added[0]
    assert event.actor_issuer == principal.issuer
    assert event.actor_subject == principal.subject
    assert event.actor_display_name == "Trusted User"


def test_role_permission_matrix_is_least_privilege() -> None:
    assert "dataset.edit" in ROLE_PERMISSIONS["engineer"]
    assert "dataset.approve" not in ROLE_PERMISSIONS["engineer"]
    assert "dataset.freeze" in ROLE_PERMISSIONS["dataset_freezer"]
    assert "security.roles.manage" not in ROLE_PERMISSIONS["dataset_freezer"]
