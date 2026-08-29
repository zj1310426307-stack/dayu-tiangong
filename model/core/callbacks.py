"""Side-effect-free callback helpers shared by hydraulic runtime checkpoints."""

from __future__ import annotations

from typing import Any

from model.core.errors import HydraulicCancelledError


def check_cancellation(cancel_check: Any | None, checkpoint: str) -> None:
    """Raise the established cooperative-cancellation error at a safe checkpoint."""

    if callable(cancel_check) and bool(cancel_check()):
        raise HydraulicCancelledError(f"hydraulic task cancelled at {checkpoint}")


__all__ = ["check_cancellation"]
