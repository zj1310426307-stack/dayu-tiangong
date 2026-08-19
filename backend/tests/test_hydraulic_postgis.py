"""Live PostGIS gates for HYDRO-DATA-01 schema and compatibility writes."""

import os

import pytest
from sqlalchemy import func, select, text

from app.database.session import SessionLocal
from app.cross_section.schemas import CrossSectionCreate
from app.cross_section.service import create_cross_section
from app.gis.models import (
    BoundaryCondition, CrossSection, DatasetVersion, DispatchEvent, DispatchPlan,
    DispatchRun, Gate, JunctionResult, Pump, River, RiverConnection, RiverNode,
    RiverSegment, SimulationCase, SimulationCaseBoundary, SimulationResult,
    SimulationTask, StructureResult,
)
from app.hydraulic.model_input import build_model_input_v3
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicChainage,
    HydraulicCrossSection,
    HydraulicCrossSectionProfile,
    HydraulicCrossSectionPoint,
    HydraulicNetwork,
    HydraulicNode,
    HydraulicReach,
)
from app.hydraulic.processing import process_profile
from app.hydraulic.schemas import CoordinateReferenceSpec
from app.hydraulic.service import build_exchange_payload, commit_import, preview_import
from app.hydraulic.topology import build_topology
from app.model_engine.service import persist_engine_result
from app.river.schemas import RiverCreate
from app.river.service import create_river
from model import HydraulicEngine
from model.provenance import snapshot_hash


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HYDRAULIC_POSTGIS_TESTS") != "1",
    reason="requires an isolated PostGIS database migrated through revision 0019",
)


def _coordinate_reference() -> CoordinateReferenceSpec:
    """Declare geographic source values and the projected topology workspace explicitly."""

    return CoordinateReferenceSpec(
        source_crs="EPSG:4490",
        engineering_crs="EPSG:4547",
        coordinate_mode="geographic",
        axis_mapping="x_easting_y_northing",
        horizontal_unit="degree",
        vertical_datum="1985 National Height Datum",
        central_meridian=114,
        zone_width=3,
    )


def _complete_workbook_text() -> bytes:
    """Return one combined deterministic exchange file used by the transaction gate."""

    return b"""// HYDRO-DATA-01-NWK11
[HYDRO_NETWORK]
  NetworkCode = 'TX-NET'
  NetworkName = 'Transaction network'
  [BRANCH]
    Code = 'TX-RIVER'
    RiverName = 'Transaction river'
    BranchName = 'Main'
    FlowDirection = 'forward'
    Point = 0, 113.1000, 23.1000
    Point = 1000, 113.1100, 23.1100
  EndSect  // BRANCH
EndSect  // HYDRO_NETWORK
"""


def _section_text() -> bytes:
    """Return three ready sections that attach to the committed branch."""

    return b"""// HYDRO-DATA-01-XNS11
[CROSS_SECTION]
  SectionCode = 'TX-XS-250'
  BranchCode = 'TX-RIVER'
  Chainage = 250
  TopographyID = 'DEFAULT'
  Location = 113.1025, 23.1025
  AxisPoint = 113.1024, 23.1026
  AxisPoint = 113.1026, 23.1024
  Point = 0, 0, 12
  Point = 1, 5, 9
  Point = 2, 10, 12
EndSect  // CROSS_SECTION
[CROSS_SECTION]
  SectionCode = 'TX-XS-500'
  BranchCode = 'TX-RIVER'
  Chainage = 500
  TopographyID = 'DEFAULT'
  Location = 113.1050, 23.1050
  AxisPoint = 113.1049, 23.1051
  AxisPoint = 113.1051, 23.1049
  Point = 0, 0, 12
  Point = 1, 5, 9
  Point = 2, 10, 12
EndSect  // CROSS_SECTION
[CROSS_SECTION]
  SectionCode = 'TX-XS-750'
  BranchCode = 'TX-RIVER'
  Chainage = 750
  TopographyID = 'DEFAULT'
  Location = 113.1075, 23.1075
  AxisPoint = 113.1074, 23.1076
  AxisPoint = 113.1076, 23.1074
  Point = 0, 0, 12
  Point = 1, 5, 9
  Point = 2, 10, 12
EndSect  // CROSS_SECTION
"""


def test_migration_and_atomic_dual_write_round_trip() -> None:
    """A confirmed import must populate semantic and existing GIS tables together."""

    with SessionLocal() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260818_0019"
        version = DatasetVersion(
            version="HYDRO-TX-1",
            name="Hydraulic transaction test",
            creator="pytest",
            status="draft",
        )
        session.add(version)
        session.commit()

        network_preview = preview_import(
            session, version.id, "network.nwk11", _complete_workbook_text(),
            _coordinate_reference(),
        )
        session.commit()
        assert network_preview.job.status == "previewed"
        assert commit_import(
            session, network_preview.job.job_code, network_preview.job.config_hash
        ).status == "committed"
        session.commit()

        session.execute(text(
            "SELECT setval(pg_get_serial_sequence('cross_section', 'id'), 3000, true)"
        ))

        section_preview = preview_import(
            session, version.id, "sections.xns11", _section_text(),
            _coordinate_reference(),
        )
        session.commit()
        assert section_preview.job.status == "previewed"
        assert commit_import(
            session, section_preview.job.job_code, section_preview.job.config_hash
        ).status == "committed"
        session.commit()

        network = session.scalar(select(HydraulicNetwork).where(
            HydraulicNetwork.dataset_version_id == version.id,
        ))
        assert network is not None
        session.execute(text(
            "SELECT setval(pg_get_serial_sequence('river_node', 'id'), 1000, true)"
        ))
        session.execute(text(
            "SELECT setval(pg_get_serial_sequence('river_segment', 'id'), 2000, true)"
        ))
        topology = build_topology(session, network.id, 1.0, 1.0)
        session.commit()
        assert topology.node_count == 2
        assert topology.reach_count == 1

        assert session.scalar(select(func.count(River.id))) == 1
        assert session.scalar(select(func.count(CrossSection.id))) == 3
        assert session.scalar(select(func.count(HydraulicBranch.id))) == 1
        assert session.scalar(select(func.count(HydraulicChainage.id))) == 2
        assert session.scalar(select(func.count(HydraulicCrossSection.id))) == 3
        assert session.scalar(select(func.count(HydraulicCrossSectionProfile.id))) == 3
        assert session.scalar(select(func.count(HydraulicCrossSectionPoint.id))) == 9
        assert session.scalar(select(func.count(HydraulicNode.id))) == 2
        assert session.scalar(select(func.count(HydraulicReach.id))) == 1
        assert session.scalar(select(func.count(RiverNode.id))) == 2
        assert session.scalar(select(func.count(RiverSegment.id))) == 1
        assert session.scalar(select(func.count(RiverConnection.id))) == 1
        branch_srid = session.scalar(
            select(func.ST_SRID(HydraulicBranch.geometry)).where(
                HydraulicBranch.dataset_version_id == version.id
            )
        )
        assert branch_srid == 4490
        exported = build_exchange_payload(session, version.id)
        assert [branch.code for branch in exported.branches] == ["TX-RIVER"]
        assert [section.section_code for section in exported.sections] == [
            "TX-XS-250", "TX-XS-500", "TX-XS-750",
        ]

        for profile in session.scalars(select(HydraulicCrossSectionProfile).where(
            HydraulicCrossSectionProfile.dataset_version_id == version.id
        ).order_by(HydraulicCrossSectionProfile.id)).all():
            process_profile(session, profile.id, 0.5)
        branch = session.scalar(select(HydraulicBranch).where(
            HydraulicBranch.network_id == network.id
        ))
        assert branch is not None
        legacy_segment = session.scalar(select(RiverSegment).where(
            RiverSegment.dataset_version_id == version.id,
            RiverSegment.segment_code == f"HYD-{network.id}-{branch.branch_code}",
        ))
        assert legacy_segment is not None
        legacy_upstream = session.get(RiverNode, legacy_segment.upstream_node_id)
        legacy_downstream = session.get(RiverNode, legacy_segment.downstream_node_id)
        assert legacy_upstream is not None and legacy_downstream is not None
        assert legacy_upstream.id != branch.upstream_node_id
        assert legacy_downstream.id != branch.downstream_node_id
        assert legacy_segment.id != branch.id

        upstream_boundary = BoundaryCondition(
            dataset_version_id=version.id,
            name="TX upstream flow",
            boundary_type="upstream_flow",
            target_node_id=legacy_upstream.id,
            values={"value": 25.0},
            unit="m3/s",
        )
        downstream_boundary = BoundaryCondition(
            dataset_version_id=version.id,
            name="TX downstream level",
            boundary_type="downstream_water_level",
            target_node_id=legacy_downstream.id,
            values={"value": 10.0},
            unit="m",
        )
        session.add_all([upstream_boundary, downstream_boundary])
        session.flush()
        case = SimulationCase(
            name="HYDRO-TX-v3 identity mapping",
            dataset_version_id=version.id,
            boundary_condition_id=upstream_boundary.id,
        )
        session.add(case)
        session.flush()
        session.add_all([
            SimulationCaseBoundary(
                case_id=case.id,
                boundary_condition_id=upstream_boundary.id,
                role="upstream",
            ),
            SimulationCaseBoundary(
                case_id=case.id,
                boundary_condition_id=downstream_boundary.id,
                role="downstream",
            ),
            Gate(
                dataset_version_id=version.id,
                name="TX gate",
                gate_code="TX-GATE",
                river_id=branch.legacy_river_id,
                gate_type="sluice",
                opening_direction="vertical",
                control_mode="manual",
                width=3.0,
                height=2.0,
                max_flow=100.0,
                bottom_elevation=8.0,
                river_segment_id=legacy_segment.id,
                upstream_node_id=legacy_upstream.id,
                downstream_node_id=legacy_downstream.id,
                status="online",
                geometry=func.ST_SetSRID(func.ST_MakePoint(113.105, 23.105), 4490),
            ),
            Pump(
                dataset_version_id=version.id,
                name="TX pump",
                pump_code="TX-PUMP",
                river_id=branch.legacy_river_id,
                design_flow=10.0,
                head=3.0,
                power=100.0,
                efficiency_curve={"points": [[0.0, 0.70], [10.0, 0.80]]},
                intake_node_id=legacy_upstream.id,
                outlet_node_id=legacy_downstream.id,
                transfer_type="internal_transfer",
                control_mode="manual",
                status="online",
                geometry=func.ST_SetSRID(func.ST_MakePoint(113.105, 23.105), 4490),
            ),
        ])
        session.flush()

        legacy_section = session.scalar(select(CrossSection).where(
            CrossSection.dataset_version_id == version.id,
            CrossSection.section_code == "TX-XS-500",
        ))
        hydraulic_section = session.scalar(select(HydraulicCrossSection).where(
            HydraulicCrossSection.dataset_version_id == version.id,
            HydraulicCrossSection.section_code == "TX-XS-500",
        ))
        assert legacy_section is not None and hydraulic_section is not None
        assert legacy_section.id != hydraulic_section.id
        model_input = build_model_input_v3(
            session,
            case.id,
            dispatch_plan={
                "schema_version": "dayu.dispatch-plan.v1",
                "rules": [
                    {
                        "id": 501,
                        "observation_type": "node_water_level",
                        "observation_object_id": legacy_upstream.id,
                    },
                    {
                        "id": 502,
                        "observation_type": "section_water_level",
                        "observation_object_id": legacy_section.id,
                    },
                ],
            },
        )
        assert model_input is not None
        assert {
            item["target_node_id"] for item in model_input["boundary_conditions"]
        } == {branch.upstream_node_id, branch.downstream_node_id}
        gate_row = model_input["gates"][0]
        assert gate_row["upstream_node_id"] == branch.upstream_node_id
        assert gate_row["downstream_node_id"] == branch.downstream_node_id
        assert gate_row["river_segment_id"] == branch.id
        assert gate_row["branch_id"] == branch.id
        assert gate_row["chainage"] == gate_row["station"]
        assert gate_row["control_state"]["opening"] is None
        pump_row = model_input["pumps"][0]
        assert pump_row["intake_node_id"] == branch.upstream_node_id
        assert pump_row["outlet_node_id"] == branch.downstream_node_id
        assert pump_row["branch_id"] == branch.id
        assert pump_row["chainage"] is None
        assert pump_row["provenance"]["chainage_source"] == (
            "unavailable_not_inferred"
        )
        assert model_input["structures"]["gates"] == model_input["gates"]
        assert model_input["structures"]["pumps"] == model_input["pumps"]
        assert [
            rule["observation_object_id"]
            for rule in model_input["dispatch_plan"]["rules"]
        ] == [branch.upstream_node_id, hydraulic_section.id]
        assert model_input["controls"]["rules"] == model_input["dispatch_plan"][
            "rules"
        ]
        assert {
            (item["legacy_river_node_id"], item["hydraulic_node_id"])
            for item in model_input["compatibility_mapping"]["river_nodes"]
        } == {
            (legacy_upstream.id, branch.upstream_node_id),
            (legacy_downstream.id, branch.downstream_node_id),
        }
        assert model_input["compatibility_mapping"]["cross_sections"] == [
            {
                "legacy_cross_section_id": 3001,
                "hydraulic_cross_section_id": 1,
            },
            {
                "legacy_cross_section_id": 3002,
                "hydraulic_cross_section_id": 2,
            },
            {
                "legacy_cross_section_id": 3003,
                "hydraulic_cross_section_id": 3,
            },
        ]

        gate = session.scalar(select(Gate).where(Gate.gate_code == "TX-GATE"))
        pump = session.scalar(select(Pump).where(Pump.pump_code == "TX-PUMP"))
        assert gate is not None and pump is not None
        # Keep this persistence gate inside the deliberately small 9–12 m
        # tabulated profile range; the test is about identity-safe result writes,
        # not a high-flow calibration of the three-point fixture geometry.
        upstream_boundary.values = {"value": 0.05}
        gate.max_flow = 0.04
        pump.design_flow = 0.01
        session.flush()
        runnable_plan = {
            "schema_version": "dayu.dispatch-plan.v1",
            "actions": [],
            "rules": [
                {
                    "id": 601,
                    "name": "Open TX gate at start",
                    "enabled": True,
                    "observation_type": "elapsed_time",
                    "observation_object_id": None,
                    "operator": ">=",
                    "threshold": 0.0,
                    "hysteresis": 0.0,
                    "minimum_hold_seconds": 0.0,
                    "cooldown_seconds": 0.0,
                    "action_template": {
                        "structure_type": "gate",
                        "structure_id": gate.id,
                        "command_type": "gate_opening_m",
                        "target_value": 1.0,
                    },
                    "priority": 10,
                },
                {
                    "id": 602,
                    "name": "Start TX pump at start",
                    "enabled": True,
                    "observation_type": "elapsed_time",
                    "observation_object_id": None,
                    "operator": ">=",
                    "threshold": 0.0,
                    "hysteresis": 0.0,
                    "minimum_hold_seconds": 0.0,
                    "cooldown_seconds": 0.0,
                    "action_template": {
                        "structure_type": "pump",
                        "structure_id": pump.id,
                        "command_type": "pump_enabled",
                        "target_value": 1.0,
                    },
                    "priority": 10,
                },
            ],
        }
        run_config = {
            "duration_seconds": 3600.0,
            "time_step_seconds": 60.0,
            "output_interval_seconds": 3600.0,
            "storage_level": "full",
            "allow_fallback_boundary": False,
        }
        runnable_input = build_model_input_v3(
            session,
            case.id,
            controls={
                "section_geometry": "tabulated",
                "runtime_overrides": run_config,
            },
            dispatch_plan=runnable_plan,
        )
        assert runnable_input is not None
        task = SimulationTask(
            case_id=case.id,
            status="running",
            progress=80,
            config=run_config,
            input_schema_version="dayu.model-input.v3",
            input_snapshot=runnable_input,
            input_snapshot_hash=snapshot_hash(runnable_input),
            engine_version="pytest",
            engine_commit="pytest",
        )
        plan = DispatchPlan(
            dataset_version_id=version.id,
            simulation_case_id=case.id,
            name="HYDRO-MODEL-01 PG16 persistence",
            version=1,
            status="frozen",
            duration_seconds=3600.0,
            evaluation_config={},
            storage_level="full",
            created_by="pytest",
            frozen_snapshot=runnable_plan,
            frozen_snapshot_hash=snapshot_hash(runnable_plan),
        )
        session.add_all([task, plan])
        session.flush()
        dispatch_run = DispatchRun(
            plan_id=plan.id,
            controlled_task_id=task.id,
            status="running",
            progress=80,
        )
        session.add(dispatch_run)
        session.flush()

        engine_result = HydraulicEngine().run(runnable_input, run_config)
        task_record = persist_engine_result(session, task, engine_result)

        assert task_record.status == "success"
        assert session.scalar(select(func.count(SimulationResult.id)).where(
            SimulationResult.task_id == task.id
        )) == 6
        assert session.scalar(select(func.count(JunctionResult.id)).where(
            JunctionResult.task_id == task.id
        )) == 4
        assert session.scalar(select(func.count(StructureResult.id)).where(
            StructureResult.task_id == task.id
        )) == 4
        assert session.scalar(select(func.count(DispatchEvent.id)).where(
            DispatchEvent.run_id == dispatch_run.id
        )) >= 4
        assert set(session.scalars(select(SimulationResult.section_id).where(
            SimulationResult.task_id == task.id
        )).all()) == {3001, 3002, 3003}
        assert set(session.scalars(select(JunctionResult.node_id).where(
            JunctionResult.task_id == task.id
        )).all()) == {legacy_upstream.id, legacy_downstream.id}

        with pytest.raises(
            ValueError,
            match=(
                "model-input.v3 readiness failed:.*observation_object_id.*"
                "cross_section 3999.*without a verified"
            ),
        ):
            build_model_input_v3(
                session,
                case.id,
                dispatch_plan={
                    "rules": [{
                        "id": 503,
                        "observation_type": "section_water_level",
                        "observation_object_id": 3999,
                    }]
                },
            )

        unmapped_node = RiverNode(
            dataset_version_id=version.id,
            node_code="UNMAPPED-TX-NODE",
            node_type="start",
            longitude=113.2,
            latitude=23.2,
            geometry=func.ST_SetSRID(func.ST_MakePoint(113.2, 23.2), 4490),
        )
        session.add(unmapped_node)
        session.flush()
        upstream_boundary.target_node_id = unmapped_node.id
        session.flush()
        with pytest.raises(
            ValueError,
            match="model-input.v3 readiness failed:.*target_node_id.*without a verified",
        ):
            build_model_input_v3(session, case.id)
        upstream_boundary.target_node_id = legacy_upstream.id
        session.flush()
        session.delete(unmapped_node)
        session.flush()

        legacy_river = create_river(
            session,
            RiverCreate(
                dataset_version_id=version.id,
                name="Legacy editor river",
                code="LEGACY-RIVER",
                length=250,
                level="branch",
                status="active",
                geometry={
                    "type": "LineString",
                    "coordinates": [[113.2, 23.2], [113.205, 23.205]],
                },
            ),
        )
        create_cross_section(
            session,
            CrossSectionCreate(
                dataset_version_id=version.id,
                river_id=legacy_river.id,
                section_code="LEGACY-XS",
                section_name="Legacy editor section",
                station=125,
                points={"points": [[0, 3], [5, 1], [10, 3]]},
                roughness=0.03,
                elevation_min=1,
                geometry={"type": "Point", "coordinates": [113.2025, 23.2025]},
            ),
        )
        session.commit()
        assert session.scalar(select(func.count(HydraulicBranch.id))) == 2
        assert session.scalar(select(func.count(HydraulicCrossSection.id))) == 4

        unknown_version = DatasetVersion(
            version="HYDRO-TX-UNKNOWN-DIRECTION",
            name="Unconfirmed hydraulic direction test",
            creator="pytest",
            status="draft",
        )
        session.add(unknown_version)
        session.commit()
        unknown_preview = preview_import(
            session,
            unknown_version.id,
            "unknown-direction.nwk11",
            _complete_workbook_text().replace(b"'forward'", b"'unknown'"),
            _coordinate_reference(),
        )
        session.commit()
        assert commit_import(
            session, unknown_preview.job.job_code, unknown_preview.job.config_hash
        ).status == "committed"
        session.commit()
        unknown_branch = session.scalar(select(HydraulicBranch).where(
            HydraulicBranch.dataset_version_id == unknown_version.id,
        ))
        assert unknown_branch is not None
        assert unknown_branch.direction_status == "unknown"
