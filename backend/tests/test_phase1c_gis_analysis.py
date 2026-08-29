"""PostGIS-backed acceptance tests for Phase 1C professional GIS workflows."""

from __future__ import annotations

from datetime import UTC, datetime
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database.session import SessionLocal
from app.gis.models import (
    CrossSection,
    DatasetVersion,
    Gate,
    MapAnnotation,
    SimulationCase,
    SimulationResult,
    SimulationTask,
)
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires the migrated local Phase 1C PostGIS service",
)
client = TestClient(app)


def _build_comparison_fixture() -> tuple[int, int, int, int]:
    """Create two same-version tasks with aligned hydraulic samples."""

    with SessionLocal() as session:
        case = session.scalar(select(SimulationCase).order_by(SimulationCase.id))
        assert case is not None
        section = session.scalar(
            select(CrossSection)
            .where(CrossSection.dataset_version_id == case.dataset_version_id)
            .order_by(CrossSection.id)
        )
        assert section is not None
        tasks = [
            SimulationTask(
                case_id=case.id, dataset_version_id=case.dataset_version_id,
                status="success", progress=100, config={"phase": "1C"},
                end_time=datetime.now(UTC),
            )
            for _ in range(2)
        ]
        session.add_all(tasks)
        session.flush()
        for task, water_level, velocity, flow in (
            (tasks[0], 11.2, 0.8, 40.0),
            (tasks[1], 11.9, 1.1, 45.5),
        ):
            session.add(SimulationResult(
                task_id=task.id, section_id=section.id, river_id=section.river_id,
                section_code=section.section_code, station=section.station,
                time_seconds=3600, water_level=water_level, velocity=velocity, flow=flow,
            ))
        session.commit()
        return case.dataset_version_id, section.id, tasks[0].id, tasks[1].id


def _delete_tasks(*task_ids: int) -> None:
    """Remove temporary comparison tasks and cascade their result rows."""

    with SessionLocal() as session:
        for task_id in task_ids:
            task = session.get(SimulationTask, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def test_annotation_crud_and_scale_visibility() -> None:
    """Annotation CRUD must preserve version identity and enforce display scales."""

    with SessionLocal() as session:
        gate = session.scalar(select(Gate).order_by(Gate.id))
        assert gate is not None
        source_version_id = gate.dataset_version_id
        draft = DatasetVersion(
            version=f"ANNOTATION-{datetime.now(UTC).timestamp()}",
            name="Phase 1C annotation draft",
            creator="pytest",
            status="draft",
        )
        session.add(draft)
        session.commit()
        version_id = draft.id
    created = client.post("/api/v1/gis-analysis/annotations", json={
        "dataset_version_id": version_id, "annotation_type": "parameter",
        "name": "phase1c-crud", "text": "闸门设计流量", "longitude": 120.18,
        "latitude": 30.28, "visible_scale_min": 1000, "visible_scale_max": 25000,
        "related_type": None, "related_id": None,
    })
    assert created.status_code == 201
    annotation_id = created.json()["id"]
    try:
        hidden = client.get("/api/v1/gis-analysis/annotations", params={
            "dataset_version_id": version_id, "scale_denominator": 50000,
            "annotation_type": "parameter",
        }).json()
        visible = client.get("/api/v1/gis-analysis/annotations", params={
            "dataset_version_id": version_id, "scale_denominator": 20000,
            "annotation_type": "parameter",
        }).json()
        assert hidden["total"] == 0
        assert [item["id"] for item in visible["items"]] == [annotation_id]
        updated = client.put(
            f"/api/v1/gis-analysis/annotations/{annotation_id}",
            params={"dataset_version_id": version_id},
            json={"text": "更新后的设计流量", "longitude": 120.19, "latitude": 30.29},
        )
        assert updated.status_code == 200
        assert updated.json()["longitude"] == pytest.approx(120.19)
    finally:
        deleted = client.delete(
            f"/api/v1/gis-analysis/annotations/{annotation_id}",
            params={"dataset_version_id": version_id},
        )
        assert deleted.status_code == 204
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM map_annotation WHERE dataset_version_id=:version_id"),
                {"version_id": version_id},
            )
            session.execute(
                text("DELETE FROM dataset_version WHERE id=:version_id"),
                {"version_id": version_id},
            )
            session.commit()

    frozen = client.post("/api/v1/gis-analysis/annotations", json={
        "dataset_version_id": source_version_id,
        "annotation_type": "parameter",
        "name": "phase1c-frozen-reject",
        "text": "must not mutate published content",
        "longitude": 120.18,
        "latitude": 30.28,
    })
    assert frozen.status_code == 409
    missing_version = client.get("/api/v1/gis-analysis/annotations", params={
        "dataset_version_id": 999999, "scale_denominator": 1000,
    })
    assert missing_version.status_code == 409


def test_trace_box_buffer_nearest_and_vector_tile() -> None:
    """Core analysis must run in PostGIS metres and return stable engineering IDs."""

    traced = client.get("/api/v1/gis-analysis/trace", params={
        "dataset_version_id": 1, "river_id": 1,
    })
    assert traced.status_code == 200
    assert traced.json()["selected_river"]["object_id"] == 1
    assert len(traced.json()["downstream_rivers"]) >= 1

    selected = client.post("/api/v1/gis-analysis/select", json={
        "dataset_version_id": 1, "bbox": [120.0, 30.0, 120.6, 30.5],
    })
    assert selected.status_code == 200
    assert selected.json()["counts"] == {
        "river": 3, "gate": 5, "pump": 3, "cross_section": 20,
    }

    buffered = client.post("/api/v1/gis-analysis/buffer", json={
        "dataset_version_id": 1, "object_type": "gate", "object_id": 1,
        "distance_m": 5000,
    })
    assert buffered.status_code == 200
    assert buffered.json()["distance_basis"] == "PostGIS geography metres"
    assert buffered.json()["buffer_geometry"]["type"] == "Polygon"

    with SessionLocal() as session:
        station_version = DatasetVersion(
            version=f"ANNO-STATION-{datetime.now(UTC).timestamp()}",
            name="Phase 1C station annotation draft",
            creator="pytest",
            status="draft",
        )
        session.add(station_version)
        session.commit()
        station_version_id = station_version.id

    station = client.post("/api/v1/gis-analysis/annotations", json={
        "dataset_version_id": station_version_id,
        "annotation_type": "hydrology_station",
        "name": "phase1c-station", "text": "演示水文站", "longitude": 120.2,
        "latitude": 30.2, "related_type": "hydrology_station", "related_id": 999001,
    })
    assert station.status_code == 201
    try:
        nearest = client.post("/api/v1/gis-analysis/nearest", json={
            "dataset_version_id": station_version_id,
            "longitude": 120.2001, "latitude": 30.2001,
            "facility_types": ["hydrology_station"], "limit": 1,
        })
        assert nearest.status_code == 200
        assert nearest.json()["facilities"][0]["object_type"] == "hydrology_station"
        assert nearest.json()["facilities"][0]["distance_m"] < 20
    finally:
        client.delete(
            f"/api/v1/gis-analysis/annotations/{station.json()['id']}",
            params={"dataset_version_id": station_version_id},
        )
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM dataset_version WHERE id=:version_id"),
                {"version_id": station_version_id},
            )
            session.commit()

    tile = client.get(
        "/api/v1/gis-analysis/vector-tiles/river/8/213/105.mvt",
        params={"dataset_version_id": 1},
    )
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert tile.headers["x-dataset-version"] == "1"
    assert len(tile.content) > 20


def test_dynamic_annotation_comparison_and_professional_pdf() -> None:
    """One simulation time must align labels, A/B differences and the exported map."""

    version_id, section_id, baseline_id, comparison_id = _build_comparison_fixture()
    try:
        annotations = client.get("/api/v1/gis-analysis/annotations", params={
            "dataset_version_id": version_id, "scale_denominator": 50000,
            "annotation_type": "cross_section", "time_seconds": 3600,
            "task_id": baseline_id,
        })
        assert annotations.status_code == 200
        dynamic = next(item for item in annotations.json()["items"] if item["related_id"] == section_id)
        assert dynamic["dynamic_source"] == "simulation"
        assert len(dynamic["dynamic_lines"]) == 2

        comparison = client.get("/api/v1/gis-analysis/comparison-frame", params={
            "dataset_version_id": version_id, "baseline_task_id": baseline_id,
            "comparison_task_id": comparison_id, "time_seconds": 3600,
        })
        assert comparison.status_code == 200
        sample = comparison.json()["water_samples"][0]
        assert sample["water_level_difference"] == pytest.approx(0.7)
        assert sample["velocity_difference"] == pytest.approx(0.3)
        assert sample["flow_difference"] == pytest.approx(5.5)
        assert comparison.json()["execution_authorized"] is False

        pdf = client.post("/api/v1/gis-analysis/thematic-map.pdf", json={
            "dataset_version_id": version_id, "task_id": comparison_id,
            "time_seconds": 3600, "title": "Phase 1C 水动力专题图",
        })
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF-")
        assert len(pdf.content) > 3000
    finally:
        _delete_tasks(baseline_id, comparison_id)


def test_more_than_one_thousand_annotations_share_one_collection_endpoint() -> None:
    """A 1000+ label page must stay bounded and advertise LabelCollection rendering."""

    with SessionLocal() as session:
        draft = DatasetVersion(
            version=f"ANNO-BULK-{datetime.now(UTC).timestamp()}",
            name="Phase 1C bulk annotation draft",
            creator="pytest",
            status="draft",
        )
        session.add(draft)
        session.flush()
        version_id = draft.id
        bulk_insert = text("""
            INSERT INTO map_annotation (
                dataset_version_id, annotation_type, name, text, longitude, latitude,
                rotation, font_size, color, visible_scale_min, visible_scale_max, geometry
            )
            SELECT 1, 'place', 'phase1c-bulk-' || value, '批量点 ' || value,
                   120.05 + (value % 40) * 0.001, 30.05 + (value % 30) * 0.001,
                   0, 11, '#E8F7FF', 0, 5000,
                   ST_SetSRID(ST_MakePoint(
                       120.05 + (value % 40) * 0.001,
                       30.05 + (value % 30) * 0.001
                   ), 4490)
            FROM generate_series(1, 1001) AS value
        """)
        bulk_insert = text(
            bulk_insert.text.replace("SELECT 1, 'place'", "SELECT :version_id, 'place'")
        )
        session.execute(bulk_insert, {"version_id": version_id})
        session.commit()
    try:
        response = client.get("/api/v1/gis-analysis/annotations", params={
            "dataset_version_id": version_id, "scale_denominator": 1000,
            "annotation_type": "place", "limit": 2000,
        })
        assert response.status_code == 200
        assert response.json()["total"] == 1001
        assert len(response.json()["items"]) == 1001
        assert response.json()["renderer"] == "Cesium LabelCollection"
    finally:
        with SessionLocal() as session:
            session.execute(text(
                "DELETE FROM map_annotation WHERE dataset_version_id = :version_id "
                "AND annotation_type = 'place' AND name LIKE 'phase1c-bulk-%'"
            ), {"version_id": version_id})
            session.execute(
                text("DELETE FROM dataset_version WHERE id=:version_id"),
                {"version_id": version_id},
            )
            session.commit()
