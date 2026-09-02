"""Stable error taxonomy for external one-dimensional hydraulic engines."""

from __future__ import annotations


class Hydraulic1DError(RuntimeError):
    """Base failure raised by the unified one-dimensional engine boundary."""


class Hydraulic1DValidationError(Hydraulic1DError, ValueError):
    """Reject an input that cannot be represented faithfully by the selected engine."""

    def __init__(self, code: str, message: str, *, field_path: str = "") -> None:
        """Preserve a machine-readable code and an actionable model field path."""

        self.code = code
        self.field_path = field_path
        detail = f"{code}: {message}"
        if field_path:
            detail += f" [{field_path}]"
        super().__init__(detail)


class Hydraulic1DRuntimeUnavailable(Hydraulic1DError):
    """Report that a real external engine is not installed or not enabled."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "MASCARET_RUNTIME_NOT_FOUND",
    ) -> None:
        """Attach the stable fail-closed code used by workers and API diagnostics."""

        self.code = code
        super().__init__(f"{code}: {message}")


class Hydraulic1DExecutionError(Hydraulic1DError):
    """Report a non-zero, timed-out, cancelled, or incomplete engine process."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "MASCARET_PROCESS_FAILED",
    ) -> None:
        """Preserve a machine-readable failure reason across process boundaries."""

        self.code = code
        super().__init__(f"{code}: {message}")


class Hydraulic1DCancelled(Hydraulic1DExecutionError):
    """Report cooperative cancellation after the external process is terminated."""

    def __init__(self, message: str, *, code: str = "MASCARET_CANCELLED") -> None:
        """Distinguish a confirmed cooperative cancellation from a process failure."""

        super().__init__(message, code=code)


class Hydraulic1DTimeout(Hydraulic1DExecutionError):
    """Report that the owned runtime was terminated after its configured deadline."""

    def __init__(self, message: str) -> None:
        """Expose a stable timeout code to task persistence and metrics."""

        super().__init__(message, code="MASCARET_TIMEOUT")


class Hydraulic1DResultError(Hydraulic1DError, ValueError):
    """Reject malformed or incomplete external-engine output without inventing values."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "MASCARET_RESULT_INVALID",
    ) -> None:
        """Keep result rejection machine-readable without weakening legacy messages."""

        self.code = code
        super().__init__(f"{code}: {message}")
