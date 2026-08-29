"""D3A-2 explicit-bed ORM and reversible migration contracts."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint

from app.hydraulic.models import HydraulicCrossSection


REPOSITORY_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / "database"
    / "migrations"
    / "versions"
    / "20260829_0023_hydraulic_explicit_bed_elevation.py"
)


def test_cross_section_owns_explicit_bed_authority_without_profile_backfill() -> None:
    table = HydraulicCrossSection.__table__
    assert {
        "bed_elevation_m",
        "bed_elevation_source",
        "bed_elevation_confirmed_by",
        "bed_elevation_confirmed_at",
    } <= set(table.columns.keys())
    assert table.c.bed_elevation_m.nullable is True
    assert table.c.bed_elevation_source.nullable is False
    assert str(table.c.bed_elevation_source.server_default.arg) == "unconfirmed"
    constraints = {
        item.name: str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint) and item.name is not None
    }
    assert "ck_hydraulic_cross_section_bed_source" in constraints
    assert "ck_hydraulic_cross_section_bed_authority" in constraints
    assert "bed_elevation_m IS NULL" in constraints[
        "ck_hydraulic_cross_section_bed_authority"
    ]


def test_0023_is_single_reversible_head_and_never_backfills_from_profile() -> None:
    config = Config(str(REPOSITORY_ROOT / "database" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260829_0023"]
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260828_0022"' in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "min(" not in source.lower()
    assert "UPDATE" not in source
