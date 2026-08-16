"""Live PostGIS gates for the GIS-OPT-2 registry and additive geometry model."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from database.seed.gis_registry import validate_gis_registry


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires migrated PostGIS, registry seed, and QGIS role bootstrap",
)


def test_registry_sources_and_qgis_renderer_permissions_are_live() -> None:
    with SessionLocal() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260815_0014"
        assert session.scalar(text("SELECT count(*) FROM gis_layer_registry WHERE active")) == 22
        assert session.scalar(text("SELECT count(*) FROM basemap_registry WHERE active")) == 1
        assert validate_gis_registry(
            session,
            qgis_server_role=os.getenv("QGIS_SERVER_DB_USER", "dayu_qgis_server"),
        ) == {"sources": 22, "qgis_permissions": 4}


def test_cross_section_spatial_rows_cannot_cross_dataset_versions() -> None:
    token = uuid4().hex[:12]
    with SessionLocal() as session:
        version_a = session.scalar(
            text(
                "INSERT INTO dataset_version (version,name,creator,status) "
                "VALUES (:version,:name,'pytest','draft') RETURNING id"
            ),
            {"version": f"XA-{token}", "name": f"Cross A {token}"},
        )
        version_b = session.scalar(
            text(
                "INSERT INTO dataset_version (version,name,creator,status) "
                "VALUES (:version,:name,'pytest','draft') RETURNING id"
            ),
            {"version": f"XB-{token}", "name": f"Cross B {token}"},
        )
        river_id = session.scalar(
            text(
                "INSERT INTO river "
                "(dataset_version_id,name,code,length,level,status,geometry) "
                "VALUES (:version_id,:name,:code,100,'1','active',"
                "ST_GeomFromText('LINESTRING(120 30,120.01 30.01)',4490)) RETURNING id"
            ),
            {"version_id": version_a, "name": f"River {token}", "code": f"R-{token}"},
        )
        cross_section_id = session.scalar(
            text(
                "INSERT INTO cross_section "
                "(dataset_version_id,river_id,section_code,section_name,station,points,"
                "roughness,elevation_min,geometry) "
                "VALUES (:version_id,:river_id,:code,:name,10,'{\"points\":[[0,1],[1,0]]}',"
                "0.03,0,ST_GeomFromText('POINT(120.001 30.001)',4490)) RETURNING id"
            ),
            {
                "version_id": version_a,
                "river_id": river_id,
                "code": f"CS-{token}",
                "name": f"Cross {token}",
            },
        )
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO cross_section_location "
                    "(cross_section_id,dataset_version_id,geometry) "
                    "VALUES (:cross_section_id,:wrong_version,"
                    "ST_GeomFromText('POINT(120.001 30.001)',4490))"
                ),
                {"cross_section_id": cross_section_id, "wrong_version": version_b},
            )
            session.flush()
        session.rollback()
