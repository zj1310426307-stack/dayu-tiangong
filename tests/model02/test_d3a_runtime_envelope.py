"""D3A RC1 dynamic runtime-envelope and retry evidence gates."""

from __future__ import annotations

import pytest

from model.geometry import RectangularSectionGeometry
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    D3A_RUNTIME_ENVELOPE_ID,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    HydraulicState,
    RuntimeEnvelopeStabilityError,
    StabilityError,
    UpstreamDischargeBoundary,
    advance_with_retries,
    observe_runtime_envelope,
    require_runtime_envelope,
    resolve_runtime_envelope,
)


def _mesh() -> FiniteVolumeMesh:
    """Return a small uniform fully-wet reach for envelope unit tests."""

    geometry = RectangularSectionGeometry(width=2.0, bed_elevation=0.0)
    return FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"envelope-{index}",
                dx=20.0,
                section_id=index + 1,
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(3)
        )
    )


def _state(
    mesh: FiniteVolumeMesh,
    *,
    area: tuple[float, float, float] = (2.0, 2.0, 2.0),
    discharge: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> HydraulicState:
    """Build one deterministic conservative state on the unit-test mesh."""

    return HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=area,
        discharge=discharge,
        dry_depth=1.0e-3,
    )


def test_runtime_envelope_passes_fully_wet_forward_subcritical_state() -> None:
    """A finite forward state reports all three physical extrema."""

    mesh = _mesh()
    observation = observe_runtime_envelope(
        mesh=mesh,
        state=_state(mesh),
        envelope=resolve_runtime_envelope(D3A_RUNTIME_ENVELOPE_ID),
    )
    assert observation.status == "pass"
    assert observation.minimum_water_depth_m == pytest.approx(1.0)
    assert observation.minimum_discharge_m3s == pytest.approx(1.0)
    assert 0.0 < observation.maximum_froude_number < 0.8


@pytest.mark.parametrize(
    ("area", "discharge", "message"),
    [
        ((2.0, 2.0, 2.0), (1.0, -1.0e-6, 1.0), "reverse flow"),
        ((2.0e-3, 2.0, 2.0), (0.0, 1.0, 1.0), "not fully wet"),
        ((2.0, 2.0, 2.0), (6.0, 1.0, 1.0), "Froude"),
    ],
)
def test_runtime_envelope_fails_closed_for_each_scope_boundary(
    area: tuple[float, float, float],
    discharge: tuple[float, float, float],
    message: str,
) -> None:
    """Reverse, dry and over-Froude states remain distinct hard failures."""

    mesh = _mesh()
    with pytest.raises(RuntimeEnvelopeStabilityError, match=message):
        require_runtime_envelope(
            mesh=mesh,
            state=_state(mesh, area=area, discharge=discharge),
            envelope=resolve_runtime_envelope(D3A_RUNTIME_ENVELOPE_ID),
            checkpoint="unit test",
        )


def test_stage_envelope_violation_retries_then_persists_pass_evidence() -> None:
    """An over-Froude trial halves dt and exposes its dedicated retry count."""

    mesh = _mesh()
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, 10.0), (15.0, 15.0), "discharge")
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, 10.0), (1.0, 1.0), "stage")
        ),
    )
    result = advance_with_retries(
        mesh=mesh,
        state=_state(mesh),
        requested_dt=5.0,
        dry_depth=1.0e-3,
        boundaries=boundaries,
        cfl_limit=0.9,
        minimum_dt=1.0e-3,
        maximum_retries=20,
        runtime_envelope=resolve_runtime_envelope(D3A_RUNTIME_ENVELOPE_ID),
    )
    assert result.runtime_envelope_retry_count == 3
    assert result.runtime_envelope_observation is not None
    assert result.runtime_envelope_observation.status == "pass"
    assert result.runtime_envelope_observation.maximum_froude_number <= 0.8


def test_persistent_runtime_envelope_violation_fails_at_minimum_dt() -> None:
    """A non-transient reverse state is never clipped into the D3A scope."""

    mesh = _mesh()
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, 1.0), (1.0, 1.0), "discharge")
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, 1.0), (1.0, 1.0), "stage")
        ),
    )
    with pytest.raises(StabilityError, match="runtime envelope failed at minimum_dt"):
        advance_with_retries(
            mesh=mesh,
            state=_state(mesh, discharge=(-1.0e-3, 1.0, 1.0)),
            requested_dt=0.01,
            dry_depth=1.0e-3,
            boundaries=boundaries,
            cfl_limit=0.9,
            minimum_dt=0.005,
            maximum_retries=20,
            runtime_envelope=resolve_runtime_envelope(D3A_RUNTIME_ENVELOPE_ID),
        )
