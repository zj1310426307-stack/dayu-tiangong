"""Unified one-dimensional engine abstraction used by platform services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[float, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class Hydraulic1DExecutionContext:
    """Carry job-scoped runtime controls without coupling engines to Celery or HTTP."""

    job_id: str
    workspace_root: Path | None = None
    cancel_check: CancelCheck | None = None
    progress_callback: ProgressCallback | None = None


class Hydraulic1DEngine(ABC):
    """Define the sole production boundary for present and future 1D engines."""

    @property
    @abstractmethod
    def engine_id(self) -> str:
        """Return the stable machine identifier persisted with every result."""

    @property
    @abstractmethod
    def engine_version(self) -> str:
        """Return the verified external-engine version targeted by this adapter."""

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """Return factual runtime availability without performing a simulation."""

    @abstractmethod
    def runtime_provenance(self) -> dict[str, object]:
        """Return structured runtime identity without performing a simulation."""

    @abstractmethod
    def validate(self, model: Hydraulic1DModel) -> None:
        """Fail closed when the selected engine cannot represent the Dayu model."""

    @abstractmethod
    def run(
        self,
        model: Hydraulic1DModel,
        context: Hydraulic1DExecutionContext,
    ) -> HydraulicResult:
        """Execute a real external runtime and return only the unified result."""
