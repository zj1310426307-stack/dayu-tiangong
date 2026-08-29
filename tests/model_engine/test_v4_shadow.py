"""Independent v3/v4 shadow readiness and diagnostic comparison semantics."""

from types import SimpleNamespace

import pytest

from app.model_engine import shadow
from app.model_engine.v4_schemas import V4ShadowCreate


class _AtomicSession:
    def __init__(self) -> None:
        self.pending: list[object] = []
        self.committed: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self._next_id = 100

    def add(self, entity) -> None:
        if getattr(entity, "id", None) is None:
            entity.id = self._next_id
            self._next_id += 1
        self.pending.append(entity)

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1
        self.committed.extend(self.pending)
        self.pending.clear()

    def rollback(self) -> None:
        self.rollback_count += 1
        self.pending.clear()


def _mark_both_builders_ready(monkeypatch) -> None:
    monkeypatch.setattr(shadow, "build_model_input_v3", lambda _session, _case: {"ready": True})
    monkeypatch.setattr(
        shadow,
        "assess_database_case",
        lambda *_args: SimpleNamespace(readiness=SimpleNamespace(ready=True, errors=[])),
    )


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
    monkeypatch.setattr(
        shadow.service, "build_task_entity", lambda *_args: created.append(object())
    )
    session = _AtomicSession()

    with pytest.raises(ValueError, match="shadow not_ready: v4"):
        shadow.create_shadow_pair(
            session, V4ShadowCreate(case_id=1, dispatch_plan_id=2)  # type: ignore[arg-type]
        )
    assert created == []
    assert session.committed == []
    assert session.rollback_count == 1


def test_shadow_creation_commits_group_and_both_tasks_once(monkeypatch) -> None:
    _mark_both_builders_ready(monkeypatch)
    session = _AtomicSession()
    built: list[tuple[object, object]] = []

    def build_task(current_session, payload):
        task = SimpleNamespace(
            id=None,
            comparison_group_id=None,
            group_role=None,
            execution_mode=None,
        )
        current_session.add(task)
        current_session.flush()
        built.append((payload, task))
        return task

    monkeypatch.setattr(shadow.service, "build_task_entity", build_task)
    pair = shadow.create_shadow_pair(
        session, V4ShadowCreate(case_id=1, dispatch_plan_id=2)  # type: ignore[arg-type]
    )

    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert len(session.committed) == 3
    assert pair.group_id == session.committed[0].id
    assert pair.v3_task_id == built[0][1].id
    assert pair.v4_task_id == built[1][1].id
    assert built[0][1].comparison_group_id == pair.group_id
    assert built[0][1].group_role == "legacy-v3"
    assert built[0][1].execution_mode == "shadow"
    assert built[1][1].comparison_group_id == pair.group_id
    assert built[1][1].group_role == "native-v4"


def test_shadow_creation_rolls_back_group_and_v3_when_v4_build_fails(monkeypatch) -> None:
    _mark_both_builders_ready(monkeypatch)
    session = _AtomicSession()
    build_count = 0

    def build_task(current_session, payload):
        nonlocal build_count
        build_count += 1
        if payload.input_schema_version == "dayu.model-input.v4":
            raise RuntimeError("injected v4 freeze failure")
        task = SimpleNamespace(
            id=None,
            comparison_group_id=None,
            group_role=None,
            execution_mode=None,
        )
        current_session.add(task)
        current_session.flush()
        return task

    monkeypatch.setattr(shadow.service, "build_task_entity", build_task)
    with pytest.raises(RuntimeError, match="injected v4 freeze failure"):
        shadow.create_shadow_pair(
            session, V4ShadowCreate(case_id=1, dispatch_plan_id=2)  # type: ignore[arg-type]
        )

    assert build_count == 2
    assert session.commit_count == 0
    assert session.rollback_count == 1
    assert session.pending == []
    assert session.committed == []


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _ComparisonSession:
    def __init__(self, legacy, native):
        self.result_sets = [legacy, native]
        self.commit_count = 0

    def scalars(self, _statement):
        return _ScalarRows(self.result_sets.pop(0))

    def commit(self):
        self.commit_count += 1


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
    assert group.status == "ready"
    assert session.commit_count == 1


@pytest.mark.parametrize(
    ("v3_status", "v4_status", "expected_status", "expected_commits"),
    [
        ("pending", "pending", "pending", 0),
        ("queued", "pending", "running", 1),
        ("success", "running", "running", 1),
        ("failed", "running", "failed", 1),
        ("cancelled", "pending", "cancelled", 1),
    ],
)
def test_shadow_comparison_updates_group_lifecycle(
    monkeypatch,
    v3_status: str,
    v4_status: str,
    expected_status: str,
    expected_commits: int,
) -> None:
    group = SimpleNamespace(id=9, status="pending")
    v3 = SimpleNamespace(id=31, status=v3_status)
    v4 = SimpleNamespace(id=32, status=v4_status)
    monkeypatch.setattr(shadow, "_tasks", lambda *_args: (group, v3, v4))
    session = _ComparisonSession([], [])

    comparison = shadow.compare_shadow_pair(session, 9)  # type: ignore[arg-type]

    assert comparison.status == expected_status
    assert group.status == expected_status
    assert session.commit_count == expected_commits


def test_shadow_comparison_marks_incomplete_group_failed(monkeypatch) -> None:
    group = SimpleNamespace(id=9, status="pending")
    v3 = SimpleNamespace(id=31, status="pending")
    monkeypatch.setattr(shadow, "_tasks", lambda *_args: (group, v3, None))
    session = _ComparisonSession([], [])

    comparison = shadow.compare_shadow_pair(session, 9)  # type: ignore[arg-type]

    assert comparison.status == "not_ready"
    assert group.status == "failed"
    assert session.commit_count == 1
