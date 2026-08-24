"""Serve a browser-only dispatch API backed by a live HydraulicEngine run.

This fixture exists only for HYDRO-MODEL-01 visual acceptance when the full
PostgreSQL/Celery API stack is unavailable.  It executes ``input.json`` at
startup and exposes the resulting time series through the existing generated
frontend client's read endpoints.  It is not a database/API integration test.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit


DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from model import HydraulicEngine  # noqa: E402


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_metrics(result: dict[str, Any]) -> dict[str, Any]:
    return dict(result.get("metrics") or {})


def build_fixture_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    """Run baseline/controlled cases and build the minimum read-only API map."""

    input_path = DEMO_DIRECTORY / "input.json"
    controlled_input = json.loads(input_path.read_text(encoding="utf-8"))
    baseline_input = copy.deepcopy(controlled_input)
    baseline_input["controls"]["rules"] = []
    baseline_input["dispatch_plan"]["rules"] = []

    engine = HydraulicEngine()
    baseline = engine.run(baseline_input).to_dict()
    controlled = engine.run(controlled_input).to_dict()

    baseline_sections = {
        row["section_code"]: row for row in baseline["section_series"]
    }
    controlled_section = max(
        controlled["section_series"],
        key=lambda row: max(float(value) for value in row["water_level"]),
    )
    baseline_section = baseline_sections[controlled_section["section_code"]]
    baseline_levels = [float(value) for value in baseline_section["water_level"]]
    controlled_levels = [
        float(value) for value in controlled_section["water_level"]
    ]
    differences = [
        controlled_level - baseline_level
        for baseline_level, controlled_level in zip(
            baseline_levels,
            controlled_levels,
            strict=True,
        )
    ]

    metrics = _result_metrics(controlled)
    metrics["maximum_level_reduction"] = max(
        (baseline - controlled_value)
        for baseline, controlled_value in zip(
            baseline_levels,
            controlled_levels,
            strict=True,
        )
    )
    controlled_hash = _canonical_hash(controlled_input)
    baseline_hash = _canonical_hash(baseline_input)
    generated_at = datetime.now(timezone.utc).isoformat()
    maximum_cfl = controlled["diagnostics"].get("maximum_cfl")
    solver = controlled["diagnostics"].get("solver")

    def task(task_id: int, input_hash: str, role: str) -> dict[str, Any]:
        return {
            "id": task_id,
            "case_id": 1,
            "status": "success",
            "progress": 100,
            "config": {
                "role": role,
                "fixture": "live-hydraulic-engine",
                "duration_seconds": 86400,
                "output_interval_seconds": 3600,
            },
            "input_schema_version": "dayu.model-input.v3",
            "input_snapshot_hash": input_hash,
            "engine_version": str(solver),
            "engine_commit": "workspace-uncommitted",
            "snapshot_summary": {
                "source": "examples/hydraulic/gate-pump-demo/input.json",
                "scientific_scope": "quasi-steady software acceptance only",
            },
            "queue_job_id": None,
            "worker_id": "ui-fixture-local",
            "queued_time": generated_at,
            "heartbeat_time": generated_at,
            "cancel_requested": False,
            "retry_count": 0,
            "retry_reason": None,
            "current_simulation_time": 86400,
            "current_cfl": maximum_cfl,
            "diagnostics": controlled["diagnostics"],
            "result_path": None,
            "error_message": None,
            "created_time": generated_at,
            "start_time": generated_at,
            "end_time": generated_at,
        }

    def result_payload(
        task_id: int,
        series: dict[str, Any],
        all_series: list[dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        """Expose the generated-client result contract for browser chart acceptance."""

        return {
            "task_id": task_id,
            "status": "success",
            "section_id": series["section_id"],
            "section_code": series["section_code"],
            "river_id": series["river_id"],
            "station": series["station"],
            "time": series["time"],
            "water_level": series["water_level"],
            "flow": series["flow"],
            "velocity": series["velocity"],
            "available_sections": [
                {
                    "section_id": row["section_id"],
                    "section_code": row["section_code"],
                    "river_id": row["river_id"],
                    "station": row["station"],
                }
                for row in all_series
            ],
            "diagnostics": diagnostics,
        }

    events = [
        {"id": index, **row}
        for index, row in enumerate(controlled["dispatch_events"], start=1)
    ]
    comparison = {
        "run_id": 1,
        "status": "success",
        "baseline_task_id": 1001,
        "controlled_task_id": 1002,
        "section_code": controlled_section["section_code"],
        "time": controlled_section["time"],
        "baseline_water_level": baseline_levels,
        "controlled_water_level": controlled_levels,
        "difference": differences,
        "metrics": metrics,
        "diagnostics": {
            **controlled["diagnostics"],
            "fixture_scope": (
                "real HydraulicEngine result-driven UI visual acceptance; "
                "not a real database/API closure"
            ),
            "input_snapshot_sha256": controlled_hash,
        },
    }
    run = {
        "id": 1,
        "plan_id": 1,
        "baseline_task_id": 1001,
        "controlled_task_id": 1002,
        "status": "success",
        "progress": 100,
        "metrics": metrics,
        "queue_job_id": None,
        "error_message": None,
        "created_time": generated_at,
        "start_time": generated_at,
        "end_time": generated_at,
    }
    plan = {
        "id": 1,
        "dataset_version_id": 1,
        "simulation_case_id": 1,
        "name": "HYDRO-MODEL-01 闸泵调度验收方案",
        "version": 1,
        "status": "frozen",
        "description": (
            "real HydraulicEngine result-driven UI visual acceptance only; "
            "not a real database/API closure"
        ),
        "duration_seconds": 86400,
        "evaluation_config": {},
        "storage_level": "full",
        "created_by": "HydraulicEngine UI fixture",
        "created_time": generated_at,
        "updated_time": generated_at,
        "frozen_time": generated_at,
        "frozen_snapshot_hash": controlled_hash,
        "action_count": 0,
        "rule_count": len(controlled_input["dispatch_plan"].get("rules", [])),
    }
    evidence = {
        "fixture": "HYDRO-MODEL-01 live-engine UI fixture",
        "scope": (
            "real HydraulicEngine result-driven UI visual acceptance only; "
            "not a real database/API closure"
        ),
        "generated_at": generated_at,
        "input_path": "examples/hydraulic/gate-pump-demo/input.json",
        "input_snapshot_sha256": controlled_hash,
        "input_schema_version": controlled["provenance"]["input_schema_version"],
        "result_schema_version": controlled["schema_version"],
        "solver": solver,
        "duration_seconds": controlled["diagnostics"]["time_axis"][-1],
        "output_frame_count": len(controlled["diagnostics"]["time_axis"]),
        "structure_result_count": len(controlled["structure_series"]),
        "dispatch_event_count": len(events),
        "structure_types": sorted(
            {row["structure_type"] for row in controlled["structure_series"]}
        ),
        "structure_sample_hours": sorted(
            {
                float(row["time_seconds"]) / 3600
                for row in controlled["structure_series"]
            }
        ),
        "water_balance": controlled["water_balance"],
    }
    baseline_task = task(1001, baseline_hash, "baseline")
    controlled_task = task(1002, controlled_hash, "controlled")
    payloads = {
        "/api/v1/model-data/dataset-versions": [
            {
                "version": "HYDRO-MODEL-01-DEMO",
                "name": "HYDRO-MODEL-01 闸泵 24h 验收夹具",
                "description": evidence["scope"],
                "creator": "HydraulicEngine UI fixture",
                "id": 1,
                "status": "published",
                "parent_version_id": None,
                "source_batch_id": None,
                "content_hash": controlled_hash,
                "change_summary": "Generated live from the committed v3 input",
                "reviewed_by": None,
                "reviewed_at": None,
                "approved_by": None,
                "approved_at": None,
                "published_at": generated_at,
                "retired_at": None,
                "created_time": generated_at,
            }
        ],
        "/api/v1/dispatch/plans/1": plan,
        "/api/v1/dispatch/runs/1": run,
        "/api/v1/model/tasks": [baseline_task, controlled_task],
        "/api/v1/model/tasks/1001": baseline_task,
        "/api/v1/model/tasks/1002": controlled_task,
        "/api/v1/model/results/1001": result_payload(
            1001,
            baseline_section,
            baseline["section_series"],
            baseline["diagnostics"],
        ),
        "/api/v1/model/results/1002": result_payload(
            1002,
            controlled_section,
            controlled["section_series"],
            controlled["diagnostics"],
        ),
        "/api/v1/dispatch/runs/1/comparison": comparison,
        "/api/v1/dispatch/runs/1/events": events,
        "/api/v1/dispatch/runs/1/structures": controlled["structure_series"],
        "/api/v1/dispatch/runs/1/nodes": controlled["node_series"],
        "/fixture/evidence": evidence,
    }
    return payloads, evidence


class FixtureHandler(BaseHTTPRequestHandler):
    """Expose only the deterministic read endpoints needed by the detail page."""

    payloads: dict[str, Any] = {}
    evidence: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path.rstrip("/") or "/"
        payload = self.payloads.get(path)
        if payload is None:
            self._send_json(
                404,
                {
                    "detail": "HYDRO-MODEL-01 UI fixture endpoint not found",
                    "path": path,
                },
            )
            return
        self._send_json(200, payload)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self.send_response(204)
        self._send_common_headers()
        self.end_headers()

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Dayu-Fixture", "live-hydraulic-engine")
        self.send_header(
            "X-Dayu-Input-SHA256",
            str(self.evidence.get("input_snapshot_sha256", "")),
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"fixture {self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8019)
    args = parser.parse_args()

    FixtureHandler.payloads, FixtureHandler.evidence = build_fixture_payloads()
    server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
    print(json.dumps(FixtureHandler.evidence, ensure_ascii=False, indent=2))
    print(f"fixture listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
