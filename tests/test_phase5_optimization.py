"""Phase 5 algorithm, constraint, Pareto and persistence contract tests."""

from __future__ import annotations

from time import perf_counter

import pytest

from app.gis.models import OptimizationCandidate, OptimizationResult, OptimizationTask
from optimization.algorithms import ParticleSwarmOptimizer
from optimization.constraints import validate_candidate
from optimization.objectives import evaluate_objectives
from optimization.pareto import non_dominated_sort


def test_particle_swarm_converges_on_seeded_sphere() -> None:
    """PSO must improve a convex objective reproducibly."""

    optimizer = ParticleSwarmOptimizer(
        [(-5, 5), (-5, 5)],
        particle_count=24,
        max_iterations=50,
        seed=7,
        tolerance=1e-10,
        patience=12,
    )
    _, score = optimizer.optimize(
        lambda vector, _generation, _index: sum(value * value for value in vector)
    )
    assert score < 0.01
    assert optimizer.iterations_completed <= 50
    assert len(optimizer.evaluations) == optimizer.iterations_completed * 24


def test_objective_weights_are_versioned_and_normalized() -> None:
    """Weighted score must use the frozen v1 objective contract."""

    result = evaluate_objectives(
        {
            "network_maximum_water_level": 100,
            "warning_exceedance_seconds": 120,
            "guarantee_exceedance_seconds": 0,
            "pump_total_energy_kwh": 20,
            "pump_runtime_seconds": 300,
            "pump_start_count": 1,
            "pump_stop_count": 1,
            "gate_action_count": 2,
            "gate_cumulative_opening_change_m": 0.5,
        },
        {
            "version": "dayu.objectives.v1",
            "weights": {"flood_risk": 5, "energy_cost": 3, "operation_cost": 2},
            "normalization": {},
        },
    )
    assert result["version"] == "dayu.objectives.v1"
    assert sum(result["weights"].values()) == pytest.approx(1)
    assert result["score"] >= 0


def test_gate_pump_and_hydraulic_constraints_return_reasons() -> None:
    """A candidate reports all stable hard-constraint reason codes."""

    plan = {
        "actions": [
            {"structure_type": "gate", "gate_id": 1, "command_type": "gate_opening_ratio", "target_value": 1.2, "time_seconds": 0},
            {"structure_type": "pump", "pump_id": 2, "command_type": "pump_enabled", "target_value": 1, "time_seconds": 0},
            {"structure_type": "pump", "pump_id": 2, "command_type": "pump_enabled", "target_value": 0, "time_seconds": 5},
        ]
    }
    result = validate_candidate(
        plan,
        gates=[{"id": 1, "height": 2, "maximum_opening": 2}],
        pumps=[{"id": 2, "minimum_run_seconds": 30, "maximum_starts_per_run": 1}],
        config={"hydraulic_limits": {"maximum_water_level": 10, "maximum_flow": 20}},
        metrics={"network_maximum_water_level": 12, "network_maximum_flow": 25},
    )
    assert result.as_dict()["valid"] is False
    assert "gate:1:opening_out_of_range" in result.reasons
    assert "pump:2:minimum_runtime_violated" in result.reasons
    assert "hydraulic:maximum_water_level_exceeded" in result.reasons
    assert "hydraulic:maximum_flow_exceeded" in result.reasons


def test_pareto_levels_are_deterministic() -> None:
    """Dominated candidates must be assigned to later one-based fronts."""

    levels = non_dominated_sort([(1, 4, 2), (2, 2, 2), (4, 1, 2), (3, 3, 3)])
    assert levels[:3] == [1, 1, 1]
    assert levels[3] == 2


def test_candidate_persistence_links_phase4_simulation_task() -> None:
    """ORM metadata must preserve candidate-to-Phase-4 evidence and Pareto links."""

    candidate_columns = OptimizationCandidate.__table__.columns
    simulation_fk = next(iter(candidate_columns["simulation_task_id"].foreign_keys))
    result_fk = next(iter(OptimizationResult.__table__.columns["candidate_id"].foreign_keys))
    assert simulation_fk.target_fullname == "simulation_task.id"
    assert result_fk.target_fullname == "optimization_candidate.id"
    assert "input_snapshot_hash" in OptimizationTask.__table__.columns


def test_pareto_sort_performance_for_one_thousand_candidates() -> None:
    """Frontier calculation remains interactive for a normal review workload."""

    vectors = [(index % 31, (index * 7) % 43, (index * 13) % 47) for index in range(1000)]
    started = perf_counter()
    levels = non_dominated_sort(vectors)
    assert len(levels) == 1000
    assert perf_counter() - started < 2.5
