"""河网汇流、分流、边界映射、确定性和有限性基准。"""

import copy
import math

import pytest

from model import HydraulicEngine
from model.boundary.conditions import BoundarySignal
from model.core.errors import HydraulicInputError


def _river(river_id: int, code: str) -> dict:
    """返回一个测试河道记录。"""

    return {"id": river_id, "code": code, "name": code, "status": "active", "length": 1000.0}


def _sections(river_id: int, prefix: str, start_id: int) -> list[dict]:
    """为一个分支构造三个矩形兼容断面。"""

    return [
        {
            "id": start_id + index,
            "river_id": river_id,
            "section_code": f"{prefix}-{index}",
            "station": index * 500.0,
            "points": {"points": [[0.0, 9.0], [20.0, 9.0]]},
            "elevation_min": 9.0,
            "roughness": 0.03,
            "geometry_type": "rectangular",
        }
        for index in range(3)
    ]


def make_y_network(*, bifurcation: bool = False) -> dict:
    """构造两入一出或一入两出的定量测试河网。"""

    if bifurcation:
        edge_specs = [(1, 1, 3), (2, 3, 2), (3, 3, 4)]
        boundaries = [
            {"boundary_type": "upstream_flow", "target_node_id": 1, "values": {"mode": "constant", "value": 20.0}},
            {"boundary_type": "downstream_water_level", "target_node_id": 2, "values": {"mode": "constant", "value": 10.0}},
            {"boundary_type": "downstream_water_level", "target_node_id": 4, "values": {"mode": "constant", "value": 10.0}},
        ]
    else:
        edge_specs = [(1, 1, 3), (2, 2, 3), (3, 3, 4)]
        boundaries = [
            {"boundary_type": "upstream_flow", "target_node_id": 1, "values": {"mode": "constant", "value": 10.0}},
            {"boundary_type": "upstream_flow", "target_node_id": 2, "values": {"mode": "constant", "value": 15.0}},
            {"boundary_type": "downstream_water_level", "target_node_id": 4, "values": {"mode": "constant", "value": 10.0}},
        ]
    segments = [
        {
            "id": river_id,
            "river_id": river_id,
            "segment_code": f"SEG-{river_id}",
            "upstream_node_id": upstream,
            "downstream_node_id": downstream,
            "length": 1000.0,
        }
        for river_id, upstream, downstream in edge_specs
    ]
    return {
        "schema_version": "dayu.model-input.v2",
        "dataset_version": {"id": 1, "version": "TEST"},
        "simulation_case": {"id": 1, "dataset_version_id": 1},
        "rivers": [_river(index, f"R-{index}") for index in range(1, 4)],
        "nodes": [{"id": index, "node_code": f"N-{index}"} for index in range(1, 5)],
        "segments": segments,
        "connections": [
            {"id": index + 1, "river_id": edge[0], "from_node_id": edge[1], "to_node_id": edge[2]}
            for index, edge in enumerate(edge_specs)
        ],
        "cross_sections": _sections(1, "A", 1) + _sections(2, "B", 10) + _sections(3, "C", 20),
        "boundary_conditions": boundaries,
        "parameters": [
            {"parameter_name": "duration_seconds", "value": 600.0},
            {"parameter_name": "output_interval", "value": 60.0},
            {"parameter_name": "initial_water_level", "value": 10.0},
            {"parameter_name": "minimum_depth", "value": 0.05},
        ],
        "gates": [],
        "pumps": [],
        "controls": {"allow_fallback_boundary": False, "section_geometry": "rectangular"},
        "provenance": {"engine_version": "test"},
    }


def test_y_confluence_mass_balance() -> None:
    """10+15 m³/s 汇流后必须形成 25 m³/s，节点归一化残差小于 1e-3。"""

    result = HydraulicEngine().run(make_y_network()).to_dict()
    junction_rows = [row for row in result["node_series"] if row["node_id"] == 3]
    assert all(row["inflow"] == pytest.approx(25.0) for row in junction_rows)
    assert all(row["outflow"] == pytest.approx(25.0) for row in junction_rows)
    assert result["diagnostics"]["maximum_normalized_node_residual"] <= 1.0e-3


def test_bifurcation_flow_split() -> None:
    """等长分流边应把 20 m³/s 稳定分为两个 10 m³/s 分支。"""

    result = HydraulicEngine().run(make_y_network(bifurcation=True)).to_dict()
    branch_flows = {
        row["river_id"]: row["flow"][0]
        for row in result["section_series"]
        if row["station"] == 0.0
    }
    assert branch_flows[2] == pytest.approx(10.0)
    assert branch_flows[3] == pytest.approx(10.0)


def test_network_boundary_mapping() -> None:
    """缺少任一外部源或出口边界时必须阻止正式计算。"""

    snapshot = make_y_network()
    snapshot["boundary_conditions"] = snapshot["boundary_conditions"][:-1]
    with pytest.raises(HydraulicInputError, match="缺少外边界"):
        HydraulicEngine().run(snapshot)


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "constant", "value": float("nan")},
        {"mode": "constant", "value": float("inf")},
        {"mode": "series", "times": [0.0, float("inf")], "values": [10.0, 10.0]},
        {"mode": "series", "times": [0.0, 600.0], "values": [10.0, float("-inf")]},
    ],
)
def test_network_boundary_numbers_must_be_finite(values: dict) -> None:
    """NaN and either infinity are invalid boundary facts, never solver inputs."""

    snapshot = make_y_network()
    snapshot["boundary_conditions"][0]["values"] = values

    with pytest.raises(HydraulicInputError, match="有限数值"):
        HydraulicEngine().run(snapshot)


def test_boundary_query_time_must_be_finite_but_constant_covers_all_finite_time() -> None:
    """A constant is all-domain only for a finite simulation time coordinate."""

    signal = BoundarySignal("upstream_flow", 1, (0.0,), (10.0,))

    assert signal.value_at(1.0e12) == 10.0
    with pytest.raises(HydraulicInputError, match="time_seconds"):
        signal.value_at(float("inf"))


def test_same_node_cannot_mix_flow_and_level_boundaries() -> None:
    """A node has one authoritative boundary type; a later type may not overwrite it."""

    snapshot = make_y_network()
    snapshot["boundary_conditions"].append({
        "boundary_type": "downstream_water_level",
        "target_node_id": 1,
        "values": {"mode": "constant", "value": 10.0},
    })

    with pytest.raises(HydraulicInputError, match="不能同时配置"):
        HydraulicEngine().run(snapshot)


@pytest.mark.parametrize(
    ("boundary_index", "wrong_type", "match"),
    [
        (0, "downstream_water_level", "source_requires_upstream_flow"),
        (-1, "upstream_flow", "sink_requires_downstream_water_level"),
    ],
)
def test_external_nodes_require_the_correct_boundary_type(
    boundary_index: int, wrong_type: str, match: str
) -> None:
    """Presence alone is insufficient: source/sink semantics must match the node role."""

    snapshot = make_y_network()
    snapshot["boundary_conditions"][boundary_index]["boundary_type"] = wrong_type

    with pytest.raises(HydraulicInputError, match=match):
        HydraulicEngine().run(snapshot)


@pytest.mark.parametrize("times", [[1.0, 600.0], [0.0, 599.0]])
def test_series_boundary_must_cover_the_complete_simulation_window(
    times: list[float],
) -> None:
    """Series interpolation may not silently clamp before its start or after its end."""

    snapshot = make_y_network()
    snapshot["boundary_conditions"][0]["values"] = {
        "mode": "series",
        "times": times,
        "values": [10.0, 10.0],
    }

    with pytest.raises(HydraulicInputError, match="必须覆盖求解时域"):
        HydraulicEngine().run(snapshot)


def test_network_determinism() -> None:
    """相同河网快照在连续执行时必须完全一致。"""

    snapshot = make_y_network()
    assert HydraulicEngine().run(copy.deepcopy(snapshot)).to_dict() == HydraulicEngine().run(
        copy.deepcopy(snapshot)
    ).to_dict()


def test_network_no_nan_and_aligned_time_axis() -> None:
    """所有断面与节点时间轴对齐且不含 NaN/Inf。"""

    result = HydraulicEngine().run(make_y_network()).to_dict()
    axis = result["diagnostics"]["time_axis"]
    assert all(row["time"] == axis for row in result["section_series"])
    assert len(result["node_series"]) == 4 * len(axis)
    for row in result["section_series"]:
        assert all(math.isfinite(value) for value in row["water_level"] + row["flow"] + row["velocity"])
