"""Focused contracts for governance maintenance in the idempotent DEMO seed."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from database.seed import demo_data


class _ScalarResult:
    """Return a stable list through SQLAlchemy's ``scalars().all()`` shape."""

    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


def test_governance_backfill_covers_all_frozen_versions_without_core_writes(
    monkeypatch,
) -> None:
    """Hash every frozen generation and add audits only for missing publications."""

    approved = SimpleNamespace(id=2, content_hash=None)
    published = SimpleNamespace(
        id=3,
        content_hash=None,
        published_at=None,
        created_time=None,
    )
    retired = SimpleNamespace(id=4, content_hash=None)
    session = MagicMock()
    session.scalars.side_effect = [
        _ScalarResult([approved, published, retired]),
        _ScalarResult([published]),
    ]
    monkeypatch.setattr(
        demo_data,
        "_core_content_rows",
        lambda _session, version_id: [{"entity_type": "river", "version": version_id}],
    )
    monkeypatch.setattr(
        demo_data,
        "canonical_sha256",
        lambda rows: f"hash-{rows[0]['version']}",
    )

    demo_data._backfill_governance_metadata(session)

    assert approved.content_hash == "hash-2"
    assert published.content_hash == "hash-3"
    assert retired.content_hash == "hash-4"
    session.add.assert_called_once()
    publication = session.add.call_args.args[0]
    assert publication.dataset_version_id == published.id
    assert publication.publication_status == "published"
    assert publication.manifest_json["legacy_backfill"] is True


def test_seed_always_runs_builtin_knowledge_after_frozen_fast_path(monkeypatch) -> None:
    """Keep Phase 6 knowledge seeding reachable when V1 is already published."""

    monkeypatch.setattr(demo_data, "_seed_demo_data_rows", lambda: {"rivers": 3})
    knowledge_calls: list[object] = []
    monkeypatch.setattr(
        demo_data,
        "seed_builtin_knowledge",
        lambda session: knowledge_calls.append(session),
    )

    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(demo_data, "SessionLocal", fake_session)

    assert demo_data.seed_demo_data() == {"rivers": 3}
    assert len(knowledge_calls) == 1
