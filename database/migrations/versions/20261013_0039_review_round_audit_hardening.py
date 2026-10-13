"""Bind review rounds, protect evidence, and persist one-time admin bootstrap.

Revision ID: 20261013_0039
Revises: 20261010_0038
"""

from alembic import op
import os
import re
import sqlalchemy as sa

revision = "20261013_0039"
down_revision = "20261010_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep all historical evidence, leaving ambiguous rounds unattributed."""

    op.add_column(
        "dataset_version",
        sa.Column("current_review_round", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("dataset_version", sa.Column("current_review_scope", sa.String(16)))
    op.create_check_constraint(
        "ck_dataset_current_review_round", "dataset_version", "current_review_round >= 0"
    )
    op.create_check_constraint(
        "ck_dataset_current_review_scope",
        "dataset_version",
        "current_review_scope IS NULL OR current_review_scope IN ('real01','standard_1d')",
    )
    op.add_column("dataset_review", sa.Column("review_round", sa.Integer()))
    op.add_column("dataset_review", sa.Column("review_scope", sa.String(16)))
    op.create_check_constraint(
        "ck_dataset_review_round", "dataset_review", "review_round IS NULL OR review_round > 0"
    )
    op.create_check_constraint(
        "ck_dataset_review_scope",
        "dataset_review",
        "review_scope IS NULL OR review_scope IN ('real01','standard_1d')",
    )
    op.create_index(
        "ix_dataset_review_round", "dataset_review", ["dataset_version_id", "review_round", "id"]
    )
    op.create_table(
        "security_bootstrap_state",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column(
            "initialized_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "principal_id",
            sa.Integer(),
            sa.ForeignKey("identity_principal.id", ondelete="RESTRICT"),
        ),
    )
    # Any historical grant, including revoked/disabled accounts, consumes bootstrap.
    op.execute("""
        INSERT INTO public.security_bootstrap_state(name,principal_id)
        SELECT 'initial_security_admin', min(principal_id)
        FROM public.identity_role_binding WHERE role='security_admin'
        HAVING count(*) > 0
    """)
    op.execute("""
        INSERT INTO public.security_bootstrap_state(name)
        SELECT 'initial_security_admin' WHERE EXISTS (
          SELECT 1 FROM public.security_audit_event WHERE action='ROLE_GRANTED'
          AND details_json->>'role'='security_admin'
        ) ON CONFLICT(name) DO NOTHING
    """)
    op.execute("""
        CREATE FUNCTION public.dayu_guard_security_history() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF current_user <> pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid=TG_RELID))
             AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) THEN
            RAISE EXCEPTION 'security history is append-only' USING ERRCODE='42501';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END $$
    """)
    for table in ("dataset_review", "security_audit_event", "security_bootstrap_state"):
        op.execute(
            f"CREATE TRIGGER guard_security_history BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.dayu_guard_security_history()"
        )
        op.execute(
            f"CREATE TRIGGER guard_security_truncate BEFORE TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.dayu_guard_security_history()"
        )
    # One owner-only routine is reused by migrations and every application bootstrap.
    op.execute("""
        CREATE FUNCTION public.dayu_harden_security_evidence(runtime_role text) RETURNS void
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target text; owner_name text; role_name text; creator text;
        BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=runtime_role) THEN RETURN; END IF;
          FOR target IN SELECT unnest(ARRAY['security_audit_event','dataset_review','security_bootstrap_state']) LOOP
            SELECT pg_get_userbyid(relowner) INTO owner_name FROM pg_class
              WHERE oid=('public.' || target)::regclass;
            IF pg_has_role(runtime_role, owner_name, 'MEMBER') OR
               (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=runtime_role) THEN
              RAISE EXCEPTION 'runtime role has owner or privileged access';
            END IF;
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC',target);
            FOR role_name IN SELECT rolname FROM pg_roles
              WHERE pg_has_role(runtime_role, oid, 'MEMBER') LOOP
              IF (SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication
                  FROM pg_roles WHERE rolname=role_name) THEN
                RAISE EXCEPTION 'runtime role inherits privileged role';
              END IF;
              EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', target, role_name);
              EXECUTE format('GRANT SELECT ON TABLE public.%I TO %I', target, role_name);
              IF target <> 'security_bootstrap_state' THEN
                EXECUTE format('GRANT INSERT ON TABLE public.%I TO %I',target,role_name);
              END IF;
              -- Remove old blanket future-table write grants for every creator role.
              FOR creator IN SELECT rolname FROM pg_roles LOOP
                EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE UPDATE, DELETE, TRUNCATE ON TABLES FROM %I',creator,role_name);
              END LOOP;
            END LOOP;
          END LOOP;
        END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.dayu_harden_security_evidence(text) FROM PUBLIC")
    runtime_role = os.getenv("BACKEND_DB_USER", "dayu_backend")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", runtime_role):
        raise ValueError("BACKEND_DB_USER must be a safe PostgreSQL role identifier")
    op.execute(f"SELECT public.dayu_harden_security_evidence('{runtime_role}')")


def downgrade() -> None:
    """Remove additive round metadata only; never delete prior identities or evidence."""

    for table in ("dataset_review", "security_audit_event", "security_bootstrap_state"):
        op.execute(f"DROP TRIGGER guard_security_history ON public.{table}")
        op.execute(f"DROP TRIGGER guard_security_truncate ON public.{table}")
    op.execute("DROP FUNCTION public.dayu_harden_security_evidence(text)")
    op.execute("DROP FUNCTION public.dayu_guard_security_history()")
    op.drop_table("security_bootstrap_state")
    op.drop_index("ix_dataset_review_round", table_name="dataset_review")
    for constraint in ("ck_dataset_review_scope", "ck_dataset_review_round"):
        op.drop_constraint(constraint, "dataset_review", type_="check")
    op.drop_column("dataset_review", "review_scope")
    op.drop_column("dataset_review", "review_round")
    for constraint in ("ck_dataset_current_review_scope", "ck_dataset_current_review_round"):
        op.drop_constraint(constraint, "dataset_version", type_="check")
    op.drop_column("dataset_version", "current_review_scope")
    op.drop_column("dataset_version", "current_review_round")
