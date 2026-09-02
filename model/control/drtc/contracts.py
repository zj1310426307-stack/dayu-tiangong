"""Immutable reporting contracts for D-RTC rule compilation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class DRTCRuleCompileRecord(BaseModel):
    """Explain exactly why one Dayu rule is or is not representable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: int | None
    status: Literal["COMPILED", "UNSUPPORTED"]
    source_semantics: dict[str, object]
    target_semantics: dict[str, object] | None
    compiled_component: str | None
    warnings: tuple[str, ...] = ()
    unsupported_reason: str | None = None


class DRTCCompileReport(BaseModel):
    """Return a deterministic whole-program D-RTC compiler decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compiler_version: str
    pinned_runtime_tag: Literal["DIMRset_2026.02"] = "DIMRset_2026.02"
    status: Literal["COMPILED", "UNSUPPORTED"]
    rules: tuple[DRTCRuleCompileRecord, ...]
    artifact_hash: str
    runtime_validated: bool
