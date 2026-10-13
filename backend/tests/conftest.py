"""Shared security fixtures for real API integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from app.database.session import SessionLocal
from app.security.models import IdentityPrincipal, IdentityRoleBinding


@pytest.fixture
def engineer_auth_headers(monkeypatch) -> dict[str, str]:
    """Create a signed OIDC identity with one server-owned Engineer binding."""

    issuer = f"https://integration.pytest.invalid/{uuid4().hex}"
    subject = "integration-engineer"
    key_file = "dayu-integration-test-key.pem"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", issuer)
    monkeypatch.setenv("OIDC_AUDIENCE", "dayu-api")
    monkeypatch.setenv("OIDC_PUBLIC_KEY_FILE", key_file)
    monkeypatch.setenv("OIDC_ALLOWED_ALGORITHMS", "RS256")
    original_read_text = Path.read_text
    monkeypatch.setattr(
        "app.security.auth.Path.read_text",
        lambda path, *args, **kwargs: (
            public_pem.decode()
            if path.name == key_file
            else original_read_text(path, *args, **kwargs)
        ),
    )
    with SessionLocal() as session:
        principal = IdentityPrincipal(
            issuer=issuer,
            subject=subject,
            display_name="Engineering Integration User",
            authentication_method="oidc",
        )
        session.add(principal)
        session.flush()
        session.add(
            IdentityRoleBinding(
                principal_id=principal.id,
                role="engineer",
                active=True,
                created_by_principal_id=principal.id,
            )
        )
        session.commit()
    now = datetime.now(UTC)
    access_token = jwt.encode(
        {
            "iss": issuer,
            "sub": subject,
            "aud": "dayu-api",
            "exp": now + timedelta(minutes=5),
            "iat": now,
            "name": "Engineering Integration User",
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {access_token}"}
