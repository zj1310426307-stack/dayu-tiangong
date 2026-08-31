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


class Hydraulic1DExecutionError(Hydraulic1DError):
    """Report a non-zero, timed-out, cancelled, or incomplete engine process."""


class Hydraulic1DCancelled(Hydraulic1DExecutionError):
    """Report cooperative cancellation after the external process is terminated."""


class Hydraulic1DResultError(Hydraulic1DError, ValueError):
    """Reject malformed or incomplete external-engine output without inventing values."""
