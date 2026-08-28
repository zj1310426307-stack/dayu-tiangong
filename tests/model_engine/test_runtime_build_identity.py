"""RC2 deterministic runtime build identity and fail-closed execution gates."""

from __future__ import annotations

import pytest

from model.build_identity import (
    BUILD_IDENTITY_SCHEMA,
    DEVELOPMENT_COMMIT_SENTINEL,
    BuildIdentityError,
    RuntimeBuildMismatchError,
    assert_runtime_build_matches,
    current_runtime_build_identity,
    runtime_build_diagnostic,
)
from model.solver.registry import registry_hash


COMMIT = "a" * 40


def test_ci_identity_is_deterministic_and_verified() -> None:
    environment = {
        "ENGINE_COMMIT": COMMIT,
        "DAYU_BUILD_MODE": "ci",
        "DAYU_ENGINE_VERSION": "dayu-hydraulic-4.0.0",
    }
    first = current_runtime_build_identity(environment)
    second = current_runtime_build_identity(dict(environment))
    assert first == second
    assert first.verified is True
    assert first.provenance()["build_identity_schema"] == BUILD_IDENTITY_SCHEMA
    assert first.provenance()["build_verified"] is True


@pytest.mark.parametrize("mode", ["ci", "release"])
@pytest.mark.parametrize("commit", ["workspace-uncommitted", "A" * 40])
def test_shipping_modes_reject_missing_or_mutable_commit(
    mode: str,
    commit: str,
) -> None:
    with pytest.raises(BuildIdentityError, match="lowercase 40-character Git SHA"):
        current_runtime_build_identity(
            {"ENGINE_COMMIT": commit, "DAYU_BUILD_MODE": mode}
        )


def test_development_mode_uses_explicit_unverified_sentinel() -> None:
    identity = current_runtime_build_identity({"DAYU_BUILD_MODE": "development"})
    assert identity.engine_commit == DEVELOPMENT_COMMIT_SENTINEL
    assert identity.verified is False
    assert identity.provenance()["unverified_build"] is True


def test_development_mode_never_claims_release_verification() -> None:
    identity = current_runtime_build_identity(
        {"DAYU_BUILD_MODE": "development", "ENGINE_COMMIT": COMMIT}
    )
    assert identity.engine_commit == COMMIT
    assert identity.verified is False


def test_hosted_diagnostic_exposes_release_environment_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENGINE_COMMIT", COMMIT)
    monkeypatch.setenv("DAYU_BUILD_MODE", "ci")
    diagnostic = runtime_build_diagnostic()
    assert diagnostic["engine_commit"] == COMMIT
    assert diagnostic["verified"] is True
    assert diagnostic["registry_hash"] == registry_hash()
    assert isinstance(diagnostic["python_version"], str)
    assert isinstance(diagnostic["platform"], str)


def test_worker_match_rejects_any_frozen_build_drift() -> None:
    identity = current_runtime_build_identity(
        {"ENGINE_COMMIT": COMMIT, "DAYU_BUILD_MODE": "ci"}
    )
    assert (
        assert_runtime_build_matches(
            expected_engine_version=identity.engine_version,
            expected_engine_commit=identity.engine_commit,
            expected_solver_build_id=identity.solver_build_id,
            expected_build_mode=identity.build_mode,
            expected_verified=identity.verified,
            expected_registry_hash=registry_hash(),
            actual=identity,
        )
        is identity
    )
    with pytest.raises(RuntimeBuildMismatchError, match="D2_RUNTIME_BUILD_MISMATCH"):
        assert_runtime_build_matches(
            expected_engine_version=identity.engine_version,
            expected_engine_commit="b" * 40,
            expected_solver_build_id=identity.solver_build_id,
            expected_build_mode=identity.build_mode,
            expected_verified=identity.verified,
            expected_registry_hash=registry_hash(),
            actual=identity,
        )
