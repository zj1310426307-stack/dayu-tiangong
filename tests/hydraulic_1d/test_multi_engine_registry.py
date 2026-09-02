"""Verify additive multi-engine registration without changing MASCARET tasks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import model.hydraulic_1d.factory as factory_module
from model.hydraulic_1d.capabilities import (
    CapabilityExecutionPolicy,
    CapabilityStatus,
    capabilities_for,
    capability_status_allowed,
    compatibility_report,
)
from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult
from model.hydraulic_1d.engine import Hydraulic1DEngine, Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import (
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.factory import create_hydraulic_1d_engine
from model.hydraulic_1d.mascaret.engine import MascaretEngine
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DFLOW_FM_ADAPTER_ID,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
    DFLOW_FM_UPSTREAM_COMMIT,
    engine_catalog_hash,
    engine_catalog_payload,
    engine_registry_payload,
    registry_hash,
    selected_engine_hash,
    task_engine_provenance,
)
from tests.hydraulic_1d.helpers import model_fixture


LEGACY_REGISTRY_HASH = (
    "5df095a1ef2eb681b4c306a9a156de71c59528451fe3ad3d8400384a37ff8d69"
)


class _FakeDFlowEngine(Hydraulic1DEngine):
    """Provide a protocol-complete fake for factory import-boundary tests."""

    @property
    def engine_id(self) -> str:
        """Return the registered engine ID."""

        return DFLOW_FM_ENGINE_ID

    @property
    def engine_version(self) -> str:
        """Return the pinned D-Flow FM version."""

        return DFLOW_FM_ENGINE_VERSION

    def availability(self) -> tuple[bool, str]:
        """Report fake availability without executing a runtime."""

        return True, "test fake"

    def runtime_provenance(self) -> dict[str, object]:
        """Return a deliberately minimal fake identity."""

        return {"engine": self.engine_id, "version": self.engine_version}

    def validate(self, model: Hydraulic1DModel) -> None:
        """Accept the model only for this import-boundary test."""

    def run(
        self,
        model: Hydraulic1DModel,
        context: Hydraulic1DExecutionContext,
    ) -> HydraulicResult:
        """Never execute from a factory unit test."""

        raise AssertionError("fake D-Flow engine must not run")


def test_legacy_registry_and_task_provenance_are_byte_stable() -> None:
    """Keep already persisted MASCARET task identity unchanged by the new catalog."""

    legacy = engine_registry_payload()
    assert legacy["reserved"] == ["d-flow-fm"]
    assert registry_hash() == LEGACY_REGISTRY_HASH
    assert task_engine_provenance() == {
        "solver_id": "mascaret-v9.1.1",
        "capability_id": "engineering-1d-mascaret-v2",
        "runtime_adapter_id": "dayu-mascaret-adapter-v2",
        "result_schema_version": "dayu.hydraulic-result.v1",
        "registry_hash": LEGACY_REGISTRY_HASH,
    }


def test_additive_catalog_registers_pinned_dflow_without_production_claims() -> None:
    """Expose experimental D-Flow capabilities without a production claim."""

    catalog = engine_catalog_payload()
    assert catalog["default_engine_id"] == DEFAULT_HYDRAULIC_1D_ENGINE_ID
    rows = {item["engine_id"]: item for item in catalog["engines"]}
    assert set(rows) == {"mascaret", DFLOW_FM_ENGINE_ID}

    dflow = rows[DFLOW_FM_ENGINE_ID]
    assert dflow["engine_version"] == "DIMRset_2026.02"
    assert dflow["adapter_id"] == DFLOW_FM_ADAPTER_ID
    assert dflow["upstream_tag"] == "DIMRset_2026.02"
    assert dflow["upstream_commit"] == DFLOW_FM_UPSTREAM_COMMIT
    assert dflow["runtime_modes"] == ("external", "container")
    assert dflow["production_eligible"] is False
    assert dflow["license"]["review_required"] is True
    assert dflow["capabilities"]
    capability_status = {
        item["feature"]: item["status"] for item in dflow["capabilities"]
    }
    assert capability_status["UNSTEADY_1D"] == "EXPERIMENTAL"
    assert capability_status["GATE"] == "EXPERIMENTAL"
    assert capability_status["PUMP"] == "EXPERIMENTAL"
    assert capability_status["DYNAMIC_CONTROL"] == "EXPERIMENTAL"
    assert capability_status["D_RTC"] == "UNVERIFIED"
    assert "VERIFIED_NATIVE" not in capability_status.values()
    assert "VERIFIED_EQUIVALENT" not in capability_status.values()

    assert engine_catalog_hash() != LEGACY_REGISTRY_HASH
    assert selected_engine_hash("mascaret") != selected_engine_hash(DFLOW_FM_ENGINE_ID)


def test_mascaret_gate_pump_and_development_policy_remain_fail_closed() -> None:
    """Allow experimental development only while production stays fail closed."""

    mascaret = {item.feature: item for item in capabilities_for("mascaret", "v9.1.1")}
    assert mascaret["GATE"].status == CapabilityStatus.UNSUPPORTED
    assert mascaret["PUMP"].status == CapabilityStatus.UNSUPPORTED

    assert capability_status_allowed(
        CapabilityStatus.EXPERIMENTAL,
        execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
        development_mode=True,
        production_mode=False,
    )
    assert not capability_status_allowed(
        CapabilityStatus.EXPERIMENTAL,
        execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
        development_mode=True,
        production_mode=True,
    )
    assert not capability_status_allowed(
        CapabilityStatus.UNVERIFIED,
        execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
        development_mode=True,
        production_mode=False,
    )

    development_report = compatibility_report(
        model_fixture(),
        engine=DFLOW_FM_ENGINE_ID,
        engine_version=DFLOW_FM_ENGINE_VERSION,
        execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
        development_mode=True,
        production_mode=False,
    )
    assert development_report["compatible"] is True
    assert development_report["issues"] == []

    production_report = compatibility_report(
        model_fixture(),
        engine=DFLOW_FM_ENGINE_ID,
        engine_version=DFLOW_FM_ENGINE_VERSION,
    )
    assert production_report["compatible"] is False
    assert production_report["issues"][0]["status"] == "EXPERIMENTAL"


def test_factory_keeps_default_mascaret_and_imports_dflow_only_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent default tasks from importing or silently selecting D-Flow FM."""

    def unexpected_import(_name: str) -> object:
        raise AssertionError("D-Flow import must be lazy")

    monkeypatch.setattr(factory_module, "import_module", unexpected_import)
    assert isinstance(create_hydraulic_1d_engine(), MascaretEngine)
    assert isinstance(create_hydraulic_1d_engine("mascaret"), MascaretEngine)

    monkeypatch.setattr(
        factory_module,
        "import_module",
        lambda name: SimpleNamespace(DFlowFMEngine=_FakeDFlowEngine),
    )
    assert isinstance(create_hydraulic_1d_engine(DFLOW_FM_ENGINE_ID), _FakeDFlowEngine)


def test_factory_fails_closed_for_missing_or_unknown_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return stable diagnostics rather than falling back to MASCARET."""

    def missing_adapter(_name: str) -> object:
        raise ModuleNotFoundError("no D-Flow adapter")

    monkeypatch.setattr(factory_module, "import_module", missing_adapter)
    with pytest.raises(Hydraulic1DRuntimeUnavailable) as missing:
        create_hydraulic_1d_engine(DFLOW_FM_ENGINE_ID)
    assert missing.value.code == "DFLOW_FM_ADAPTER_UNAVAILABLE"

    with pytest.raises(Hydraulic1DValidationError) as unknown:
        create_hydraulic_1d_engine("unknown-engine")
    assert unknown.value.code == "HYDRAULIC_ENGINE_NOT_REGISTERED"
