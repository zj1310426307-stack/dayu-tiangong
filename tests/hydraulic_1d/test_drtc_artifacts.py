"""Contract tests for the version-pinned DIMR/FBC Gate subset."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from model.control.drtc import (
    DRTCFBCArtifactWriter,
    DRTCGateThresholdSpec,
    DRTCManualGateScheduleSpec,
)


def _local(root: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == name]


def test_threshold_bundle_has_explicit_true_and_false_rules(tmp_path: Path) -> None:
    artifacts = DRTCFBCArtifactWriter().write_threshold(
        job_root=tmp_path,
        dflow_input_file="model.mdu",
        start=datetime(2020, 1, 1),
        duration_seconds=600,
        coupling_step_seconds=60,
        spec=DRTCGateThresholdSpec(
            rule_id="gate_rule_1",
            observation_bmi_variable="observations/section-up/water_level",
            actuator_bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
            operator=">=",
            threshold=2.5,
            target_native_value=3.0,
            fallback_native_value=2.2,
        ),
    )

    tools = ET.parse(artifacts.tools_config).getroot()
    constants = _local(tools, "constant")
    assert {item.attrib.get("id") for item in constants} == {
        None,
        "gate_rule_1.true",
        "gate_rule_1.false",
    }
    assert sorted(item.text for item in constants if not list(item)) == [
        "2.2000000000000002",
        "3",
    ]
    assert _local(tools, "relationalOperator")[0].text == "GreaterEqual"
    assert {item.text for item in _local(tools, "ruleReference")} == {
        "gate_rule_1.true",
        "gate_rule_1.false",
    }
    manifest = json.loads(artifacts.manifest.read_text(encoding="utf-8"))
    assert manifest["artifact_hash"] == artifacts.artifact_hash
    assert manifest["semantic_contract"]["kind"] == (
        "simple_threshold_with_explicit_fallback"
    )
    assert "/delft3d/share/drtc" in artifacts.settings.read_text(encoding="utf-8")
    data = ET.parse(artifacts.data_config).getroot()
    assert {item.attrib["id"] for item in _local(data, "timeSeries")} == {
        "input_gate_rule_1_water_level",
        "output_gate_rule_1_gate_lower_edge_level",
        "status_gate_rule_1",
    }
    assert _local(data, "CSVTimeSeriesFile")[0].attrib["adjointOutput"] == "false"
    state = ET.parse(artifacts.tools_config.parent / "state_import.xml").getroot()
    assert {item.attrib["id"] for item in _local(state, "treeVectorLeaf")} == {
        "input_gate_rule_1_water_level",
        "output_gate_rule_1_gate_lower_edge_level",
        "status_gate_rule_1",
    }

    dimr_text = artifacts.dimr_config.read_text(encoding="utf-8")
    assert "flow2rtc" in dimr_text
    assert "rtc2flow" in dimr_text
    assert "orifices/gate-1/gateLowerEdgeLevel" in dimr_text
    assert "<workingDir>input</workingDir>" in dimr_text


def test_manual_schedule_uses_block_table_and_no_flow_feedback(tmp_path: Path) -> None:
    artifacts = DRTCFBCArtifactWriter().write_schedule(
        job_root=tmp_path,
        dflow_input_file="model.mdu",
        start=datetime(2020, 1, 1),
        duration_seconds=600,
        coupling_step_seconds=60,
        spec=DRTCManualGateScheduleSpec(
            schedule_id="gate_schedule_1",
            actuator_bmi_variable="orifices/gate-1/gateLowerEdgeLevel",
            records=((0, 2.2), (180, 3.0), (420, 2.5)),
        ),
    )

    tools = ET.parse(artifacts.tools_config).getroot()
    assert _local(tools, "interpolationOption")[0].text == "BLOCK"
    assert [item.attrib for item in _local(tools, "record")] == [
        {"time": "0", "value": "2.2000000000000002"},
        {"time": "180", "value": "3"},
        {"time": "420", "value": "2.5"},
    ]
    dimr_text = artifacts.dimr_config.read_text(encoding="utf-8")
    assert "flow2rtc" not in dimr_text
    assert "rtc2flow" in dimr_text
    data = ET.parse(artifacts.data_config).getroot()
    assert {item.attrib["id"] for item in _local(data, "timeSeries")} == {
        "input_gate_schedule_1_clock",
        "output_gate_schedule_1_gate_lower_edge_level",
        "time_active_gate_schedule_1",
    }


@pytest.mark.parametrize(
    "spec",
    [
        DRTCGateThresholdSpec,
        DRTCManualGateScheduleSpec,
    ],
)
def test_specs_reject_unreviewed_native_targets(spec: type[object]) -> None:
    with pytest.raises(ValueError, match="Orifice Gate"):
        if spec is DRTCGateThresholdSpec:
            spec(
                rule_id="r1",
                observation_bmi_variable="observations/up/water_level",
                actuator_bmi_variable="pumps/p1/Capacity",
                operator=">",
                threshold=1,
                target_native_value=1,
                fallback_native_value=0,
            )
        else:
            spec(
                schedule_id="s1",
                actuator_bmi_variable="pumps/p1/Capacity",
                records=((0, 1),),
            )
