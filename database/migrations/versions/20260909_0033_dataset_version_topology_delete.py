"""Allow complete deletion of version-owned hydraulic topology.

Revision ID: 20260909_0033
Revises: 20260909_0032
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260909_0033"
down_revision: str | None = "20260909_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_fk(
    name: str,
    source_table: str,
    referent_table: str,
    local_columns: list[str],
    remote_columns: list[str],
    *,
    source_schema: str | None = None,
    referent_schema: str | None = None,
    ondelete: str,
) -> None:
    """Replace one internal version-owned FK while keeping its identity stable."""

    op.drop_constraint(name, source_table, type_="foreignkey", schema=source_schema)
    op.create_foreign_key(
        name,
        source_table,
        referent_table,
        local_columns,
        remote_columns,
        source_schema=source_schema,
        referent_schema=referent_schema,
        ondelete=ondelete,
    )


_TOPOLOGY_FOREIGN_KEYS = (
    # Legacy River topology.
    ("fk_river_segment_upstream_version", "river_segment", "river_node", ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], None, None),
    ("fk_river_segment_downstream_version", "river_segment", "river_node", ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], None, None),
    # Unified hydraulic topology.
    ("fk_hydraulic_branch_upstream_node_version", "branch", "node", ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_hydraulic_branch_downstream_node_version", "branch", "node", ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_hydraulic_reach_upstream_node_version", "reach", "node", ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_hydraulic_reach_downstream_node_version", "reach", "node", ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"], "hydraulic", "hydraulic"),
    ("fk_boundary_d2_hydraulic_node_version", "boundary_condition", "node", ["hydraulic_node_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_boundary_hydraulic_branch_version", "boundary_condition", "branch", ["branch_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_hydraulic_structure_branch_network_version", "structure", "branch", ["branch_id", "network_id", "dataset_version_id"], ["id", "network_id", "dataset_version_id"], "hydraulic", "hydraulic"),
    # Version-owned structures and their versioned cross-sections/Rivers.
    ("fk_gate_d2_upstream_section_version", "gate", "cross_section", ["hydraulic_upstream_section_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_gate_d2_downstream_section_version", "gate", "cross_section", ["hydraulic_downstream_section_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_pump_d2_section_version", "pump", "cross_section", ["hydraulic_section_id", "dataset_version_id"], ["id", "dataset_version_id"], None, "hydraulic"),
    ("fk_gate_river_id", "gate", "river", ["river_id"], ["id"], None, None),
    ("fk_pump_river_id", "pump", "river", ["river_id"], ["id"], None, None),
)


def upgrade() -> None:
    """Let version-owned rows cascade together without weakening audit FKs."""

    for name, source, referent, local, remote, source_schema, referent_schema in _TOPOLOGY_FOREIGN_KEYS:
        _replace_fk(
            name,
            source,
            referent,
            local,
            remote,
            source_schema=source_schema,
            referent_schema=referent_schema,
            ondelete="NO ACTION",
        )


def downgrade() -> None:
    """Restore the historical immediate RESTRICT topology behavior."""

    for name, source, referent, local, remote, source_schema, referent_schema in _TOPOLOGY_FOREIGN_KEYS:
        _replace_fk(
            name,
            source,
            referent,
            local,
            remote,
            source_schema=source_schema,
            referent_schema=referent_schema,
            ondelete="RESTRICT",
        )
