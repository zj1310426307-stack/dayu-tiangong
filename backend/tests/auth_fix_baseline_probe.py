"""Reproduce FIX-01 risks only against an explicitly isolated migrated database."""

import os
from uuid import uuid4


from app.database.session import SessionLocal
from app.gis.models import DatasetVersion
from app.security.models import DatasetReview, IdentityPrincipal
from app.security.service import latest_approved_review
from database.bootstrap_app import (
    _bootstrap_security_admin,
    _configure_privileges,
    _ensure_login_role,
    _reset_memberships,
)


def main() -> None:
    """Report reproducible evidence, retaining no platform engineering data."""

    assert os.environ.get("RUN_AUTH_FIX_BASELINE") == "1"
    with SessionLocal() as session:
        principal = IdentityPrincipal(
            issuer="https://baseline.invalid",
            subject=uuid4().hex,
            display_name="Baseline probe",
            authentication_method="oidc",
        )
        version = DatasetVersion(
            version=uuid4().hex, name="Isolated probe", creator="probe", status="review"
        )
        session.add_all([principal, version])
        session.flush()
        for action, status in [("approve", "approved"), ("return", "returned")]:
            session.add(
                DatasetReview(
                    dataset_version_id=version.id,
                    engineering_content_hash="a" * 64,
                    action=action,
                    status=status,
                    reviewer_principal_id=principal.id,
                    reviewer_issuer=principal.issuer,
                    reviewer_subject=principal.subject,
                    reviewer_display_name=principal.display_name,
                )
            )
        session.flush()
        # Same-hash resubmission restores review state without new approval.
        selected = latest_approved_review(session, version.id)
        print("BASELINE_OLD_APPROVAL_REUSED=" + str(selected is not None))
        session.rollback()
        connection = session.connection().connection.driver_connection
        with connection.cursor() as cursor:
            owner = cursor.execute("SELECT current_user").fetchone()[0]
            database = cursor.execute("SELECT current_database()").fetchone()[0]
            _ensure_login_role(cursor, "dayu_backend", "isolated-probe-only")
            cursor.execute("CREATE ROLE dayu_auth_fix_publisher NOLOGIN")
            _reset_memberships(cursor, "dayu_backend")
            _configure_privileges(
                cursor,
                owner=owner,
                database=database,
                app_role="dayu_backend",
                publisher="dayu_auth_fix_publisher",
            )
            print(
                "BASELINE_EVIDENCE_UPDATE_ALLOWED="
                + str(
                    cursor.execute(
                        "SELECT has_table_privilege('dayu_backend','security_audit_event','UPDATE') "
                        "AND has_table_privilege('dayu_backend','dataset_review','DELETE')"
                    ).fetchone()[0]
                )
            )
            os.environ["DAYU_BOOTSTRAP_SECURITY_ADMIN_ISSUER"] = "https://bootstrap.invalid"
            os.environ["DAYU_BOOTSTRAP_SECURITY_ADMIN_SUBJECT"] = "initial-admin"
            _bootstrap_security_admin(cursor)
            cursor.execute(
                "UPDATE identity_role_binding SET active=FALSE WHERE role='security_admin'"
            )
            cursor.execute(
                "UPDATE identity_principal SET active=FALSE WHERE issuer='https://bootstrap.invalid'"
            )
            _bootstrap_security_admin(cursor)
            print(
                "BASELINE_REVOKED_ADMIN_REACTIVATED="
                + str(
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM identity_role_binding b JOIN identity_principal p "
                        "ON p.id=b.principal_id WHERE b.role='security_admin' AND b.active AND p.active)"
                    ).fetchone()[0]
                )
            )
        session.rollback()


if __name__ == "__main__":
    main()
