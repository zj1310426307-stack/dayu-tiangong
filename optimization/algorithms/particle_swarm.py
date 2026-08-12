"""Deterministic particle swarm optimization for dispatch-plan search."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from random import Random
from typing import Callable, Sequence


@dataclass(frozen=True)
class ParticleEvaluation:
    """Record one objective evaluation with its generation and particle index."""

    generation: int
    candidate_index: int
    vector: tuple[float, ...]
    score: float


class ParticleSwarmOptimizer:
    """Minimize an objective within box bounds using seeded PSO."""

    def __init__(
        self,
        bounds: Sequence[tuple[float, float]],
        *,
        particle_count: int = 12,
        max_iterations: int = 20,
        inertia: float = 0.65,
        cognitive: float = 1.4,
        social: float = 1.4,
        tolerance: float = 1e-4,
        patience: int = 4,
        seed: int = 42,
    ) -> None:
        """Validate and retain deterministic optimizer parameters."""

        if not bounds or any(low > high for low, high in bounds):
            raise ValueError("bounds must contain ordered (low, high) pairs")
        if particle_count < 2 or max_iterations < 1:
            raise ValueError("particle_count >= 2 and max_iterations >= 1 are required")
        self.bounds = tuple((float(low), float(high)) for low, high in bounds)
        self.particle_count = particle_count
        self.max_iterations = max_iterations
        self.inertia = inertia
        self.cognitive = cognitive
        self.social = social
        self.tolerance = max(0.0, tolerance)
        self.patience = max(1, patience)
        self.random = Random(seed)
        self.evaluations: list[ParticleEvaluation] = []
        self.iterations_completed = 0
        self.converged = False

    def optimize(
        self,
        objective: Callable[[tuple[float, ...], int, int], float],
        *,
        should_cancel: Callable[[], bool] | None = None,
        on_generation: Callable[[int, float], None] | None = None,
    ) -> tuple[tuple[float, ...], float]:
        """Evaluate particles, update swarm state and return the best solution."""

        dimensions = len(self.bounds)
        positions = [
            [self.random.uniform(low, high) for low, high in self.bounds]
            for _ in range(self.particle_count)
        ]
        velocities = [
            [self.random.uniform(-(high - low), high - low) * 0.1 for low, high in self.bounds]
            for _ in range(self.particle_count)
        ]
        personal_positions = [position[:] for position in positions]
        personal_scores = [inf] * self.particle_count
        global_position = tuple(positions[0])
        global_score = inf
        stable_generations = 0

        for generation in range(1, self.max_iterations + 1):
            if should_cancel and should_cancel():
                break
            previous_best = global_score
            for index, position in enumerate(positions):
                vector = tuple(position)
                score = float(objective(vector, generation, index))
                self.evaluations.append(ParticleEvaluation(generation, index, vector, score))
                if score < personal_scores[index]:
                    personal_scores[index] = score
                    personal_positions[index] = position[:]
                if score < global_score:
                    global_score = score
                    global_position = vector
            self.iterations_completed = generation
            if on_generation:
                on_generation(generation, global_score)
            improvement = previous_best - global_score
            stable_generations = stable_generations + 1 if improvement <= self.tolerance else 0
            if stable_generations >= self.patience:
                self.converged = True
                break
            for index in range(self.particle_count):
                for dimension in range(dimensions):
                    r1, r2 = self.random.random(), self.random.random()
                    velocity = (
                        self.inertia * velocities[index][dimension]
                        + self.cognitive
                        * r1
                        * (personal_positions[index][dimension] - positions[index][dimension])
                        + self.social
                        * r2
                        * (global_position[dimension] - positions[index][dimension])
                    )
                    low, high = self.bounds[dimension]
                    velocities[index][dimension] = velocity
                    positions[index][dimension] = min(
                        high, max(low, positions[index][dimension] + velocity)
                    )
        return global_position, global_score
