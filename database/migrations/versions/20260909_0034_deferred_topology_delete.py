"""Defer version-owned topology checks until the cascade transaction commits.

Revision ID: 20260909_0034
Revises: 20260909_0033
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260909_0034"
down_revision: str | None = "20260909_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINTS = (
    ("fk_river_segment_upstream_version", "river_segment", "river_node", ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], None, None),
    ("fk_river_segment_downstream_version", "river_segment", "river_node", ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], None, None),
    ("fk_hydraulic_branch_upstream_node_version", "branch", "node", ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_hydraulic_branch_downstream_node_version", "branch", "node", ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_hydraulic_reach_upstream_node_version", "reach", "node", ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_hydraulic_reach_downstream_node_version", "reach", "node", ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_boundary_d2_hydraulic_node_version", "boundary_condition", "node", ["hydraulic_node_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_boundary_hydraulic_branch_version", "boundary_condition", "branch", ["branch_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_hydraulic_structure_branch_network_version", "structure", "branch", ["branch_id", "network_id", "dataset_version_id"], ["id", "network_id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_gate_d2_upstream_section_version", "gate", "cross_section", ["hydraulic_upstream_section_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_gate_d2_downstream_section_version", "gate", "cross_section", ["hydraulic_downstream_section_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_pump_d2_section_version", "pump", "cross_section", ["hydraulic_section_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_gate_river_id", "gate", "river", ["river_id"], ["id"], None, None),
    ("fk_pump_river_id", "pump", "river", ["river_id"], ["id"], None, None),
)


def _replace(name: str, source: str, referent: str, local: list[str], remote: list[str], source_schema: str | None, referent_schema: str | None, *, deferred: bool) -> None:
    """Switch the same named FK between immediate and deferred validation."""

    op.drop_constraint(name, source, type_="foreignkey", schema=source_schema)
    op.create_foreign_key(
        name,
        source,
        referent,
        local,
        remote,
        source_schema=source_schema,
        referent_schema=referent_schema,
        ondelete="NO ACTION",
        deferrable=deferred,
        initially="DEFERRED" if deferred else None,
    )


def upgrade() -> None:
    """Allow all version-owned topology cascades to validate at commit time."""

    for constraint in _CONSTRAINTS:
        _replace(*constraint, deferred=True)


def downgrade() -> None:
    """Return to the immediate NO ACTION checks from revision 0033."""

    for constraint in _CONSTRAINTS:
        _replace(*constraint, deferred=False)
