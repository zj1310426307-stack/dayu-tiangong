"""Compatibility entry point for the Phase 5 particle swarm optimizer."""

from collections.abc import Mapping
from typing import Any

from optimization.algorithms.particle_swarm import ParticleSwarmOptimizer


class SchedulerOptimizer:
    """Retain the Phase 0 placeholder contract while Phase 5 uses typed PSO directly."""

    def optimize(self, data: Mapping[str, Any]) -> dict[str, list[Any] | float | None]:
        """Validate legacy mapping input and return the historical empty result."""

        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")
        return {"scheme": [], "score": None}

__all__ = ["ParticleSwarmOptimizer", "SchedulerOptimizer"]
