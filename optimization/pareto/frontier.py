"""Deterministic non-dominated sorting for minimization objectives."""

from __future__ import annotations

from typing import Sequence


def _dominates(left: Sequence[float], right: Sequence[float]) -> bool:
    """Return whether left is no worse everywhere and better somewhere."""

    return all(a <= b for a, b in zip(left, right, strict=True)) and any(
        a < b for a, b in zip(left, right, strict=True)
    )


def non_dominated_sort(vectors: Sequence[Sequence[float]]) -> list[int]:
    """Assign one-based Pareto levels in the same order as input vectors."""

    remaining = set(range(len(vectors)))
    levels = [0] * len(vectors)
    level = 1
    while remaining:
        front = [
            index
            for index in sorted(remaining)
            if not any(
                other != index and _dominates(vectors[other], vectors[index])
                for other in remaining
            )
        ]
        if not front:
            front = [min(remaining)]
        for index in front:
            levels[index] = level
            remaining.remove(index)
        level += 1
    return levels
