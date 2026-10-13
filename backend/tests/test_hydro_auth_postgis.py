"""Disposable PostGIS integration for HYDRO-AUTH-01 identity evidence."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.security.models import IdentityPrincipal, IdentityRoleBinding
from app.security.service import observe_principal


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_HYDRO_AUTH_POSTGIS") != "1",
    reason="requires a disposable database migrated to 20261010_0038",
)


def test_issuer_subject_identity_and_local_role_binding_round_trip() -> None:
    """Persist one principal and prove token claims do not create role rows."""

    token = uuid4().hex
    issuer = f"https://pytest.invalid/{token}"
    with SessionLocal() as session:
        try:
            principal, roles = observe_principal(
                session,
                issuer=issuer,
                subject="reviewer-1",
                display_name="Disposable Reviewer",
                email=None,
                authentication_method="oidc",
            )
            assert roles == ()
            session.add(
                IdentityRoleBinding(
                    principal_id=principal.id,
                    role="engineering_reviewer",
                    active=True,
                    created_by_principal_id=principal.id,
                )
            )
            session.flush()
            observed, roles = observe_principal(
                session,
                issuer=issuer,
                subject="reviewer-1",
                display_name="Renamed Reviewer",
                email="reviewer@example.invalid",
                authentication_method="oidc",
            )
            assert observed.id == principal.id
            assert roles == ("engineering_reviewer",)
            assert (
                session.scalar(
                    select(IdentityPrincipal).where(
                        IdentityPrincipal.issuer == issuer,
                        IdentityPrincipal.subject == "reviewer-1",
                    )
                )
                is not None
            )
        finally:
            session.rollback()
