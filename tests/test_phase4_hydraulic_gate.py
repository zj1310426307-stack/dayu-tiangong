"""Phase 4.0 水动力正确性与可复现性硬门禁。"""

import copy
import math

import pytest

from model import HydraulicEngine
from model.core.errors import HydraulicInputError
from model.geometry import RectangularSectionGeometry, TabulatedSectionGeometry
from model.provenance import canonical_json, snapshot_hash

from tests.test_hydraulic_engine import make_snapshot


def test_lake_at_rest_over_variable_bed() -> None:
    """变床静水的最大流速和水位漂移必须都不超过 1e-4。"""

    snapshot = make_snapshot()
    beds = [8.7, 9.0, 9.3, 9.1, 8.8, 8.6]
    for row, bed in zip(snapshot["cross_sections"], beds):
        row["points"] = {"points": [[0.0, bed], [20.0, bed]]}
        row["elevation_min"] = bed
        row["roughness"] = 0.0
    snapshot["parameters"] = [
        {"parameter_name": "duration_seconds", "value": 600.0},
        {"parameter_name": "time_step", "value": 30.0},
        {"parameter_name": "output_interval", "value": 60.0},
        {"parameter_name": "cfl", "value": 0.75},
        {"parameter_name": "initial_water_level", "value": 10.0},
        {"parameter_name": "initial_flow", "value": 0.0},
        {"parameter_name": "minimum_depth", "value": 0.05},
    ]
    snapshot["boundary_conditions"][0]["values"] = {"mode": "constant", "value": 0.0}
    snapshot["boundary_conditions"][1]["values"] = {"mode": "constant", "value": 10.0}

    result = HydraulicEngine().run(snapshot).to_dict()
    velocities = [abs(value) for row in result["series"] for value in row["velocity"]]
    drifts = [abs(value - 10.0) for row in result["series"] for value in row["water_level"]]

    assert max(velocities) <= 1.0e-4
    assert max(drifts) <= 1.0e-4
    assert all(math.isfinite(value) for value in velocities + drifts)


def test_tabulated_geometry_is_monotonic_and_invertible() -> None:
    """非规则断面面积必须单调，面积反函数在查算范围内可复原水位。"""

    geometry = TabulatedSectionGeometry.from_points(
        [[0.0, 12.0], [4.0, 10.0], [8.0, 9.0], [13.0, 10.5], [18.0, 12.0]]
    )
    stages = [9.2, 10.0, 11.0, 11.8]
    areas = [geometry.area(stage) for stage in stages]

    assert areas == sorted(areas)
    assert [geometry.stage_from_area(area) for area in areas] == pytest.approx(
        stages, abs=1.0e-10
    )
    with pytest.raises(HydraulicInputError, match="超出断面查算范围"):
        geometry.area(12.1)


def test_rectangular_geometry_keeps_phase3_inverse() -> None:
    """矩形适配器继续保持 Phase 3 面积—水位精确反函数。"""

    geometry = RectangularSectionGeometry(width=20.0, bed_elevation=9.0)
    assert geometry.area(10.5) == pytest.approx(30.0)
    assert geometry.stage_from_area(30.0) == pytest.approx(10.5)


def test_two_section_river_is_explicitly_rejected() -> None:
    """两个断面没有内部控制体，不得返回看似成功的结果。"""

    snapshot = make_snapshot()
    snapshot["cross_sections"] = snapshot["cross_sections"][:2]
    with pytest.raises(HydraulicInputError, match="至少包含三个"):
        HydraulicEngine().run(snapshot)


def test_snapshot_hash_is_stable() -> None:
    """键顺序变化不应改变冻结快照的 SHA-256。"""

    snapshot = make_snapshot()
    reordered = {key: snapshot[key] for key in reversed(snapshot)}
    assert canonical_json(snapshot) == canonical_json(reordered)
    assert snapshot_hash(snapshot) == snapshot_hash(reordered)
    assert len(snapshot_hash(snapshot)) == 64


def test_same_snapshot_same_result() -> None:
    """相同快照和引擎版本必须产生确定性一致结果。"""

    snapshot = make_snapshot(flood=True)
    first = HydraulicEngine().run(copy.deepcopy(snapshot)).to_dict()
    second = HydraulicEngine().run(copy.deepcopy(snapshot)).to_dict()
    assert first == second


def test_duplicate_boundary_is_rejected() -> None:
    """同一外边界节点的重复同类型边界必须失败。"""

    snapshot = make_snapshot()
    snapshot["boundary_conditions"].append(copy.deepcopy(snapshot["boundary_conditions"][0]))
    with pytest.raises(HydraulicInputError, match="重复流量边界"):
        HydraulicEngine().run(snapshot)
