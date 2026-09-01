"""Strict Opthyca `.opt` parser producing the unified Dayu hydraulic result."""

from __future__ import annotations

from csv import reader
from dataclasses import dataclass
from math import hypot, isclose, isfinite
from pathlib import Path
from re import DOTALL, findall, sub
from model.hydraulic_1d.contracts import (
    Hydraulic1DModel,
    HydraulicCrossSection,
    HydraulicResult,
    HydraulicResultRecord,
)
from model.hydraulic_1d.errors import Hydraulic1DResultError
from model.hydraulic_1d.mascaret.config import MASCARET_ENGINE_ID, MASCARET_VERSION
from model.hydraulic_1d.mascaret.adapter import (
    MascaretPreparedCase,
    mascaret_branch_offsets,
)


@dataclass(frozen=True, slots=True)
class _WetGeometry:
    """Carry geometry-derived metrics that are not trusted from optional raw columns."""

    area_m2: float
    top_width_m: float
    wetted_perimeter_m: float
    depth_m: float


class MascaretResultParser:
    """Parse official Opthyca rows and reject topology or time-axis drift."""

    REQUIRED_VARIABLES = frozenset({"Z", "Q"})

    def parse(
        self,
        model: Hydraulic1DModel,
        prepared: MascaretPreparedCase,
        *,
        runtime_seconds: float,
    ) -> HydraulicResult:
        """Convert a complete `.opt` file without inventing missing H/Q values."""

        try:
            lines = prepared.result_file.read_text(
                encoding="iso-8859-1",
                errors="strict",
            ).splitlines()
        except (OSError, UnicodeError) as exc:
            raise Hydraulic1DResultError(f"cannot read MASCARET result: {exc}") from exc
        variables, result_start = self._variables(lines)
        missing = sorted(self.REQUIRED_VARIABLES.difference(variables))
        if missing:
            raise Hydraulic1DResultError(
                "MASCARET result lacks required variables: " + ", ".join(missing)
            )
        branches = sorted(model.branches, key=lambda item: (item.code, item.id))
        branch_by_reach = {
            str(index): branch for index, branch in enumerate(branches, start=1)
        }
        branch_offsets = mascaret_branch_offsets(branches)
        sections_by_branch = {
            branch.id: sorted(
                (item for item in model.cross_sections if item.branch_id == branch.id),
                key=lambda item: item.chainage_m,
            )
            for branch in branches
        }
        sections = [
            section for branch in branches for section in sections_by_branch[branch.id]
        ]
        records: list[HydraulicResultRecord] = []
        last_time_by_section: dict[tuple[str, str], float] = {}
        raw_location_by_section: dict[tuple[str, str], float] = {}
        seen_sections: set[str] = set()
        mapped_times_by_section: dict[str, set[float]] = {
            item.id: set() for item in sections
        }
        mapped_keys: set[tuple[str, float]] = set()
        raw_rows = 0
        for line_number, raw in enumerate(lines[result_start:], start=result_start + 1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            values = next(reader([stripped], delimiter=";", quotechar='"'))
            if len(values) != len(variables) + 4:
                raise Hydraulic1DResultError(
                    f"line {line_number} has {len(values) - 4} values; "
                    f"expected {len(variables)}"
                )
            time_seconds = self._number(values[0], line_number, "time")
            reach_id = values[1].strip()
            section_number = values[2].strip()
            branch = branch_by_reach.get(reach_id)
            if branch is None:
                raise Hydraulic1DResultError(
                    f"unexpected MASCARET reach id {reach_id!r}; adapter generated "
                    f"{len(branches)} branches"
                )
            native_chainage_m = self._number(values[3], line_number, "chainage")
            chainage_m = native_chainage_m - branch_offsets[branch.id]
            raw_values = [
                self._number(value, line_number, abbreviation)
                for abbreviation, value in zip(variables, values[4:])
            ]
            row = dict(zip(variables, raw_values))
            raw_rows += 1
            raw_key = reach_id, section_number
            previous_chainage = raw_location_by_section.setdefault(
                raw_key, native_chainage_m
            )
            if not isclose(
                previous_chainage,
                native_chainage_m,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise Hydraulic1DResultError(
                    f"MASCARET section {raw_key!r} changed chainage across time"
                )
            previous_time = last_time_by_section.get(raw_key)
            if previous_time is not None and time_seconds <= previous_time:
                raise Hydraulic1DResultError(
                    f"MASCARET section {raw_key!r} has a repeated or decreasing time"
                )
            last_time_by_section[raw_key] = time_seconds
            section = self._match_section(sections_by_branch[branch.id], chainage_m)
            if section is None:
                continue
            mapped_key = section.id, time_seconds
            if mapped_key in mapped_keys:
                raise Hydraulic1DResultError(
                    f"duplicate mapped MASCARET row for section {section.id!r}, "
                    f"t={time_seconds:g}"
                )
            mapped_keys.add(mapped_key)
            mapped_times_by_section[section.id].add(time_seconds)
            stage = row["Z"]
            geometry = self._wet_geometry(section, stage)
            raw_depth = row.get("Y")
            depth = geometry.depth_m if raw_depth is None else raw_depth
            if depth < 0.0:
                raise Hydraulic1DResultError(
                    f"negative depth at section {section.id!r}, t={time_seconds:g}"
                )
            discharge = row["Q"]
            raw_area = self._pair_sum(row, "S1", "S2")
            raw_top_width = self._pair_sum(row, "B1", "B2")
            raw_perimeter = self._pair_sum(row, "P1", "P2")
            area = geometry.area_m2 if raw_area is None else raw_area
            top_width = geometry.top_width_m if raw_top_width is None else raw_top_width
            perimeter = (
                geometry.wetted_perimeter_m if raw_perimeter is None else raw_perimeter
            )
            if area <= 0.0 or top_width <= 0.0 or perimeter <= 0.0:
                raise Hydraulic1DResultError(
                    f"non-positive wet geometry at section {section.id!r}, t={time_seconds:g}"
                )
            velocity = discharge / area
            hydraulic_radius = area / perimeter
            records.append(
                HydraulicResultRecord(
                    simulation_id=model.simulation_id,
                    scenario_id=model.scenario_id,
                    engine=MASCARET_ENGINE_ID,
                    engine_version=MASCARET_VERSION,
                    branch_id=branch.id,
                    chainage_m=section.chainage_m,
                    cross_section_id=section.id,
                    timestamp=time_seconds,
                    water_level_m=stage,
                    depth_m=depth,
                    discharge_m3s=discharge,
                    velocity_m_s=velocity,
                    flow_area_m2=area,
                    wet_area_m2=area,
                    hydraulic_radius_m=hydraulic_radius,
                    top_width_m=top_width,
                    # REZO signs its raw Froude value with flow direction;
                    # the unified contract stores the dimensionless magnitude.
                    froude_number=(abs(row["FR"]) if "FR" in row else None),
                )
            )
            seen_sections.add(section.id)
        if not records:
            raise Hydraulic1DResultError(
                "MASCARET result contains no rows at authoritative Dayu cross sections"
            )
        missing_sections = sorted(
            {item.id for item in sections}.difference(seen_sections)
        )
        if missing_sections:
            raise Hydraulic1DResultError(
                "MASCARET result is missing Dayu cross sections: "
                + ", ".join(missing_sections)
            )
        reference_times = mapped_times_by_section[sections[0].id]
        if any(
            mapped_times_by_section[item.id] != reference_times for item in sections[1:]
        ):
            raise Hydraulic1DResultError(
                "MASCARET result does not cover every Dayu cross section on one time axis"
            )
        observed_times = sorted(reference_times)
        expected_times = model.settings.expected_output_times()
        native_expected_times = (
            model.settings.time_step_seconds,
            *(
                item
                for item in expected_times
                if item > model.settings.time_step_seconds
            ),
        )
        time_tolerance = max(1e-6, model.settings.output_interval_seconds * 1e-9)
        platform_axis = self._same_time_axis(
            observed_times,
            expected_times,
            tolerance=time_tolerance,
        )
        native_axis = self._same_time_axis(
            observed_times,
            native_expected_times,
            tolerance=time_tolerance,
        )
        if not platform_axis and not native_axis:
            raise Hydraulic1DResultError(
                "MASCARET result does not cover the complete expected output time axis"
            )
        branch_rank = {item.id: index for index, item in enumerate(branches)}
        records.sort(
            key=lambda item: (
                float(item.timestamp),
                branch_rank[item.branch_id],
                item.chainage_m,
            )
        )
        native_mass_balance = self._native_mass_balance(
            prepared.workspace / "results.lis"
        )
        return HydraulicResult(
            simulation_id=model.simulation_id,
            scenario_id=model.scenario_id,
            engine=MASCARET_ENGINE_ID,
            engine_version=MASCARET_VERSION,
            records=tuple(records),
            diagnostics={
                "runtime_seconds": runtime_seconds,
                "raw_result_rows": raw_rows,
                "mapped_result_rows": len(records),
                "variable_abbreviations": list(variables),
                "source_format": "opthyca-opt",
                **native_mass_balance,
                # The official native executable stores the first solved time
                # step, then the requested interval; it cannot store t=0.
                "time_axis_mode": "platform-t0" if platform_axis else "mascaret-native",
            },
            # Raw engine files stay private to the job workspace and are deleted
            # after parsing. Durable artifacts require a separate object-store path.
            artifacts=(),
        )

    @staticmethod
    def _native_mass_balance(listing_file: Path) -> dict[str, object]:
        """Read the final global mass report emitted by the official runtime."""

        try:
            content = listing_file.read_text(encoding="iso-8859-1", errors="strict")
        except (OSError, UnicodeError):
            return {}
        relative = findall(
            r"ERREUR RELATIVE\s*:\s*([+-]?[0-9.]+(?:[Ee][+-]?[0-9]+)?)",
            content,
        )
        node_block_pattern = (
            r"BILAN DE MASSE FINAL DANS LE CONFLUENT\s*:\s*"
            r"(\d+)(.*?)(?=\n={20,}|\Z)"
        )
        global_content = sub(node_block_pattern, "", content, flags=DOTALL)
        absolute = findall(
            r"ERREUR SUR LA MASSE D'EAU\s*:\s*([+-]?[0-9.]+(?:[Ee][+-]?[0-9]+)?)",
            global_content,
        )
        if not relative:
            return {}
        result: dict[str, object] = {
            "network_mass_balance_residual": abs(float(relative[-1]))
        }
        if absolute:
            result["network_mass_balance_error_m3"] = abs(float(absolute[-1]))
        node_rows: dict[int, dict[str, float | int]] = {}
        blocks = findall(node_block_pattern, content, flags=DOTALL)
        labels = {
            "initial_volume_m3": r"MASSE D'EAU INITIALE\s*:\s*([+\-0-9.Ee]+)",
            "inflow_volume_m3": r"MASSE D'EAU ENTREE AUX FRONTIERES\s*:\s*([+\-0-9.Ee]+)",
            "outflow_volume_m3": r"MASSE D'EAU SORTIE AUX FRONTIERES\s*:\s*([+\-0-9.Ee]+)",
            "final_volume_m3": r"MASSE D'EAU FINALE\s*:\s*([+\-0-9.Ee]+)",
            "mass_error_m3": r"ERREUR SUR LA MASSE D'EAU\s*:\s*([+\-0-9.Ee]+)",
        }
        for node_number, block in blocks:
            values: dict[str, float | int] = {"mascaret_node_number": int(node_number)}
            for key, pattern in labels.items():
                matches = findall(pattern, block)
                if matches:
                    values[key] = float(matches[-1])
            if "mass_error_m3" not in values:
                continue
            denominator = max(
                (
                    abs(float(values.get(key, 0.0)))
                    for key in (
                        "initial_volume_m3",
                        "inflow_volume_m3",
                        "outflow_volume_m3",
                        "final_volume_m3",
                    )
                ),
                default=1.0,
            )
            values["continuity_residual"] = abs(float(values["mass_error_m3"])) / max(
                denominator, 1.0
            )
            node_rows[int(node_number)] = values
        if node_rows:
            result["node_continuity"] = [node_rows[key] for key in sorted(node_rows)]
            result["node_continuity_residual"] = max(
                float(item["continuity_residual"]) for item in node_rows.values()
            )
        return result

    @staticmethod
    def _same_time_axis(
        observed: list[float],
        expected: tuple[float, ...],
        *,
        tolerance: float,
    ) -> bool:
        """Compare one complete axis without accepting gaps or extra timestamps."""

        return len(observed) == len(expected) and all(
            isclose(left, right, rel_tol=0.0, abs_tol=tolerance)
            for left, right in zip(observed, expected)
        )

    @staticmethod
    def _pair_sum(row: dict[str, float], left: str, right: str) -> float | None:
        """Combine main-channel/floodplain values only when both are declared."""

        if left not in row and right not in row:
            return None
        if left not in row or right not in row:
            raise Hydraulic1DResultError(
                f"MASCARET result must declare {left} and {right} together"
            )
        return row[left] + row[right]

    @staticmethod
    def _variables(lines: list[str]) -> tuple[tuple[str, ...], int]:
        """Read the declared variable order and locate the result section."""

        try:
            variable_start = next(
                index
                for index, value in enumerate(lines)
                if value.strip().lower() == "[variables]"
            )
            result_start = next(
                index
                for index, value in enumerate(
                    lines[variable_start + 1 :], start=variable_start + 1
                )
                if value.strip().lower() == "[resultats]"
            )
        except StopIteration as exc:
            raise Hydraulic1DResultError(
                "MASCARET result requires [variables] followed by [resultats]"
            ) from exc
        abbreviations: list[str] = []
        for line_number, raw in enumerate(
            lines[variable_start + 1 : result_start],
            start=variable_start + 2,
        ):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = next(reader([stripped], delimiter=";", quotechar='"'))
            if len(fields) < 2 or not fields[1].strip():
                raise Hydraulic1DResultError(
                    f"invalid MASCARET variable declaration at line {line_number}"
                )
            abbreviation = fields[1].strip().upper()
            if abbreviation in abbreviations:
                raise Hydraulic1DResultError(
                    f"duplicate MASCARET variable abbreviation: {abbreviation}"
                )
            abbreviations.append(abbreviation)
        if not abbreviations:
            raise Hydraulic1DResultError("MASCARET result declares no variables")
        return tuple(abbreviations), result_start + 1

    @staticmethod
    def _number(value: str, line_number: int, field: str) -> float:
        """Parse one finite number and attach its raw line/field location on failure."""

        try:
            parsed = float(value.strip())
        except ValueError as exc:
            raise Hydraulic1DResultError(
                f"invalid numeric {field} at MASCARET result line {line_number}"
            ) from exc
        if not isfinite(parsed):
            raise Hydraulic1DResultError(
                f"non-finite {field} at MASCARET result line {line_number}"
            )
        return parsed

    @staticmethod
    def _match_section(
        sections: list[HydraulicCrossSection],
        chainage_m: float,
    ) -> HydraulicCrossSection | None:
        """Map only exact authoritative profile locations and ignore interpolated mesh rows."""

        closest = min(sections, key=lambda item: abs(item.chainage_m - chainage_m))
        tolerance = max(1e-6, abs(closest.chainage_m) * 1e-10)
        return closest if abs(closest.chainage_m - chainage_m) <= tolerance else None

    @staticmethod
    def _wet_geometry(section: HydraulicCrossSection, stage_m: float) -> _WetGeometry:
        """Integrate the piecewise-linear profile at the reported water level."""

        points = section.points
        minimum_bed = min(item.elevation_m for item in points)
        if stage_m <= minimum_bed:
            raise Hydraulic1DResultError(
                f"water level does not wet section {section.id!r}: {stage_m:g}"
            )
        if stage_m > min(points[0].elevation_m, points[-1].elevation_m):
            raise Hydraulic1DResultError(
                f"water level exceeds surveyed banks at section {section.id!r}"
            )
        area = 0.0
        perimeter = 0.0
        wet_x: list[float] = []
        for left, right in zip(points, points[1:]):
            width = right.station_m - left.station_m
            left_depth = stage_m - left.elevation_m
            right_depth = stage_m - right.elevation_m
            segment_length = hypot(width, right.elevation_m - left.elevation_m)
            if left_depth > 0.0:
                wet_x.append(left.station_m)
            if right_depth > 0.0:
                wet_x.append(right.station_m)
            if left_depth <= 0.0 and right_depth <= 0.0:
                continue
            if left_depth > 0.0 and right_depth > 0.0:
                area += width * (left_depth + right_depth) / 2.0
                perimeter += segment_length
                continue
            positive_depth = max(left_depth, right_depth)
            negative_depth = min(left_depth, right_depth)
            wet_fraction = positive_depth / (positive_depth - negative_depth)
            wet_width = width * wet_fraction
            area += wet_width * positive_depth / 2.0
            perimeter += segment_length * wet_fraction
            if left_depth > 0.0:
                wet_x.append(left.station_m + wet_width)
            else:
                wet_x.append(right.station_m - wet_width)
        if area <= 0.0 or perimeter <= 0.0 or len(wet_x) < 2:
            raise Hydraulic1DResultError(
                f"cannot derive wet geometry at section {section.id!r}"
            )
        return _WetGeometry(
            area_m2=area,
            top_width_m=max(wet_x) - min(wet_x),
            wetted_perimeter_m=perimeter,
            depth_m=stage_m - minimum_bed,
        )
