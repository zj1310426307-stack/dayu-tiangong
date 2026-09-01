"""GIS conversion gates for the unified Standard 1D result."""

import pytest

from app.hydraulic.result_geojson import (
    HydraulicResultGeoJSONError,
    build_water_surface_geojson,
)
from model.hydraulic_1d import HydraulicResult, HydraulicResultRecord
from tests.hydraulic_1d.helpers import model_fixture


def _model():
    source = model_fixture()
    locations = ([113.0, 23.0], [113.01, 23.0])
    sections = tuple(
        section.model_copy(
            update={
                "location_geometry": {
                    "type": "Point",
                    "coordinates": locations[index],
                }
            }
        )
        for index, section in enumerate(source.cross_sections)
    )
    return source.model_copy(
        update={"cross_sections": sections, "metadata": {"display_crs": "EPSG:4490"}}
    )


def _result(model):
    records = []
    for time_seconds in (0.0, 60.0):
        for section in model.cross_sections:
            records.append(
                HydraulicResultRecord(
                    simulation_id=model.simulation_id,
                    scenario_id=model.scenario_id,
                    engine="mascaret",
                    engine_version="v9.1.1",
                    branch_id=section.branch_id,
                    chainage_m=section.chainage_m,
                    cross_section_id=section.id,
                    timestamp=time_seconds,
                    water_level_m=2.0 + time_seconds / 600.0,
                    depth_m=2.0 + time_seconds / 600.0,
                    discharge_m3s=11.0,
                    velocity_m_s=1.1,
                    flow_area_m2=10.0,
                )
            )
    return HydraulicResult(
        simulation_id=model.simulation_id,
        scenario_id=model.scenario_id,
        engine="mascaret",
        engine_version="v9.1.1",
        records=tuple(records),
    )


def test_water_surface_uses_exact_unified_rows_and_never_invents_a_polygon() -> None:
    """Create two factual points and their one adjacent line at the requested time."""

    model = _model()
    output = build_water_surface_geojson(model, _result(model), time_seconds=60.0)

    assert output["metadata"]["point_count"] == 2
    assert output["metadata"]["segment_count"] == 1
    assert output["metadata"]["risk_extent_generated"] is False
    assert {item["properties"]["time_seconds"] for item in output["features"]} == {60.0}
    assert all(item["geometry"]["type"] != "Polygon" for item in output["features"])


def test_missing_location_is_explicitly_excluded_or_rejected() -> None:
    """Location gaps remain visible and never trigger spatial interpolation."""

    model = _model()
    sections = (
        model.cross_sections[0],
        model.cross_sections[1].model_copy(update={"location_geometry": None}),
    )
    model = model.model_copy(update={"cross_sections": sections})
    result = _result(model)

    output = build_water_surface_geojson(model, result, time_seconds=60.0)
    assert output["metadata"]["point_count"] == 1
    assert output["metadata"]["segment_count"] == 0
    assert output["excluded"][0]["reason"] == "missing_or_invalid_point_location"
    with pytest.raises(HydraulicResultGeoJSONError, match="no valid Point location"):
        build_water_surface_geojson(
            model,
            result,
            time_seconds=60.0,
            missing_location="error",
        )
