"""Dynamic Q/H boundary series with an explicit no-extrapolation contract."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Literal

from model.solver.finite_volume.diagnostics import BoundaryCoverageError
from model.solver.finite_volume.flux import ConservedVector
from model.solver.finite_volume.mesh import FiniteVolumeCell

_TIME_TOLERANCE = 1.0e-9


@dataclass(frozen=True)
class BoundarySeries:
    """Store a finite, strictly ordered, piecewise-linear boundary process."""

    times: tuple[float, ...]
    values: tuple[float, ...]
    variable: Literal["discharge", "stage"]

    def __post_init__(self) -> None:
        """Validate the full interpolation domain before time integration."""

        object.__setattr__(self, "times", tuple(float(item) for item in self.times))
        object.__setattr__(self, "values", tuple(float(item) for item in self.values))
        if len(self.times) != len(self.values) or not self.times:
            raise ValueError("boundary times and values must have the same non-zero length")
        if any(not math.isfinite(item) for item in (*self.times, *self.values)):
            raise ValueError("boundary series must contain only finite values")
        if any(right <= left for left, right in zip(self.times, self.times[1:])):
            raise ValueError("boundary times must be strictly increasing")

    @property
    def start_time(self) -> float:
        """Return the first time at which interpolation is defined."""

        return self.times[0]

    @property
    def end_time(self) -> float:
        """Return the final time at which interpolation is defined."""

        return self.times[-1]

    def value_at(self, time: float) -> float:
        """Interpolate inside the closed domain and reject all extrapolation."""

        if not math.isfinite(time):
            raise BoundaryCoverageError("boundary evaluation time must be finite")
        if time < self.start_time - _TIME_TOLERANCE or time > self.end_time + _TIME_TOLERANCE:
            raise BoundaryCoverageError(
                f"{self.variable} boundary time {time} is outside "
                f"[{self.start_time}, {self.end_time}]"
            )
        if time <= self.start_time + _TIME_TOLERANCE:
            return self.values[0]
        if time >= self.end_time - _TIME_TOLERANCE:
            return self.values[-1]
        right = bisect.bisect_right(self.times, time)
        left = right - 1
        ratio = (time - self.times[left]) / (self.times[right] - self.times[left])
        return self.values[left] + ratio * (self.values[right] - self.values[left])

    def validate_coverage(self, start_time: float, end_time: float) -> None:
        """Fail preflight when a requested run would need extrapolation."""

        if end_time < start_time:
            raise ValueError("boundary coverage end_time must not precede start_time")
        self.value_at(start_time)
        self.value_at(end_time)

    def next_breakpoint_after(self, time: float) -> float | None:
        """Return the next series knot so a time step can land on it exactly."""

        index = bisect.bisect_right(self.times, time + _TIME_TOLERANCE)
        return self.times[index] if index < len(self.times) else None


@dataclass(frozen=True)
class UpstreamDischargeBoundary:
    """Prescribe upstream Q while retaining the interior companion stage."""

    series: BoundarySeries

    def __post_init__(self) -> None:
        """Prevent accidental binding of an H series to a Q boundary."""

        if self.series.variable != "discharge":
            raise ValueError("upstream discharge boundary requires a discharge series")

    def ghost_state(
        self,
        *,
        time: float,
        interior: ConservedVector,
        cell: FiniteVolumeCell,
    ) -> ConservedVector:
        """Build the MVP ghost state using interior stage and prescribed Q.

        This is a documented subcritical MVP closure, not the future complete
        characteristic boundary solver.
        """

        del cell
        return ConservedVector(interior.area, self.series.value_at(time))


@dataclass(frozen=True)
class DownstreamStageBoundary:
    """Prescribe downstream absolute H while retaining companion discharge."""

    series: BoundarySeries

    def __post_init__(self) -> None:
        """Prevent accidental binding of a Q series to an H boundary."""

        if self.series.variable != "stage":
            raise ValueError("downstream stage boundary requires a stage series")

    def ghost_state(
        self,
        *,
        time: float,
        interior: ConservedVector,
        cell: FiniteVolumeCell,
    ) -> ConservedVector:
        """Build the MVP ghost state using prescribed H and interior Q."""

        stage = self.series.value_at(time)
        area = float(cell.geometry.area(stage))
        return ConservedVector(area, interior.discharge if area > 1.0e-12 else 0.0)


@dataclass(frozen=True)
class BoundaryPair:
    """Bind the two MVP open boundaries and coordinate their time domains."""

    upstream: UpstreamDischargeBoundary
    downstream: DownstreamStageBoundary

    def validate_coverage(self, start_time: float, end_time: float) -> None:
        """Require both Q and H to cover the complete requested run."""

        self.upstream.series.validate_coverage(start_time, end_time)
        self.downstream.series.validate_coverage(start_time, end_time)

    def next_breakpoint_after(self, time: float) -> float | None:
        """Return the earliest future knot across upstream and downstream data."""

        candidates = (
            self.upstream.series.next_breakpoint_after(time),
            self.downstream.series.next_breakpoint_after(time),
        )
        available = [item for item in candidates if item is not None]
        return min(available) if available else None
