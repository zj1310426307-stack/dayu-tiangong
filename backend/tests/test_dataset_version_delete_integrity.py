"""Regression contracts for deleting editable Dataset Version topology."""

from pathlib import Path

from sqlalchemy import ForeignKeyConstraint

from app.gis.models import BoundaryCondition, Gate, Pump, RiverSegment
from app.hydraulic.models import HydraulicBranch, HydraulicReach, HydraulicStructure


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / "database/migrations/versions/20260909_0033_dataset_version_topology_delete.py"
)


def _foreign_key(table: object, name: str) -> ForeignKeyConstraint:
    """Return one named table constraint for an exact metadata assertion."""

    matches = [
        constraint
        for constraint in table.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _column_foreign_key(table: object, column_name: str) -> object:
    """Return an unnamed column FK whose database constraint is named in migration."""

    column = table.c[column_name]  # type: ignore[attr-defined]
    assert len(column.foreign_keys) == 1
    return next(iter(column.foreign_keys))


def test_version_owned_topology_uses_statement_end_no_action() -> None:
    """Same-version children may cascade together while direct deletes stay guarded."""

    expected = {
        RiverSegment.__table__: (
            "fk_river_segment_upstream_version",
            "fk_river_segment_downstream_version",
        ),
        HydraulicBranch.__table__: (
            "fk_hydraulic_branch_upstream_node_version",
            "fk_hydraulic_branch_downstream_node_version",
        ),
        HydraulicReach.__table__: (
            "fk_hydraulic_reach_upstream_node_version",
            "fk_hydraulic_reach_downstream_node_version",
        ),
        BoundaryCondition.__table__: (
            "fk_boundary_d2_hydraulic_node_version",
            "fk_boundary_hydraulic_branch_version",
        ),
        HydraulicStructure.__table__: ("fk_hydraulic_structure_branch_network_version",),
        Gate.__table__: (
            "fk_gate_d2_upstream_section_version",
            "fk_gate_d2_downstream_section_version",
        ),
        Pump.__table__: ("fk_pump_d2_section_version",),
    }

    for table, names in expected.items():
        for name in names:
            assert _foreign_key(table, name).ondelete == "NO ACTION"

    assert _column_foreign_key(Gate.__table__, "river_id").ondelete == "NO ACTION"
    assert _column_foreign_key(Pump.__table__, "river_id").ondelete == "NO ACTION"


def test_topology_delete_migration_reverses_each_constraint() -> None:
    """The Alembic migration must be deployable and reversible by constraint name."""

    source = MIGRATION.read_text(encoding="utf-8")
    expected_names = (
        "fk_river_segment_upstream_version",
        "fk_river_segment_downstream_version",
        "fk_hydraulic_branch_upstream_node_version",
        "fk_hydraulic_branch_downstream_node_version",
        "fk_hydraulic_reach_upstream_node_version",
        "fk_hydraulic_reach_downstream_node_version",
        "fk_boundary_d2_hydraulic_node_version",
        "fk_boundary_hydraulic_branch_version",
        "fk_hydraulic_structure_branch_network_version",
        "fk_gate_d2_upstream_section_version",
        "fk_gate_d2_downstream_section_version",
        "fk_pump_d2_section_version",
        "fk_gate_river_id",
        "fk_pump_river_id",
    )
    for name in expected_names:
        assert source.count(f'"{name}"') == 1
    assert 'ondelete="NO ACTION"' in source
    assert 'ondelete="RESTRICT"' in source
