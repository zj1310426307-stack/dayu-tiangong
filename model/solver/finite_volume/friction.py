"""Semi-implicit Manning friction for a cell-centred conserved state."""

from __future__ import annotations

import math
from dataclasses import dataclass

from model.solver.finite_volume.diagnostics import NumericalStateError
from model.solver.finite_volume.flux import GRAVITY
from model.solver.finite_volume.mesh import FiniteVolumeMesh, SectionGeometryLike

_EPSILON = 1.0e-12


class ManningEvidenceContractError(RuntimeError):
    """Signal an internal evidence invariant failure that must never be retried."""


@dataclass(frozen=True)
class ManningCellStageEvidence:
    """Record one independently reproducible semi-implicit friction update.

    ``discharge_before`` is the post-flux/source Euler value consumed by the
    Manning source.  Friction number ``mu=dt*k*abs(Q*)`` exposes the temporal
    strength of this split source update without relabelling it as a proven
    globally second-order IMEX discretisation.
    """

    cell_id: str
    area: float
    discharge_before: float
    discharge_after: float
    manning_n: float
    hydraulic_radius: float
    coefficient: float
    friction_number: float
    denominator: float
    dt: float
    gravity: float = GRAVITY
    policy: str = "semi-implicit-manning-stage-v1"

    def __post_init__(self) -> None:
        """Reject evidence that cannot reproduce the accepted stage formula."""

        if not self.cell_id:
            raise ManningEvidenceContractError(
                "Manning stage evidence cell_id must not be empty"
            )
        values = (
            self.area,
            self.discharge_before,
            self.discharge_after,
            self.manning_n,
            self.hydraulic_radius,
            self.coefficient,
            self.friction_number,
            self.denominator,
            self.dt,
            self.gravity,
        )
        if not all(math.isfinite(value) for value in values):
            raise ManningEvidenceContractError(
                "Manning stage evidence values must be finite"
            )
        if self.area < 0.0 or self.manning_n < 0.0:
            raise ManningEvidenceContractError(
                "Manning stage evidence requires A>=0 and n>=0"
            )
        if self.dt <= 0.0 or self.gravity <= 0.0:
            raise ManningEvidenceContractError(
                "Manning stage evidence requires positive dt and gravity"
            )
        if min(
            self.hydraulic_radius,
            self.coefficient,
            self.friction_number,
        ) < 0.0:
            raise ManningEvidenceContractError(
                "Manning stage evidence metrics must be non-negative"
            )
        if self.denominator < 1.0:
            raise ManningEvidenceContractError(
                "Manning stage denominator must be at least one"
            )
        if self.policy != "semi-implicit-manning-stage-v1":
            raise ManningEvidenceContractError(
                "unsupported Manning stage evidence policy"
            )

        inactive = (
            self.area <= _EPSILON
            or self.manning_n == 0.0
            or self.discharge_before == 0.0
        )
        if inactive:
            if self.area <= _EPSILON and abs(self.discharge_before) > _EPSILON:
                raise ManningEvidenceContractError(
                    "dry Manning evidence cannot carry discharge"
                )
            if not all(
                value == 0.0
                for value in (
                    self.hydraulic_radius,
                    self.coefficient,
                    self.friction_number,
                )
            ):
                raise ManningEvidenceContractError(
                    "inactive Manning evidence must have zero metrics"
                )
            if self.denominator != 1.0:
                raise ManningEvidenceContractError(
                    "inactive Manning evidence denominator must be one"
                )
        else:
            if self.hydraulic_radius <= 0.0:
                raise ManningEvidenceContractError(
                    "active Manning evidence requires positive radius"
                )
            expected_coefficient = (
                self.gravity
                * self.manning_n
                * self.manning_n
                / (self.area * self.hydraulic_radius ** (4.0 / 3.0))
            )
            expected_friction_number = (
                self.dt * expected_coefficient * abs(self.discharge_before)
            )
            if not math.isclose(
                self.coefficient,
                expected_coefficient,
                rel_tol=1.0e-12,
                abs_tol=1.0e-15,
            ):
                raise ManningEvidenceContractError(
                    "Manning stage coefficient is inconsistent"
                )
            if not math.isclose(
                self.friction_number,
                expected_friction_number,
                rel_tol=1.0e-12,
                abs_tol=1.0e-15,
            ):
                raise ManningEvidenceContractError(
                    "Manning stage friction number is inconsistent"
                )
            if not math.isclose(
                self.denominator,
                1.0 + expected_friction_number,
                rel_tol=1.0e-12,
                abs_tol=1.0e-15,
            ):
                raise ManningEvidenceContractError(
                    "Manning stage denominator is inconsistent"
                )

        expected_after = self.discharge_before / self.denominator
        if not math.isclose(
            self.discharge_after,
            expected_after,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12 * max(abs(self.discharge_before), 1.0),
        ):
            raise ManningEvidenceContractError(
                "Manning stage discharge is inconsistent"
            )
        if self.discharge_after * self.discharge_before < 0.0:
            raise ManningEvidenceContractError(
                "Manning stage update must preserve discharge sign"
            )
        if abs(self.discharge_after) > abs(self.discharge_before) + 1.0e-12:
            raise ManningEvidenceContractError(
                "Manning stage update must not increase discharge magnitude"
            )

    @property
    def removed_discharge(self) -> float:
        """Return the signed stage-local momentum-variable decrement."""

        return self.discharge_before - self.discharge_after

    @property
    def normalized_equation_residual(self) -> float:
        """Return the independently checkable algebraic update residual."""

        numerator = abs(
            self.discharge_after * self.denominator - self.discharge_before
        )
        return numerator / max(abs(self.discharge_before), 1.0)


@dataclass(frozen=True, slots=True)
class ManningTimeStepEstimate:
    """Expose the accepted-state predictor limit and its controlling cell."""

    time_step: float
    limiting_cell: int | None


def estimate_manning_time_step(
    *,
    mesh: FiniteVolumeMesh,
    area: tuple[float, ...],
    discharge: tuple[float, ...],
    maximum_friction_number: float,
) -> ManningTimeStepEstimate:
    """Predict ``max_mu/(k*abs(Q))`` from the current accepted state."""

    if (
        not math.isfinite(maximum_friction_number)
        or maximum_friction_number <= 0.0
    ):
        raise ValueError("maximum_friction_number must be finite and positive")
    if len(area) != len(mesh.cells) or len(discharge) != len(mesh.cells):
        raise ValueError("Manning predictor state must match the mesh")
    candidates: list[tuple[float, int]] = []
    for index, (cell, cell_area, cell_discharge) in enumerate(
        zip(mesh.cells, area, discharge)
    ):
        if cell.manning_n == 0.0 or cell_discharge == 0.0:
            continue
        stage = cell.geometry.stage_from_area(cell_area)
        radius = float(cell.geometry.hydraulic_radius(stage))
        if not math.isfinite(radius) or radius <= 0.0 or cell_area <= _EPSILON:
            raise NumericalStateError(
                "wet Manning predictor cell requires positive area and radius"
            )
        coefficient = (
            GRAVITY
            * cell.manning_n
            * cell.manning_n
            / (cell_area * radius ** (4.0 / 3.0))
        )
        denominator = coefficient * abs(cell_discharge)
        if denominator > 0.0:
            candidates.append((maximum_friction_number / denominator, index))
    if not candidates:
        return ManningTimeStepEstimate(math.inf, None)
    time_step, limiting_cell = min(candidates, key=lambda item: item[0])
    if not math.isfinite(time_step) or time_step <= 0.0:
        raise NumericalStateError("Manning predictor produced an invalid time step")
    return ManningTimeStepEstimate(time_step, limiting_cell)


def _semi_implicit_manning_values(
    *,
    area: float,
    discharge: float,
    geometry: SectionGeometryLike,
    manning_n: float,
    dt: float,
    gravity: float,
) -> tuple[float, float, float, float, float]:
    """Return ``Qf, R, k, mu, denominator`` without allocating evidence."""

    if not all(
        math.isfinite(value)
        for value in (area, discharge, manning_n, dt, gravity)
    ):
        raise NumericalStateError("Manning update inputs must be finite")
    if area < 0.0 or manning_n < 0.0 or dt <= 0.0 or gravity <= 0.0:
        raise NumericalStateError(
            "Manning update requires A>=0, n>=0, dt>0 and gravity>0"
        )
    if area <= _EPSILON:
        if abs(discharge) > _EPSILON:
            raise NumericalStateError(
                "dry cell cannot discard non-zero discharge in friction"
            )
        return 0.0, 0.0, 0.0, 0.0, 1.0
    if manning_n == 0.0 or discharge == 0.0:
        return discharge, 0.0, 0.0, 0.0, 1.0
    stage = geometry.stage_from_area(area)
    radius = float(geometry.hydraulic_radius(stage))
    if not math.isfinite(radius) or radius <= 0.0:
        raise NumericalStateError(
            "wet cell hydraulic radius must be finite and positive"
        )
    coefficient = gravity * manning_n * manning_n / (
        area * radius ** (4.0 / 3.0)
    )
    friction_number = dt * coefficient * abs(discharge)
    denominator = 1.0 + friction_number
    result = discharge / denominator
    if not math.isfinite(result):
        raise NumericalStateError(
            "semi-implicit Manning update produced a non-finite Q"
        )
    return result, radius, coefficient, friction_number, denominator


def _semi_implicit_manning_evidence(
    *,
    cell_id: str,
    area: float,
    discharge: float,
    geometry: SectionGeometryLike,
    manning_n: float,
    dt: float,
    gravity: float,
) -> ManningCellStageEvidence:
    """Evaluate one Manning update and retain every reproducibility input."""

    result, radius, coefficient, friction_number, denominator = (
        _semi_implicit_manning_values(
            area=area,
            discharge=discharge,
            geometry=geometry,
            manning_n=manning_n,
            dt=dt,
            gravity=gravity,
        )
    )
    return ManningCellStageEvidence(
        cell_id=cell_id,
        area=area,
        discharge_before=discharge,
        discharge_after=result,
        manning_n=manning_n,
        hydraulic_radius=radius,
        coefficient=coefficient,
        friction_number=friction_number,
        denominator=denominator,
        dt=dt,
        gravity=gravity,
    )


def semi_implicit_manning(
    *,
    area: float,
    discharge: float,
    geometry: SectionGeometryLike,
    manning_n: float,
    dt: float,
    gravity: float = GRAVITY,
) -> float:
    """Apply the sign-preserving linearised Manning momentum sink.

    For the cell ODE ``dQ/dt=-k Q|Q|``, the accepted MVP update is
    ``Q_new=Q_star/(1+dt*k*|Q_star|)``.  Friction is recomputed in every
    forward-Euler stage used by SSP-RK2.  This is deliberately described as a
    semi-implicit stage update, not as a proven globally second-order IMEX
    discretisation.
    """

    return _semi_implicit_manning_values(
        area=area,
        discharge=discharge,
        geometry=geometry,
        manning_n=manning_n,
        dt=dt,
        gravity=gravity,
    )[0]


def apply_manning_friction_with_evidence(
    *,
    mesh: FiniteVolumeMesh,
    area: tuple[float, ...] | list[float],
    discharge: tuple[float, ...] | list[float],
    dt: float,
) -> tuple[tuple[float, ...], tuple[ManningCellStageEvidence, ...]]:
    """Apply cell-local friction and return its exact per-cell stage evidence."""

    if len(area) != len(mesh.cells) or len(discharge) != len(mesh.cells):
        raise ValueError("friction arrays must match the mesh cell count")
    evidence = tuple(
        _semi_implicit_manning_evidence(
            cell_id=cell.cell_id,
            area=float(cell_area),
            discharge=float(cell_discharge),
            geometry=cell.geometry,
            manning_n=cell.manning_n,
            dt=dt,
            gravity=GRAVITY,
        )
        for cell, cell_area, cell_discharge in zip(mesh.cells, area, discharge)
    )
    return tuple(item.discharge_after for item in evidence), evidence


def apply_manning_friction(
    *,
    mesh: FiniteVolumeMesh,
    area: tuple[float, ...] | list[float],
    discharge: tuple[float, ...] | list[float],
    dt: float,
) -> tuple[float, ...]:
    """Apply the cell-local semi-implicit update to one complete branch."""

    if len(area) != len(mesh.cells) or len(discharge) != len(mesh.cells):
        raise ValueError("friction arrays must match the mesh cell count")
    return tuple(
        semi_implicit_manning(
            area=float(cell_area),
            discharge=float(cell_discharge),
            geometry=cell.geometry,
            manning_n=cell.manning_n,
            dt=dt,
            gravity=GRAVITY,
        )
        for cell, cell_area, cell_discharge in zip(mesh.cells, area, discharge)
    )
