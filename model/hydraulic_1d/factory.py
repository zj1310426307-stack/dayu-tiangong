"""Engine-neutral factory used by backend workers and command-line entry points."""

from __future__ import annotations

from model.hydraulic_1d.engine import Hydraulic1DEngine
from model.hydraulic_1d.mascaret.engine import MascaretEngine


def create_hydraulic_1d_engine() -> Hydraulic1DEngine:
    """Return the sole configured production 1D engine behind its public protocol."""

    return MascaretEngine()
