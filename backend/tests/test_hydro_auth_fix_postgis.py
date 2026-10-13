"""AUTH-FIX-T01–T20 on isolated PostgreSQL with actual runtime-role connections.

Readiness is a named synthetic software fixture; the real locks, transactions,
authorization evidence and database ACLs remain in use. No engineering claim.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi import HTTPException
import psycopg
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.database.session import SessionLocal, engine
from app.dataset.schemas import Real01FreezeRequest
from app.dataset.service import freeze_dataset_version_for_real01
from app.gis.models import DatasetVersion
from app.security.auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_permission,
)
from app.security.models import (
    DatasetReview,
    IdentityPrincipal,
    SecurityAuditEvent,
)
from app.security.permissions import permissions_for_roles
from app.security.service import (
    decide_dataset_review,
    grant_role,
    revoke_role,
    submit_dataset_review,
)
from database.bootstrap_app import (
    _bootstrap_security_admin,
    _configure_privileges,
    _ensure_login_role,
    _reset_memberships,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HYDRO_AUTH_FIX_POSTGIS") != "1",
    reason="requires disposable owner database migrated to 0039",
)
GRAPH_HASH = "a" * 64


@pytest.fixture(scope="module")
def runtime_sessions():
    """Provision a real non-owner login with a non-owner inherited publisher group."""

    password = uuid4().hex
    with engine.begin() as connection:
        cursor = connection.connection.driver_connection.cursor()
        owner = cursor.execute("SELECT current_user").fetchone()[0]
        database = cursor.execute("SELECT current_database()").fetchone()[0]
        if not cursor.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='dayu_auth_fix_publisher'"
        ).fetchone():
            cursor.execute("CREATE ROLE dayu_auth_fix_publisher NOLOGIN")
        _ensure_login_role(cursor, "dayu_backend", password)
        _reset_memberships(cursor, "dayu_backend")
        _configure_privileges(
            cursor,
            owner=owner,
            database=database,
            app_role="dayu_backend",
            publisher="dayu_auth_fix_publisher",
        )
        # Rebootstrap proves blanket grants are corrected on every deployment.
        _configure_privileges(
            cursor,
            owner=owner,
            database=database,
            app_role="dayu_backend",
            publisher="dayu_auth_fix_publisher",
        )
        cursor.close()
    runtime_engine = create_engine(
        engine.url.set(username="dayu_backend", password=password), pool_pre_ping=True
    )
    yield sessionmaker(bind=runtime_engine, expire_on_commit=False)
    runtime_engine.dispose()


@pytest.fixture
def workflow(monkeypatch, runtime_sessions):
    """Persist a synthetic draft and actors, patching only graph/QA software inputs."""

    state = {"hash": GRAPH_HASH, "qa_hash": GRAPH_HASH, "ready": True}

    def readiness(_session, _version):
        """Represent current-hash QA, while lifecycle code still validates the decision hash."""
        return SimpleNamespace(
            can_freeze=state["ready"] and state["hash"] == state["qa_hash"],
            engineering_content_hash=state["hash"],
            missing_data_records=[],
        )

    monkeypatch.setattr("app.security.service.build_real01_readiness", readiness)
    monkeypatch.setattr("app.dataset.service.build_real01_readiness", readiness)
    monkeypatch.setattr(
        "app.security.service.engineering_graph_content_hash", lambda _s, _id: state["hash"]
    )
    actors = []
    with SessionLocal() as session:
        for role in (
            "engineer",
            "engineering_reviewer",
            "dataset_freezer",
            "security_admin",
            "engineering_reviewer",
        ):
            row = IdentityPrincipal(
                issuer="https://fix-fixture.invalid",
                subject=uuid4().hex,
                display_name=role,
                authentication_method="oidc",
            )
            session.add(row)
            session.flush()
            actors.append(
                AuthenticatedPrincipal(
                    row.id,
                    row.issuer,
                    row.subject,
                    row.display_name,
                    None,
                    "oidc",
                    (role,),
                    permissions_for_roles((role,)),
                )
            )
        version = DatasetVersion(
            version=uuid4().hex,
            name="Synthetic authorization fixture",
            creator="pytest",
            status="draft",
        )
        session.add(version)
        session.commit()
        version_id = version.id

    def run(operation, **kwargs):
        """Run one transaction under the actual application login, including audit INSERT."""
        with runtime_sessions() as session:
            version = session.get(DatasetVersion, version_id)
            if operation == "submit":
                result = submit_dataset_review(session, version, actors[0], None)
            elif operation == "freeze":
                result = freeze_dataset_version_for_real01(
                    session, version, Real01FreezeRequest(reason="synthetic test"), actors[2]
                )
            else:
                reviewer_index = kwargs.pop("reviewer_index", 1)
                result = decide_dataset_review(
                    session, version, actors[reviewer_index], operation, None, **kwargs
                )
            session.commit()
            return result

    return SimpleNamespace(
        run=run, id=version_id, actors=actors, state=state, sessions=runtime_sessions
    )


def approved(workflow):
    """Create the normal current-round approval used by freeze and invalidation cases."""
    version = workflow.run("submit")
    return workflow.run("approve", review_round=version.current_review_round)


def test_auth_fix_t01_approve_freeze(workflow):
    approved(workflow)
    assert workflow.run("freeze").status == "approved"


def test_auth_fix_t02_return_resubmit_without_approval(workflow):
    decision = approved(workflow)
    workflow.run("return", review_round=1, expected_decision_id=decision.id)
    assert workflow.run("submit").current_review_round == 2
    with pytest.raises(ValueError, match="缺少工程审核"):
        workflow.run("freeze")


def test_auth_fix_t03_resubmit_new_approval_freeze(workflow):
    decision = approved(workflow)
    workflow.run("return", review_round=1, expected_decision_id=decision.id)
    version = workflow.run("submit")
    workflow.run("approve", review_round=version.current_review_round)
    assert workflow.run("freeze").status == "approved"


def test_auth_fix_t04_rejection_is_terminal(workflow):
    decision = approved(workflow)
    workflow.run("reject", review_round=1, expected_decision_id=decision.id)
    with pytest.raises(ValueError):
        workflow.run("submit")
    with pytest.raises(ValueError):
        workflow.run("freeze")


def test_auth_fix_t05_changed_graph_hash(workflow):
    approved(workflow)
    workflow.state.update(hash="b" * 64, qa_hash="b" * 64)
    with pytest.raises(ValueError, match="审核哈希"):
        workflow.run("freeze")


def test_auth_fix_t06_same_hash_old_round_denied(workflow):
    decision = approved(workflow)
    workflow.run("return", review_round=1, expected_decision_id=decision.id)
    workflow.run("submit")
    assert workflow.state["hash"] == GRAPH_HASH
    with pytest.raises(ValueError, match="缺少工程审核"):
        workflow.run("freeze")


def _race(workflow, operations):
    """Start independent database transactions together; conflicting commands cannot both commit."""
    barrier = Barrier(2)

    def perform(item):
        """Synchronize request arrival without replacing any database locks."""
        barrier.wait(timeout=10)
        try:
            workflow.run(item[0], **item[1])
            return "committed"
        except ValueError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(perform, operations))


def test_auth_fix_t07_concurrent_reviewers(workflow):
    workflow.run("submit")
    results = _race(
        workflow,
        [("approve", {"review_round": 1}), ("reject", {"review_round": 1, "reviewer_index": 4})],
    )
    assert sorted(results) == ["committed", "denied"]


def test_auth_fix_t08_return_freeze_race(workflow):
    decision = approved(workflow)
    results = _race(
        workflow,
        [("return", {"review_round": 1, "expected_decision_id": decision.id}), ("freeze", {})],
    )
    assert sorted(results) == ["committed", "denied"]


@pytest.mark.parametrize(
    "table,verb",
    [
        ("security_audit_event", "UPDATE"),
        ("security_audit_event", "DELETE"),
        ("dataset_review", "UPDATE"),
        ("dataset_review", "DELETE"),
    ],
    ids=["AUTH-FIX-T09", "AUTH-FIX-T10", "AUTH-FIX-T11", "AUTH-FIX-T12"],
)
def test_auth_fix_evidence_mutation_denied(runtime_sessions, table, verb):
    with runtime_sessions() as session:
        statement = (
            f"UPDATE public.{table} SET id=id WHERE false"
            if verb == "UPDATE"
            else f"DELETE FROM public.{table} WHERE false"
        )
        with pytest.raises(Exception) as caught:
            session.execute(text(statement))
        assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)
        session.rollback()
        with pytest.raises(Exception) as caught:
            session.execute(text(f"TRUNCATE public.{table}"))
        assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)


def test_auth_fix_t13_app_append_and_role_events(workflow):
    decision = approved(workflow)
    with workflow.sessions() as session:
        assert session.get(DatasetReview, decision.id)
        assert session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.resource_id == str(workflow.id))
        )
        target = session.get(IdentityPrincipal, workflow.actors[0].id)
        grant_role(session, target, "viewer", workflow.actors[3])
        revoke_role(session, target, "viewer", workflow.actors[3])
        session.commit()


def _bootstrap_probe(monkeypatch, *, revoke=False, disable=False):
    """Use a rolled-back owner transaction so bootstrap fixtures cannot affect other cases."""
    monkeypatch.setenv("DAYU_BOOTSTRAP_SECURITY_ADMIN_ISSUER", "https://bootstrap-fixture.invalid")
    monkeypatch.setenv("DAYU_BOOTSTRAP_SECURITY_ADMIN_SUBJECT", uuid4().hex)
    with engine.connect() as connection, connection.begin():
        cursor = connection.connection.driver_connection.cursor()
        cursor.execute("DELETE FROM public.security_bootstrap_state")
        cursor.execute(
            "DELETE FROM public.security_audit_event WHERE action='ROLE_GRANTED' AND details_json->>'source'='initial_bootstrap'"
        )
        cursor.execute("DELETE FROM public.identity_role_binding WHERE role='security_admin'")
        _bootstrap_security_admin(cursor)
        principal_id = cursor.execute(
            "SELECT principal_id FROM public.security_bootstrap_state"
        ).fetchone()[0]
        first_count = cursor.execute("SELECT count(*) FROM public.security_audit_event").fetchone()[
            0
        ]
        if revoke:
            cursor.execute(
                "UPDATE public.identity_role_binding SET active=FALSE WHERE principal_id=%s",
                (principal_id,),
            )
        if disable:
            cursor.execute(
                "UPDATE public.identity_principal SET active=FALSE WHERE id=%s", (principal_id,)
            )
        _bootstrap_security_admin(cursor)
        active, binding_active = cursor.execute(
            "SELECT p.active,b.active FROM public.identity_principal p JOIN public.identity_role_binding b ON b.principal_id=p.id WHERE p.id=%s",
            (principal_id,),
        ).fetchone()
        assert (
            cursor.execute("SELECT count(*) FROM public.security_audit_event").fetchone()[0]
            == first_count
        )
        connection.rollback()
        return active, binding_active


def test_auth_fix_t14_initial_bootstrap(monkeypatch):
    assert _bootstrap_probe(monkeypatch) == (True, True)


def test_auth_fix_t15_repeated_bootstrap(monkeypatch):
    assert _bootstrap_probe(monkeypatch) == (True, True)


def test_auth_fix_t16_revoked_admin_restart(monkeypatch):
    assert _bootstrap_probe(monkeypatch, revoke=True) == (True, False)


def test_auth_fix_t17_disabled_principal_restart(monkeypatch):
    assert _bootstrap_probe(monkeypatch, disable=True) == (False, True)


def test_auth_fix_t18_production_no_oidc(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("DAYU_BUILD_MODE", "release")
    with pytest.raises(HTTPException) as caught:
        get_authenticated_principal(None, SimpleNamespace())
    assert caught.value.status_code == 401


def test_auth_fix_t19_spoofed_role_denied(workflow):
    with pytest.raises(HTTPException) as caught:
        require_permission("dataset.freeze")(workflow.actors[0])
    assert caught.value.status_code == 403


def test_auth_fix_t20_qa_graph_review_binding(workflow):
    approved(workflow)
    workflow.state["qa_hash"] = "b" * 64
    with pytest.raises(ValueError):
        workflow.run("freeze")


def test_runtime_role_owner_membership_and_marker_protection(runtime_sessions):
    with runtime_sessions() as session:
        assert session.scalar(text("SELECT current_user")) == "dayu_backend"
        assert not session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
        assert not session.scalar(
            text(
                "SELECT pg_has_role(current_user, relowner, 'MEMBER') FROM pg_class WHERE oid='public.dataset_review'::regclass"
            )
        )
        assert not session.scalar(
            text("SELECT has_table_privilege(current_user,'security_bootstrap_state','INSERT')")
        )


def test_old_approval_and_standard_scope_cannot_freeze(workflow):
    workflow.run("submit")
    with workflow.sessions() as session:
        actor = workflow.actors[1]
        session.add(
            DatasetReview(
                dataset_version_id=workflow.id,
                engineering_content_hash=GRAPH_HASH,
                action="approve",
                status="approved",
                reviewer_principal_id=actor.id,
                reviewer_issuer=actor.issuer,
                reviewer_subject=actor.subject,
                reviewer_display_name=actor.display_name,
            )
        )
        session.commit()
    with pytest.raises(ValueError, match="缺少工程审核"):
        workflow.run("freeze")
    with SessionLocal() as session:
        version = session.get(DatasetVersion, workflow.id)
        version.current_review_scope = "standard_1d"
        session.commit()
    with pytest.raises(ValueError, match="本轮 REAL-01"):
        workflow.run("freeze")


def test_future_blanket_grant_cannot_mutate_evidence(workflow):
    """A future mistaken grant is still blocked by the non-owner history trigger."""

    decision = approved(workflow)
    with engine.begin() as owner:
        owner.execute(
            text(
                "GRANT UPDATE, DELETE, TRUNCATE ON public.dataset_review TO dayu_auth_fix_publisher"
            )
        )
    try:
        with workflow.sessions() as session:
            assert session.scalar(
                text("SELECT has_table_privilege(current_user,'public.dataset_review','UPDATE')")
            )
            with pytest.raises(Exception) as caught:
                session.execute(
                    text("UPDATE public.dataset_review SET comment='tampered' WHERE id=:id"),
                    {"id": decision.id},
                )
            assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)
    finally:
        with engine.begin() as owner:
            owner.execute(
                text(
                    "REVOKE UPDATE, DELETE, TRUNCATE ON public.dataset_review FROM dayu_auth_fix_publisher"
                )
            )


def test_migration_roundtrip_preserves_history_and_invalidates_unknown_rounds():
    """Run 0039→0038→0039 with real history and compare original row values."""

    tables = (
        "identity_principal",
        "identity_role_binding",
        "dataset_review",
        "security_audit_event",
        "dataset_version",
    )

    def snapshot():
        """Read original evidence fields without comparing removable round metadata."""
        with engine.connect() as connection:
            return {
                table: connection.execute(
                    text(
                        f"SELECT to_jsonb(t)-'review_round'-'review_scope'-'current_review_round'-'current_review_scope' FROM public.{table} t ORDER BY id"
                    )
                )
                .scalars()
                .all()
                for table in tables
            }

    with engine.begin() as connection:
        principal_id = connection.execute(
            text(
                "INSERT INTO identity_principal(issuer,subject,display_name,active,authentication_method) VALUES ('https://historical-admin.invalid',:subject,'Revoked administrator',FALSE,'oidc') RETURNING id"
            ),
            {"subject": uuid4().hex},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO identity_role_binding(principal_id,role,active) VALUES (:id,'security_admin',FALSE)"
            ),
            {"id": principal_id},
        )
    before = snapshot()
    for target in ("downgrade", "upgrade"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(Path(__file__).resolve().parents[2] / "database" / "alembic.ini"),
                target,
                "20261010_0038" if target == "downgrade" else "head",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
    assert snapshot() == before
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM dataset_review WHERE review_round IS NOT NULL")
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM dataset_version WHERE current_review_round<>0")
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM security_bootstrap_state WHERE name='initial_security_admin'"
                )
            )
            == 1
        )
