"""OpenAPI and generated-client coverage for the additive native-v4 surface."""

from pathlib import Path

from app.main import create_app


def test_openapi_exposes_the_complete_restricted_v4_surface() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        "/api/v1/model-data/simulation-cases/{case_id}/input-v4/readiness",
        "/api/v1/model-data/simulation-cases/{case_id}/input-v4/preview",
        "/api/v1/model/v4/tasks/{task_id}/sections",
        "/api/v1/model/v4/tasks/{task_id}/gates",
        "/api/v1/model/v4/tasks/{task_id}/pumps",
        "/api/v1/model/v4/tasks/{task_id}/events",
        "/api/v1/model/v4/tasks/{task_id}/summary",
        "/api/v1/model/v4/tasks/{task_id}/artifacts",
        "/api/v1/model/v4/tasks/{task_id}/artifacts/{artifact_id}/download",
        "/api/v1/model/v4/shadow-pairs",
        "/api/v1/model/v4/shadow-pairs/{group_id}",
    }
    assert required <= paths.keys()
    download = paths[
        "/api/v1/model/v4/tasks/{task_id}/artifacts/{artifact_id}/download"
    ]["get"]
    assert "internal" in download["description"].lower()


def test_generated_client_contains_v4_calls_and_types() -> None:
    source = (
        Path(__file__).parents[2] / "frontend" / "src" / "api" / "generated" / "client.ts"
    ).read_text(encoding="utf-8")
    for symbol in (
        "getModelInputV4Readiness",
        "getHydraulicV4Section",
        "getHydraulicV4Gates",
        "getHydraulicV4Pumps",
        "getHydraulicV4Events",
        "getHydraulicV4Summary",
        "downloadHydraulicV4Artifact",
        "createHydraulicV4ShadowPair",
    ):
        assert f"export const {symbol}" in source
