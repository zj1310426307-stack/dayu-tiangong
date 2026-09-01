"""Prove Boundary CRUD locations survive through Standard 1D preview mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.dataset.router import router as dataset_router
from app.dataset.schemas import BoundaryConditionCreate
from app.gis.models import BoundaryCondition as BoundaryConditionRow
from app.model_engine import hydraulic_1d_service, service
from app.model_engine.hydraulic_1d_service import _boundary
from app.model_engine.schemas import SimulationTaskCreate
from model.hydraulic_1d.errors import Hydraulic1DValidationError


def test_boundary_crud_openapi_exposes_only_current_hydraulic_semantics() -> None:
    """The HTTP contract names real endpoint/lateral columns and current types."""

    api = FastAPI()
    api.include_router(dataset_router)
    schema = api.openapi()["components"]["schemas"]["BoundaryConditionCreate"]
    properties = schema["properties"]
    assert properties["boundary_type"]["enum"] == [
        "upstream_discharge",
        "downstream_water_level",
        "lateral_inflow",
    ]
    assert {"hydraulic_node_id", "branch_id", "chainage_m"} <= properties.keys()
    assert properties["target_node_id"]["deprecated"] is True
    assert "Standard 1D never uses" in properties["target_node_id"]["description"]
    assert {"hydraulic_node_id", "branch_id", "chainage_m"} <= {
        column.name for column in BoundaryConditionRow.__table__.columns
    }

    BoundaryConditionCreate(
        dataset_version_id=1,
        name="upstream",
        boundary_type="upstream_discharge",
        hydraulic_node_id=10,
        values={"mode": "constant", "value": 12.0},
        unit="m3/s",
    )
    BoundaryConditionCreate(
        dataset_version_id=1,
        name="lateral",
        boundary_type="lateral_inflow",
        branch_id=20,
        chainage_m=300.0,
        values={"mode": "constant", "value": 1.0},
        unit="m3/s",
    )
    with pytest.raises(ValidationError, match="hydraulic_node_id"):
        BoundaryConditionCreate(
            dataset_version_id=1,
            name="legacy-only",
            boundary_type="upstream_discharge",
            target_node_id=999,
            values={"mode": "constant", "value": 12.0},
            unit="m3/s",
        )
    with pytest.raises(ValidationError):
        BoundaryConditionCreate(
            dataset_version_id=1,
            name="retired-type",
            boundary_type="upstream_flow",  # type: ignore[arg-type]
            hydraulic_node_id=10,
            values={"mode": "constant", "value": 12.0},
            unit="m3/s",
        )


def test_model_builder_ignores_legacy_target_and_json_location_fields() -> None:
    """Only hydraulic_node_id or Branch/chainage columns select the model location."""

    branch = SimpleNamespace(
        id=20,
        upstream_node_id=10,
        downstream_node_id=11,
        start_chainage=0.0,
        end_chainage=1000.0,
    )
    endpoint = _boundary(
        SimpleNamespace(
            id=1,
            boundary_type="upstream_discharge",
            target_node_id=999,
            hydraulic_node_id=10,
            branch_id=None,
            chainage_m=None,
            values={"mode": "constant", "value": 12.0},
        ),
        [branch],
    )
    lateral = _boundary(
        SimpleNamespace(
            id=2,
            boundary_type="lateral_inflow",
            target_node_id=999,
            hydraulic_node_id=None,
            branch_id=20,
            chainage_m=300.0,
            values={
                "mode": "constant",
                "value": 1.0,
                "branch_id": 999,
                "chainage_m": 999.0,
            },
        ),
        [branch],
    )
    assert (endpoint.branch_id, endpoint.location) == ("20", "upstream")
    assert (lateral.branch_id, lateral.chainage_m) == ("20", 300.0)


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _PreviewSession:
    """Return deterministic ORM-shaped rows without requiring PostGIS."""

    def __init__(self) -> None:
        self.case = SimpleNamespace(
            id=5,
            dataset_version_id=7,
            boundary_condition_id=1,
            hydraulic_1d_configuration={
                "initial_condition": {
                    "water_level_m": 2.0,
                    "discharge_m3s": 12.0,
                },
                "settings": {
                    "duration_seconds": 600.0,
                    "time_step_seconds": 10.0,
                    "output_interval_seconds": 60.0,
                },
            },
        )
        self.dataset = SimpleNamespace(
            id=7,
            status="published",
            content_hash="a" * 64,
        )
        network = SimpleNamespace(
            id=8,
            engineering_crs="EPSG:32651",
            display_crs="EPSG:4490",
            horizontal_unit="m",
            vertical_unit="m",
            vertical_datum="1985-national-height-datum",
        )
        branch = SimpleNamespace(
            id=20,
            branch_code="B-20",
            direction_status="confirmed",
            upstream_node_id=10,
            downstream_node_id=11,
            start_chainage=0.0,
            end_chainage=1000.0,
        )
        nodes = [
            SimpleNamespace(
                id=node_id,
                node_code=f"N-{node_id}",
                node_name=f"Node {node_id}",
                node_type="boundary",
                geometry={"type": "Point", "coordinates": coordinates},
                metadata_json={},
            )
            for node_id, coordinates in (
                (10, [120.0, 30.0]),
                (11, [120.01, 30.0]),
            )
        ]
        sections = [
            SimpleNamespace(
                id=30,
                branch_id=20,
                section_code="XS-0",
                chainage=0.0,
                orientation_status="confirmed",
                location_geometry={"type": "Point", "coordinates": [120.0, 30.0]},
                axis_geometry=None,
                left_bank=None,
                right_bank=None,
            ),
            SimpleNamespace(
                id=31,
                branch_id=20,
                section_code="XS-1000",
                chainage=1000.0,
                orientation_status="confirmed",
                location_geometry={"type": "Point", "coordinates": [120.01, 30.0]},
                axis_geometry=None,
                left_bank=None,
                right_bank=None,
            ),
        ]
        profiles = [
            SimpleNamespace(
                id=40 + index,
                vertical_unit="m",
                vertical_datum="1985-national-height-datum",
                default_manning_n=0.03,
            )
            for index in range(2)
        ]
        points = [
            SimpleNamespace(
                distance=distance,
                elevation=elevation,
                source_x=None,
                source_y=None,
                source_z=None,
                source_crs=None,
                source_axis_mapping=None,
            )
            for distance, elevation in (
                (0.0, 3.0),
                (5.0, 0.0),
                (15.0, 0.0),
                (20.0, 3.0),
            )
        ]
        boundaries = [
            SimpleNamespace(
                id=1,
                boundary_type="upstream_discharge",
                target_node_id=999,
                hydraulic_node_id=10,
                branch_id=None,
                chainage_m=None,
                values={"mode": "constant", "value": 12.0},
            ),
            SimpleNamespace(
                id=2,
                boundary_type="downstream_water_level",
                target_node_id=999,
                hydraulic_node_id=11,
                branch_id=None,
                chainage_m=None,
                values={"mode": "constant", "value": 2.0},
            ),
            SimpleNamespace(
                id=3,
                boundary_type="lateral_inflow",
                target_node_id=999,
                hydraulic_node_id=None,
                branch_id=20,
                chainage_m=300.0,
                values={"mode": "constant", "value": 1.0},
            ),
        ]

        build_rows = [
            [network],
            [branch],
            nodes,
            sections,
            [profiles[0]],
            points,
            [],
            [profiles[1]],
            points,
            [],
            boundaries,
            [],
        ]
        self._scalar_rows = iter(build_rows + build_rows)

    def get(self, model: type[Any], identity: int) -> Any:
        del identity
        if model.__name__ == "SimulationCase":
            return self.case
        if model.__name__ == "DatasetVersion":
            return self.dataset
        return None

    def scalars(self, statement: Any) -> _Rows:
        del statement
        return _Rows(next(self._scalar_rows))


def test_service_preview_and_readiness_keep_lateral_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview builds the same endpoint/lateral fields exposed by Boundary CRUD."""

    monkeypatch.setattr(
        hydraulic_1d_service,
        "geometry_json",
        lambda _session, geometry: geometry,
    )
    monkeypatch.setattr(
        service,
        "_runtime_readiness",
        lambda _case_id: (True, "test", {"version_verified": True}),
    )
    preview = service.preview_model(
        _PreviewSession(),  # type: ignore[arg-type]
        SimulationTaskCreate(case_id=5),
    )

    assert preview.readiness.ready is True
    assert preview.readiness.blockers == []
    assert preview.snapshot_hash
    assert preview.snapshot is not None
    assert preview.readiness.input_summary == {
        "schema_version": "dayu.hydraulic-1d.input.v1",
        "simulation_id": preview.snapshot["simulation_id"],
        "scenario_id": "5",
        "dataset_version_id": 7,
        "branch_count": 1,
        "section_count": 2,
        "boundary_count": 3,
        "structure_count": 0,
    }
    lateral = next(
        item for item in preview.snapshot["boundaries"] if item["location"] == "lateral"
    )
    assert (lateral["branch_id"], lateral["chainage_m"]) == ("20", 300.0)


def test_structure_selection_cannot_silently_omit_an_active_network_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ID list is an assertion, not a bypass around capability checks."""

    structure = SimpleNamespace(
        id=90,
        structure_name="Unsupported active gate",
        structure_code="G-90",
        branch_id=20,
        structure_type="gate",
        chainage_m=500.0,
        location={"type": "Point", "coordinates": [120.005, 30.0]},
        crest_elevation_m=1.0,
        invert_elevation_m=0.0,
        width_m=4.0,
        height_m=3.0,
        hydraulic_law_type="legacy_gate",
        hydraulic_parameters={},
        operation_rule_type="fixed",
        operation_parameters={},
        status="active",
        metadata_json={},
    )

    class StructureSession:
        def __init__(self) -> None:
            self.rows = iter(([structure], []))

        def scalars(self, statement: Any) -> _Rows:
            del statement
            return _Rows(next(self.rows))

    monkeypatch.setattr(
        hydraulic_1d_service,
        "geometry_json",
        lambda _session, geometry: geometry,
    )

    with pytest.raises(
        Hydraulic1DValidationError,
        match="DAYU_STRUCTURE_CONFIGURATION_INVALID",
    ):
        hydraulic_1d_service._structures(
            StructureSession(),  # type: ignore[arg-type]
            SimpleNamespace(id=5, dataset_version_id=7),
            {"structures": {"structure_ids": []}},
            8,
        )
