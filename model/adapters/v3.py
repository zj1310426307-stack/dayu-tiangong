"""Adapt full hydraulic model-input.v3 into the established v2 solver contract."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from model.core.errors import HydraulicInputError


def _integer_id(value: Any, label: str) -> int:
    """Return one exact integer identifier and reject lossy coercion."""

    if isinstance(value, bool):
        raise HydraulicInputError(f"{label} must be an integer")
    try:
        identifier = int(value)
    except (TypeError, ValueError) as exc:
        raise HydraulicInputError(f"{label} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise HydraulicInputError(f"{label} must be an integer")
    if identifier <= 0:
        raise HydraulicInputError(f"{label} must be positive")
    return identifier


def _finite_number(value: Any, label: str) -> float:
    """Return a finite engineering value before it reaches the solver boundary."""

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HydraulicInputError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise HydraulicInputError(f"{label} must be finite")
    return number


def _validated_reaches(
    branches: list[Mapping[str, Any]],
    nodes: list[Mapping[str, Any]],
    reaches: list[Mapping[str, Any]],
) -> dict[int, list[Mapping[str, Any]]]:
    """Validate and order the HydraulicReach chains that v2 can represent exactly."""

    node_ids = {_integer_id(node.get("id"), "node id") for node in nodes}
    branches_by_id: dict[int, Mapping[str, Any]] = {}
    for branch in branches:
        branch_id = _integer_id(branch.get("id"), "branch id")
        if branch_id in branches_by_id:
            raise HydraulicInputError(f"model-input.v3 contains duplicate branch id {branch_id}")
        branches_by_id[branch_id] = branch

    grouped: defaultdict[int, list[Mapping[str, Any]]] = defaultdict(list)
    reach_ids: set[int] = set()
    for reach in reaches:
        reach_id = _integer_id(reach.get("id"), "reach id")
        branch_id = _integer_id(reach.get("branch_id"), f"reach {reach_id} branch_id")
        if reach_id in reach_ids:
            raise HydraulicInputError(f"model-input.v3 contains duplicate reach id {reach_id}")
        if branch_id not in branches_by_id:
            raise HydraulicInputError(
                f"HydraulicReach {reach_id} references unknown branch {branch_id}"
            )
        reach_ids.add(reach_id)
        if str(reach.get("reach_type", "channel")) != "channel":
            raise HydraulicInputError(
                f"HydraulicReach {reach_id} type {reach.get('reach_type')} "
                "cannot be projected to the channel-only v2 solver"
            )
        parameters = reach.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise HydraulicInputError(f"HydraulicReach {reach_id} parameters must be an object")
        unsupported_parameters = sorted(
            str(key)
            for key in parameters
            if key not in {"start_fraction", "end_fraction"}
        )
        if unsupported_parameters:
            raise HydraulicInputError(
                f"HydraulicReach {reach_id} has unsupported solver parameters: "
                + ", ".join(unsupported_parameters)
            )
        start = _finite_number(
            reach.get("start_chainage_m"), f"HydraulicReach {reach_id} start_chainage_m"
        )
        end = _finite_number(
            reach.get("end_chainage_m"), f"HydraulicReach {reach_id} end_chainage_m"
        )
        length = _finite_number(reach.get("length_m"), f"HydraulicReach {reach_id} length_m")
        upstream = _integer_id(
            reach.get("upstream_node_id"), f"HydraulicReach {reach_id} upstream_node_id"
        )
        downstream = _integer_id(
            reach.get("downstream_node_id"), f"HydraulicReach {reach_id} downstream_node_id"
        )
        if end <= start or length <= 0:
            raise HydraulicInputError(
                f"HydraulicReach {reach_id} requires increasing chainage and positive length"
            )
        if upstream == downstream or upstream not in node_ids or downstream not in node_ids:
            raise HydraulicInputError(
                f"HydraulicReach {reach_id} has invalid or unknown endpoint nodes"
            )
        geometry = reach.get("geometry")
        if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
            raise HydraulicInputError(f"HydraulicReach {reach_id} requires LineString geometry")
        grouped[branch_id].append(reach)

    for branch_id, branch in branches_by_id.items():
        ordered = sorted(
            grouped.get(branch_id, []),
            key=lambda reach: _finite_number(
                reach.get("start_chainage_m"), "reach start_chainage_m"
            ),
        )
        if not ordered:
            raise HydraulicInputError(
                f"branch {branch.get('branch_code', branch_id)} has no HydraulicReach"
            )
        branch_start = _finite_number(
            branch.get("start_chainage_m"), f"branch {branch_id} start_chainage_m"
        )
        branch_end = _finite_number(
            branch.get("end_chainage_m"), f"branch {branch_id} end_chainage_m"
        )
        branch_length = _finite_number(
            branch.get("length_m"), f"branch {branch_id} length_m"
        )
        branch_upstream = _integer_id(
            branch.get("upstream_node_id"), f"branch {branch_id} upstream_node_id"
        )
        branch_downstream = _integer_id(
            branch.get("downstream_node_id"), f"branch {branch_id} downstream_node_id"
        )
        tolerance = max(1.0e-6, abs(branch_end - branch_start) * 1.0e-9)
        first = ordered[0]
        last = ordered[-1]
        if not math.isclose(
            _finite_number(first.get("start_chainage_m"), "first reach start_chainage_m"),
            branch_start,
            rel_tol=0.0,
            abs_tol=tolerance,
        ) or not math.isclose(
            _finite_number(last.get("end_chainage_m"), "last reach end_chainage_m"),
            branch_end,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise HydraulicInputError(
                f"HydraulicReach chain for branch {branch_id} does not cover branch chainage"
            )
        if (
            _integer_id(first.get("upstream_node_id"), "first reach upstream_node_id")
            != branch_upstream
            or _integer_id(last.get("downstream_node_id"), "last reach downstream_node_id")
            != branch_downstream
        ):
            raise HydraulicInputError(
                f"HydraulicReach chain for branch {branch_id} does not match branch endpoints"
            )
        for upstream_reach, downstream_reach in zip(ordered, ordered[1:]):
            upstream_id = _integer_id(upstream_reach.get("id"), "upstream reach id")
            downstream_id = _integer_id(downstream_reach.get("id"), "downstream reach id")
            if not math.isclose(
                _finite_number(
                    upstream_reach.get("end_chainage_m"),
                    f"HydraulicReach {upstream_id} end_chainage_m",
                ),
                _finite_number(
                    downstream_reach.get("start_chainage_m"),
                    f"HydraulicReach {downstream_id} start_chainage_m",
                ),
                rel_tol=0.0,
                abs_tol=tolerance,
            ) or _integer_id(
                upstream_reach.get("downstream_node_id"),
                f"HydraulicReach {upstream_id} downstream_node_id",
            ) != _integer_id(
                downstream_reach.get("upstream_node_id"),
                f"HydraulicReach {downstream_id} upstream_node_id",
            ):
                raise HydraulicInputError(
                    f"HydraulicReach chain for branch {branch_id} is not contiguous"
                )
        reach_length = sum(
            _finite_number(reach.get("length_m"), "reach length_m") for reach in ordered
        )
        if not math.isclose(
            reach_length,
            branch_length,
            rel_tol=1.0e-6,
            abs_tol=1.0e-6,
        ):
            raise HydraulicInputError(
                f"HydraulicReach lengths for branch {branch_id} do not match branch length"
            )
        grouped[branch_id] = ordered
    return dict(grouped)


def _project_gates_to_reaches(
    gates: Any, reaches_by_branch: Mapping[int, list[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    """Resolve an explicit Reach or project an authoritative branch chainage."""

    if not isinstance(gates, list):
        raise HydraulicInputError("model-input.v3 gates must be an array")
    reaches_by_id = {
        _integer_id(reach.get("id"), "reach id"): reach
        for reaches in reaches_by_branch.values()
        for reach in reaches
    }
    projected: list[dict[str, Any]] = []
    for index, gate in enumerate(gates):
        if not isinstance(gate, Mapping):
            raise HydraulicInputError(f"model-input.v3 gates[{index}] must be an object")
        result = dict(gate)
        explicit_reach = gate.get("reach_id")
        branch_reference = gate.get("branch_id")
        legacy_reference = gate.get("river_segment_id")
        if branch_reference is not None and legacy_reference is not None:
            branch_id = _integer_id(
                branch_reference, f"gate {gate.get('id', index)} branch_id"
            )
            legacy_branch_id = _integer_id(
                legacy_reference,
                f"gate {gate.get('id', index)} river_segment_id",
            )
            if branch_id != legacy_branch_id:
                raise HydraulicInputError(
                    f"gate {gate.get('id', index)} branch references disagree"
                )
        reference = (
            branch_reference if branch_reference is not None else legacy_reference
        )
        chainage_value = (
            gate.get("chainage") if "chainage" in gate else gate.get("station")
        )
        chainage = (
            None
            if chainage_value is None
            else _finite_number(
                chainage_value, f"gate {gate.get('id', index)} chainage"
            )
        )
        if explicit_reach is not None:
            reach_id = _integer_id(
                explicit_reach, f"gate {gate.get('id', index)} reach_id"
            )
            reach = reaches_by_id.get(reach_id)
            if reach is None:
                raise HydraulicInputError(
                    f"gate {gate.get('id', index)} references unknown HydraulicReach {reach_id}"
                )
            if reference is not None:
                branch_id = _integer_id(
                    reference, f"gate {gate.get('id', index)} river_segment_id"
                )
                if _integer_id(reach.get("branch_id"), "reach branch_id") != branch_id:
                    raise HydraulicInputError(
                        f"gate {gate.get('id', index)} reach {reach_id} does not belong "
                        f"to branch {branch_id}"
                    )
            if chainage is not None:
                reach_start = _finite_number(
                    reach.get("start_chainage_m"),
                    f"HydraulicReach {reach_id} start_chainage_m",
                )
                reach_end = _finite_number(
                    reach.get("end_chainage_m"),
                    f"HydraulicReach {reach_id} end_chainage_m",
                )
                tolerance = max(1.0e-9, abs(reach_end - reach_start) * 1.0e-9)
                if chainage < reach_start - tolerance or chainage > reach_end + tolerance:
                    raise HydraulicInputError(
                        f"gate {gate.get('id', index)} chainage {chainage} lies outside "
                        f"explicit HydraulicReach {reach_id}"
                    )
            result["river_segment_id"] = reach_id
            resolution = "explicit_reach_id"
        elif reference is not None:
            branch_id = _integer_id(
                reference, f"gate {gate.get('id', index)} branch reference"
            )
            candidates = reaches_by_branch.get(branch_id)
            if not candidates:
                raise HydraulicInputError(
                    f"gate {gate.get('id', index)} references unknown hydraulic branch {branch_id}"
                )
            if len(candidates) == 1:
                selected = candidates[0]
                resolution = "unique_branch_projection"
                if chainage is not None:
                    reach_start = _finite_number(
                        selected.get("start_chainage_m"),
                        "gate target reach start_chainage_m",
                    )
                    reach_end = _finite_number(
                        selected.get("end_chainage_m"),
                        "gate target reach end_chainage_m",
                    )
                    tolerance = max(
                        1.0e-9, abs(reach_end - reach_start) * 1.0e-9
                    )
                    if (
                        chainage < reach_start - tolerance
                        or chainage > reach_end + tolerance
                    ):
                        raise HydraulicInputError(
                            f"gate {gate.get('id', index)} chainage {chainage} lies "
                            f"outside hydraulic branch {branch_id}"
                        )
            elif chainage is not None:
                containing: list[Mapping[str, Any]] = []
                for candidate in candidates:
                    reach_start = _finite_number(
                        candidate.get("start_chainage_m"),
                        "gate candidate reach start_chainage_m",
                    )
                    reach_end = _finite_number(
                        candidate.get("end_chainage_m"),
                        "gate candidate reach end_chainage_m",
                    )
                    tolerance = max(
                        1.0e-9, abs(reach_end - reach_start) * 1.0e-9
                    )
                    if (
                        chainage > reach_start + tolerance
                        and chainage < reach_end - tolerance
                    ):
                        containing.append(candidate)
                if len(containing) != 1:
                    raise HydraulicInputError(
                        f"gate {gate.get('id', index)} references branch {branch_id} "
                        f"with {len(candidates)} reaches; the target reach is ambiguous"
                    )
                selected = containing[0]
                resolution = "authoritative_chainage_projection"
            else:
                raise HydraulicInputError(
                    f"gate {gate.get('id', index)} references branch {branch_id} with "
                    f"{len(candidates)} reaches; the target reach is ambiguous"
                )
            reach_id = _integer_id(selected.get("id"), "gate target reach id")
            result["river_segment_id"] = reach_id
        else:
            projected.append(result)
            continue
        result["reach_id"] = reach_id
        provenance = result.get("provenance")
        if isinstance(provenance, Mapping):
            result["provenance"] = {
                **provenance,
                "reach_id": reach_id,
                "reach_resolution": resolution,
            }
        projected.append(result)
    return projected


_REQUIRED_STRUCTURE_FIELDS = frozenset({
    "id",
    "dataset_version_id",
    "branch_id",
    "chainage",
    "geometry",
    "parameters",
    "control_state",
    "provenance",
})

_GATE_PARAMETER_FIELDS = (
    "gate_type",
    "opening_direction",
    "width",
    "height",
    "max_flow",
    "bottom_elevation",
    "crest_elevation",
    "discharge_coefficient",
    "minimum_opening",
    "maximum_opening",
    "opening_rate_limit",
    "minimum_hold_seconds",
    "allow_reverse_flow",
)
_PUMP_PARAMETER_FIELDS = (
    "design_flow",
    "head",
    "head_curve",
    "efficiency_curve",
    "power",
    "transfer_type",
    "unit_count",
    "minimum_running_units",
    "maximum_running_units",
    "minimum_run_seconds",
    "minimum_stop_seconds",
    "maximum_starts_per_run",
    "minimum_operating_head",
    "maximum_operating_head",
    "reverse_flow_protection",
)


def _project_canonical_structure_fields(
    row: Mapping[str, Any], structure_type: str, label: str
) -> dict[str, Any]:
    """Project canonical parameters/state to the legacy solver shape without ambiguity."""

    parameters = row.get("parameters")
    control_state = row.get("control_state")
    if not isinstance(parameters, Mapping) or not isinstance(control_state, Mapping):
        raise HydraulicInputError(f"{label} parameters and control_state must be objects")
    result = dict(row)
    parameter_fields = (
        _GATE_PARAMETER_FIELDS if structure_type == "gate" else _PUMP_PARAMETER_FIELDS
    )
    for field_name in parameter_fields:
        if field_name not in parameters:
            continue
        canonical_value = parameters[field_name]
        if field_name in row and row[field_name] != canonical_value:
            raise HydraulicInputError(
                f"{label} canonical parameter {field_name} conflicts with its flat mirror"
            )
        result[field_name] = canonical_value

    aliases = (
        (("minimum_opening", "opening_min"), ("maximum_opening", "opening_max"))
        if structure_type == "gate"
        else (("unit_count", "pump_count"),)
    )
    for primary, alias in aliases:
        has_primary = primary in parameters
        has_alias = alias in parameters
        if has_primary and has_alias and parameters[primary] != parameters[alias]:
            raise HydraulicInputError(
                f"{label} canonical parameters {primary} and {alias} disagree"
            )
        if not has_primary and has_alias:
            canonical_value = parameters[alias]
            if primary in row and row[primary] != canonical_value:
                raise HydraulicInputError(
                    f"{label} canonical parameter {alias} conflicts with flat {primary}"
                )
            result[primary] = canonical_value

    availability = control_state.get("availability")
    if not isinstance(availability, str) or not availability:
        raise HydraulicInputError(f"{label} control_state availability must be a string")
    if "status" in row and row["status"] != availability:
        raise HydraulicInputError(
            f"{label} canonical availability conflicts with its flat status mirror"
        )
    result["status"] = availability
    control_mode = control_state.get("control_mode")
    if control_mode is not None:
        if "control_mode" in row and row["control_mode"] != control_mode:
            raise HydraulicInputError(
                f"{label} canonical control_mode conflicts with its flat mirror"
            )
        result["control_mode"] = control_mode
    return result


def _validated_structure_control_envelopes(
    snapshot: Mapping[str, Any],
    reaches_by_branch: Mapping[int, list[Mapping[str, Any]]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], bool]:
    """Read the authoritative v3 envelope while retaining legacy top-level input."""

    structures = snapshot.get("structures")
    if structures is None:
        gates = snapshot.get("gates", [])
        pumps = snapshot.get("pumps", [])
        if not isinstance(gates, list) or not isinstance(pumps, list):
            raise HydraulicInputError("model-input.v3 gates and pumps must be arrays")
        return gates, pumps, False
    if not isinstance(structures, Mapping):
        raise HydraulicInputError("model-input.v3 structures must be an object")

    gates = structures.get("gates")
    pumps = structures.get("pumps")
    if not isinstance(gates, list) or not isinstance(pumps, list):
        raise HydraulicInputError(
            "model-input.v3 structures.gates and structures.pumps must be arrays"
        )
    for collection_name, nested in (("gates", gates), ("pumps", pumps)):
        if collection_name in snapshot and snapshot[collection_name] != nested:
            raise HydraulicInputError(
                "model-input.v3 nested structures must match top-level gates and pumps"
            )

    dataset_version = snapshot.get("dataset_version")
    if not isinstance(dataset_version, Mapping):
        raise HydraulicInputError("model-input.v3 dataset_version must be an object")
    dataset_version_id = _integer_id(
        dataset_version.get("id"), "dataset_version id"
    )
    reaches_by_id = {
        _integer_id(reach.get("id"), "reach id"): reach
        for reaches in reaches_by_branch.values()
        for reach in reaches
    }
    projected_structures: dict[str, list[Mapping[str, Any]]] = {
        "gate": [],
        "pump": [],
    }
    for structure_type, rows in (("gate", gates), ("pump", pumps)):
        seen_ids: set[int] = set()
        for index, row in enumerate(rows):
            label = f"model-input.v3 structures.{structure_type}s[{index}]"
            if not isinstance(row, Mapping):
                raise HydraulicInputError(f"{label} must be an object")
            missing = sorted(_REQUIRED_STRUCTURE_FIELDS.difference(row))
            if missing:
                raise HydraulicInputError(
                    f"{label} is missing required fields: {', '.join(missing)}"
                )
            structure_id = _integer_id(row.get("id"), f"{label} id")
            if structure_id in seen_ids:
                raise HydraulicInputError(
                    f"model-input.v3 contains duplicate {structure_type} id {structure_id}"
                )
            seen_ids.add(structure_id)
            if _integer_id(
                row.get("dataset_version_id"), f"{label} dataset_version_id"
            ) != dataset_version_id:
                raise HydraulicInputError(
                    f"{label} belongs to a different dataset version"
                )
            branch_id = _integer_id(row.get("branch_id"), f"{label} branch_id")
            if branch_id not in reaches_by_branch:
                raise HydraulicInputError(
                    f"{label} references unknown hydraulic branch {branch_id}"
                )
            chainage = row.get("chainage")
            if chainage is not None and _finite_number(chainage, f"{label} chainage") < 0:
                raise HydraulicInputError(f"{label} chainage must be non-negative")
            for field_name in ("geometry", "parameters", "control_state", "provenance"):
                if not isinstance(row.get(field_name), Mapping):
                    raise HydraulicInputError(f"{label} {field_name} must be an object")
            control_state = row["control_state"]
            required_state_fields = {"mode", "status", "availability"}
            required_state_fields.add(
                "opening" if structure_type == "gate" else "running_units"
            )
            missing_state = sorted(required_state_fields.difference(control_state))
            if missing_state:
                raise HydraulicInputError(
                    f"{label} control_state is missing required fields: "
                    + ", ".join(missing_state)
                )
            provenance = row["provenance"]
            provenance_version = provenance.get("dataset_version")
            if (
                not isinstance(provenance_version, Mapping)
                or _integer_id(
                    provenance_version.get("id"),
                    f"{label} provenance dataset_version id",
                )
                != dataset_version_id
            ):
                raise HydraulicInputError(
                    f"{label} provenance must identify the frozen dataset version"
                )
            explicit_reach = row.get("reach_id")
            if explicit_reach is not None:
                reach_id = _integer_id(explicit_reach, f"{label} reach_id")
                reach = reaches_by_id.get(reach_id)
                if reach is None:
                    raise HydraulicInputError(
                        f"{label} references unknown HydraulicReach {reach_id}"
                    )
                if _integer_id(
                    reach.get("branch_id"), f"HydraulicReach {reach_id} branch_id"
                ) != branch_id:
                    raise HydraulicInputError(
                        f"{label} reach {reach_id} does not belong to branch {branch_id}"
                    )
                if provenance.get("reach_id") != explicit_reach:
                    raise HydraulicInputError(
                        f"{label} explicit reach_id must be recorded in provenance"
                    )
                if chainage is not None:
                    reach_start = _finite_number(
                        reach.get("start_chainage_m"),
                        f"HydraulicReach {reach_id} start_chainage_m",
                    )
                    reach_end = _finite_number(
                        reach.get("end_chainage_m"),
                        f"HydraulicReach {reach_id} end_chainage_m",
                    )
                    tolerance = max(
                        1.0e-9, abs(reach_end - reach_start) * 1.0e-9
                    )
                    numeric_chainage = _finite_number(chainage, f"{label} chainage")
                    if (
                        numeric_chainage < reach_start - tolerance
                        or numeric_chainage > reach_end + tolerance
                    ):
                        raise HydraulicInputError(
                            f"{label} chainage {numeric_chainage} lies outside "
                            f"HydraulicReach {reach_id}"
                        )
            if structure_type == "gate":
                if "station" in row:
                    station = row.get("station")
                    if (station is None) != (chainage is None) or (
                        station is not None
                        and chainage is not None
                        and not math.isclose(
                            _finite_number(station, f"{label} station"),
                            _finite_number(chainage, f"{label} chainage"),
                            rel_tol=0.0,
                            abs_tol=1.0e-9,
                        )
                    ):
                        raise HydraulicInputError(
                            f"{label} chainage must mirror the authoritative gate station"
                        )
            else:
                chainage_source = provenance.get("chainage_source")
                if chainage is None:
                    if chainage_source != "unavailable_not_inferred":
                        raise HydraulicInputError(
                            f"{label} null chainage must record unavailable_not_inferred"
                        )
                elif (
                    not isinstance(chainage_source, str)
                    or not chainage_source.strip()
                    or chainage_source == "unavailable_not_inferred"
                ):
                    raise HydraulicInputError(
                        f"{label} chainage requires an explicit provenance source"
                    )
            projected_structures[structure_type].append(
                _project_canonical_structure_fields(row, structure_type, label)
            )

    controls = snapshot.get("controls")
    if not isinstance(controls, Mapping):
        raise HydraulicInputError("model-input.v3 controls must be an object")
    rules = controls.get("rules")
    if not isinstance(rules, list):
        raise HydraulicInputError("model-input.v3 controls.rules must be an array")
    dispatch_plan = snapshot.get("dispatch_plan")
    if dispatch_plan is None:
        expected_rules: list[Any] = []
    else:
        if not isinstance(dispatch_plan, Mapping):
            raise HydraulicInputError("model-input.v3 dispatch_plan must be an object")
        expected_rules = dispatch_plan.get("rules", [])
        if not isinstance(expected_rules, list):
            raise HydraulicInputError(
                "model-input.v3 dispatch_plan.rules must be an array"
            )
    if rules != expected_rules:
        raise HydraulicInputError(
            "model-input.v3 controls.rules must mirror dispatch_plan.rules"
        )
    return projected_structures["gate"], projected_structures["pump"], True


def adapt_v3_to_v2(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Project v3 profiles and losslessly representable Reach topology to v2."""

    if snapshot.get("schema_version") != "dayu.model-input.v3":
        raise HydraulicInputError("v3 adapter requires dayu.model-input.v3")
    branches = snapshot.get("branches")
    nodes = snapshot.get("nodes")
    reaches = snapshot.get("reaches")
    profiles = snapshot.get("cross_section_profiles")
    if (
        not isinstance(branches, list)
        or not all(isinstance(branch, Mapping) for branch in branches)
        or not isinstance(nodes, list)
        or not all(isinstance(node, Mapping) for node in nodes)
        or not isinstance(reaches, list)
        or not all(isinstance(reach, Mapping) for reach in reaches)
        or not isinstance(profiles, list)
    ):
        raise HydraulicInputError(
            "model-input.v3 requires branch, node, reach, and cross_section_profiles arrays"
        )
    reaches_by_branch = _validated_reaches(branches, nodes, reaches)
    river_ids = {
        int(branch["id"]): int(branch.get("legacy_river_id") or branch["id"])
        for branch in branches
    }
    structure_gates, structure_pumps, has_structure_envelope = (
        _validated_structure_control_envelopes(snapshot, reaches_by_branch)
    )
    result = dict(snapshot)
    result["schema_version"] = "dayu.model-input.v2"
    result["_source_schema_version"] = "dayu.model-input.v3"
    result["rivers"] = [{
        "id": river_ids[int(branch["id"])], "code": branch["branch_code"],
        "name": branch["branch_name"], "length": branch["length_m"],
        "level": "main", "status": "active", "geometry": branch["centerline"],
    } for branch in branches]
    result["nodes"] = [{
        "id": node["id"], "node_code": node["node_code"],
        "node_type": node["node_type"], "geometry": node["geometry"],
        "longitude": node["geometry"]["coordinates"][0],
        "latitude": node["geometry"]["coordinates"][1],
    } for node in nodes]
    ordered_reaches = [
        reach
        for branch in branches
        for reach in reaches_by_branch[_integer_id(branch.get("id"), "branch id")]
    ]
    result["segments"] = [{
        "id": _integer_id(reach.get("id"), "reach id"),
        "river_id": river_ids[_integer_id(reach.get("branch_id"), "reach branch_id")],
        "segment_code": str(reach["reach_code"]),
        "upstream_node_id": reach["upstream_node_id"],
        "downstream_node_id": reach["downstream_node_id"],
        "length": reach["length_m"],
        "geometry": reach["geometry"],
    } for reach in ordered_reaches]
    result["connections"] = [{
        "id": _integer_id(reach.get("id"), "reach id"),
        "river_id": river_ids[_integer_id(reach.get("branch_id"), "reach branch_id")],
        "from_node_id": reach["upstream_node_id"],
        "to_node_id": reach["downstream_node_id"],
    } for reach in ordered_reaches]
    result["gates"] = _project_gates_to_reaches(
        structure_gates, reaches_by_branch
    )
    result["pumps"] = [dict(pump) for pump in structure_pumps]
    if has_structure_envelope:
        result["structures"] = {
            "gates": result["gates"],
            "pumps": result["pumps"],
        }
    result["cross_sections"] = [{
        "id": profile["cross_section_id"],
        "river_id": river_ids[int(profile["branch_id"])],
        "section_code": profile["section_code"],
        "section_name": profile["section_code"],
        "station": profile["chainage_m"],
        "points": {"points": [[p["offset_m"], p["elevation_m"]] for p in profile["points"]]},
        "roughness": profile["default_manning_n"],
        "elevation_min": min(float(p["elevation_m"]) for p in profile["points"]),
        "geometry_type": "tabulated",
        "profile_hash": profile["profile_hash"],
        "topography_id": profile["topography_id"],
    } for profile in profiles]
    controls = dict(result.get("controls") or {})
    controls["section_geometry"] = "tabulated"
    result["controls"] = controls
    provenance = dict(result.get("provenance") or {})
    provenance["input_schema_version"] = "dayu.model-input.v3"
    provenance["solver_adapter"] = "model.adapters.v3.adapt_v3_to_v2"
    provenance["reach_projection"] = "one solver segment per validated HydraulicReach"
    provenance["reach_count"] = len(ordered_reaches)
    result["provenance"] = provenance
    return result
