"""Cross-section spatial extensions must remain strictly additive."""

from pathlib import Path

from app.gis.models import CrossSection, CrossSectionAxis, CrossSectionLocation, CrossSectionPoint, CrossSectionProfile


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_cross_section_contract_is_unchanged() -> None:
    columns = CrossSection.__table__.columns
    assert str(columns.geometry.type).upper().startswith("GEOMETRY(POINT")
    assert "points" in columns and "station" in columns
    assert columns.points.nullable is False and columns.station.nullable is False


def test_spatial_extensions_are_separate_versioned_tables() -> None:
    assert CrossSectionLocation.__tablename__ == "cross_section_location"
    assert CrossSectionAxis.__tablename__ == "cross_section_axis"
    assert CrossSectionPoint.__tablename__ == "cross_section_point"
    assert CrossSectionProfile.__tablename__ == "cross_section_profile"
    assert str(CrossSectionAxis.__table__.columns.geometry.type).upper().startswith("GEOMETRY(LINESTRING")
    for model in (CrossSectionLocation, CrossSectionAxis, CrossSectionPoint, CrossSectionProfile):
        assert {"cross_section_id", "dataset_version_id"} <= set(model.__table__.columns.keys())


def test_migration_downgrade_never_drops_legacy_cross_section() -> None:
    source = (ROOT / "database/migrations/versions/20260815_0014_cross_section_spatial_model.py").read_text(encoding="utf-8")
    downgrade = source.split("def downgrade", 1)[1]
    assert 'drop_table("cross_section")' not in downgrade
    assert "DROP VIEW IF EXISTS publish.cross_section_spatial" in downgrade
    assert 'down_revision: str | None = "20260815_0013"' in source
