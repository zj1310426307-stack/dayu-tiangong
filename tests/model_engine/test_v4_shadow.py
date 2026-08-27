"""Independent v3/v4 shadow readiness and diagnostic comparison semantics."""

from types import SimpleNamespace

import pytest

from app.model_engine import shadow
from app.model_engine.v4_schemas import V4ShadowCreate


def test_shadow_not_ready_creates_no_tasks(monkeypatch) -> None:
    created: list[object] = []
    monkeypatch.setattr(shadow, "build_model_input_v3", lambda _session, _case: {"ready": True})
    monkeypatch.setattr(
        shadow,
        "assess_database_case",
        lambda *_args: SimpleNamespace(
            readiness=SimpleNamespace(
                ready=False,
                errors=[SimpleNamespace(code="D2_PUMP_CONTRACT_INCOMPLETE", message="missing")],
            )
        ),
    )
    monkeypatch.setattr(shadow.service, "create_task", lambda *_args: created.append(object()))

    with pytest.raises(ValueError, match="shadow not_ready: v4"):
        shadow.create_shadow_pair(
            object(), V4ShadowCreate(case_id=1, dispatch_plan_id=2)  # type: ignore[arg-type]
        )
    assert created == []


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _ComparisonSession:
    def __init__(self, legacy, native):
        self.result_sets = [legacy, native]
        self.committed = False

    def scalars(self, _statement):
        return _ScalarRows(self.result_sets.pop(0))

    def commit(self):
        self.committed = True


def test_shadow_comparison_uses_only_common_section_times(monkeypatch) -> None:
    group = SimpleNamespace(id=9, status="pending")
    v3 = SimpleNamespace(id=31, status="success")
    v4 = SimpleNamespace(id=32, status="success")
    monkeypatch.setattr(shadow, "_tasks", lambda *_args: (group, v3, v4))
    legacy = [
        SimpleNamespace(section_code="S1", time_seconds=0.0, water_level=10.0, flow=1.0),
        SimpleNamespace(section_code="S1", time_seconds=60.0, water_level=10.1, flow=2.0),
    ]
    native = [
        SimpleNamespace(section_code="S1", time_seconds=0.0, water_level_m=10.05, flow_m3s=1.2),
        SimpleNamespace(section_code="S1", time_seconds=60.0, water_level_m=10.08, flow_m3s=2.3),
        SimpleNamespace(section_code="S1", time_seconds=120.0, water_level_m=10.0, flow_m3s=1.0),
    ]
    session = _ComparisonSession(legacy, native)
    comparison = shadow.compare_shadow_pair(session, 9)  # type: ignore[arg-type]
    assert comparison.status == "ready"
    assert comparison.sections[0].time_seconds == [0.0, 60.0]
    assert comparison.sections[0].water_level_delta_m == pytest.approx([0.05, -0.02])
    assert "not truth" in comparison.diagnostic_disclaimer
    assert session.committed
