"""Parse audited D-Flow FM history NetCDF into the unified hydraulic result."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any, Iterable, Mapping, Sequence

from model.hydraulic_1d.contracts import (
    Hydraulic1DModel,
    HydraulicCrossSection,
    HydraulicResult,
    HydraulicResultRecord,
)
from model.hydraulic_1d.dflow_fm.adapter import (
    DFLOW_ENGINE_ID,
    DFLOW_ENGINE_VERSION,
    DFLOW_NATIVE_VERSION,
    DFLOW_TIME_UNIT,
    DFlowFMPreparedCase,
)
from model.hydraulic_1d.errors import (
    Hydraulic1DResultError,
    Hydraulic1DRuntimeUnavailable,
)


@dataclass(frozen=True, slots=True)
class DFlowFMResultMapping:
    """Declare exact variable and dimension names for one audited HIS contract.

    The defaults are the names documented by the D-Flow FM 2026.02 history-file
    contract.  A different upstream build must provide a complete explicit mapping;
    the parser never scans for similarly named variables or nearest locations.
    """

    time_dimension: str = "time"
    time_variable: str = "time"
    expected_time_unit: str = DFLOW_TIME_UNIT
    station_dimension: str = "stations"
    station_id_variable: str = "station_name"
    water_level_variable: str = "waterlevel"
    water_level_unit: str = "m"
    cross_section_dimension: str = "cross_section"
    cross_section_id_variable: str = "cross_section_name"
    discharge_variable: str = "cross_section_discharge"
    discharge_unit: str = "m3 s-1"
    flow_area_variable: str = "cross_section_area"
    flow_area_unit: str = "m2"
    velocity_variable: str = "cross_section_velocity"
    velocity_unit: str = "m s-1"


class DFlowFMResultParser:
    """Read only exact Dayu observation IDs on one complete HIS time axis."""

    def __init__(self, mapping: DFlowFMResultMapping | None = None) -> None:
        self.mapping = mapping or DFlowFMResultMapping()

    def parse(
        self,
        model: Hydraulic1DModel,
        prepared: DFlowFMPreparedCase,
        *,
        runtime_seconds: float,
    ) -> HydraulicResult:
        """Open a real NetCDF through xarray and parse it under the strict contract."""

        result_file = prepared.result_file
        if not result_file.is_file():
            raise Hydraulic1DResultError(
                f"D-Flow history result is missing: {result_file.name}",
                code="DFLOW_RESULT_MISSING",
            )
        try:
            if result_file.stat().st_size <= 0:
                raise Hydraulic1DResultError(
                    "D-Flow history result is empty",
                    code="DFLOW_RESULT_CORRUPT",
                )
        except OSError as exc:
            raise Hydraulic1DResultError(
                f"cannot inspect D-Flow history result: {exc}",
                code="DFLOW_RESULT_CORRUPT",
            ) from exc
        try:
            import xarray as xr
        except ImportError as exc:
            raise Hydraulic1DRuntimeUnavailable(
                "xarray is required to parse D-Flow NetCDF results",
                code="DFLOW_RESULT_READER_NOT_AVAILABLE",
            ) from exc
        try:
            with xr.open_dataset(
                result_file,
                decode_times=False,
                mask_and_scale=True,
                decode_cf=True,
            ) as dataset:
                return self.parse_dataset(
                    model,
                    prepared,
                    dataset,
                    runtime_seconds=runtime_seconds,
                )
        except (Hydraulic1DResultError, Hydraulic1DRuntimeUnavailable):
            raise
        except Exception as exc:
            raise Hydraulic1DResultError(
                f"cannot open D-Flow history NetCDF: {exc}",
                code="DFLOW_RESULT_CORRUPT",
            ) from exc

    def parse_dataset(
        self,
        model: Hydraulic1DModel,
        prepared: DFlowFMPreparedCase,
        dataset: Any,
        *,
        runtime_seconds: float,
    ) -> HydraulicResult:
        """Parse an xarray-compatible dataset; used by real and contract tests."""

        mapping = self.mapping
        variables = self._variables(dataset)
        required = {
            mapping.time_variable,
            mapping.station_id_variable,
            mapping.water_level_variable,
            mapping.cross_section_id_variable,
            mapping.discharge_variable,
            mapping.flow_area_variable,
            mapping.velocity_variable,
        }
        missing = sorted(required.difference(variables))
        if missing:
            raise Hydraulic1DResultError(
                "D-Flow history result lacks required variables: " + ", ".join(missing),
                code="DFLOW_RESULT_VARIABLE_MISSING",
            )
        time_variable = variables[mapping.time_variable]
        self._require_dims(
            time_variable,
            (mapping.time_dimension,),
            name=mapping.time_variable,
        )
        self._require_unit(
            time_variable,
            mapping.expected_time_unit,
            name=mapping.time_variable,
        )
        times = self._finite_vector(time_variable, name=mapping.time_variable)
        self._validate_time_axis(model, times)

        station_ids = self._ids(
            variables[mapping.station_id_variable],
            dimension=mapping.station_dimension,
            name=mapping.station_id_variable,
        )
        cross_section_ids = self._ids(
            variables[mapping.cross_section_id_variable],
            dimension=mapping.cross_section_dimension,
            name=mapping.cross_section_id_variable,
        )
        station_index = self._id_index(station_ids, label="station")
        cross_section_index = self._id_index(
            cross_section_ids,
            label="cross section",
        )
        expected_sections = self._ordered_sections(model)
        expected_ids = {item.id for item in expected_sections}
        missing_stations = sorted(expected_ids.difference(station_index))
        missing_cross_sections = sorted(expected_ids.difference(cross_section_index))
        unexpected_stations = sorted(set(station_index).difference(expected_ids))
        unexpected_cross_sections = sorted(
            set(cross_section_index).difference(expected_ids)
        )
        if missing_stations or missing_cross_sections:
            raise Hydraulic1DResultError(
                (
                    "D-Flow history result is missing authoritative Dayu IDs: "
                    f"stations={missing_stations}; cross_sections={missing_cross_sections}"
                ),
                code="DFLOW_RESULT_LOCATION_MISSING",
            )
        if unexpected_stations or unexpected_cross_sections:
            raise Hydraulic1DResultError(
                (
                    "D-Flow history result contains unauthoritative location IDs: "
                    f"stations={unexpected_stations}; "
                    f"cross_sections={unexpected_cross_sections}"
                ),
                code="DFLOW_RESULT_LOCATION_UNEXPECTED",
            )

        water_level = variables[mapping.water_level_variable]
        discharge = variables[mapping.discharge_variable]
        flow_area = variables[mapping.flow_area_variable]
        velocity = variables[mapping.velocity_variable]
        self._require_matrix(
            water_level,
            mapping.time_dimension,
            mapping.station_dimension,
            len(times),
            len(station_ids),
            name=mapping.water_level_variable,
        )
        for variable, name in (
            (discharge, mapping.discharge_variable),
            (flow_area, mapping.flow_area_variable),
            (velocity, mapping.velocity_variable),
        ):
            self._require_matrix(
                variable,
                mapping.time_dimension,
                mapping.cross_section_dimension,
                len(times),
                len(cross_section_ids),
                name=name,
            )
        self._require_unit(
            water_level,
            mapping.water_level_unit,
            name=mapping.water_level_variable,
        )
        self._require_unit(
            discharge,
            mapping.discharge_unit,
            name=mapping.discharge_variable,
        )
        self._require_unit(
            flow_area,
            mapping.flow_area_unit,
            name=mapping.flow_area_variable,
        )
        self._require_unit(
            velocity,
            mapping.velocity_unit,
            name=mapping.velocity_variable,
        )

        branch_rank = {
            item.id: index
            for index, item in enumerate(
                sorted(model.branches, key=lambda item: (item.code, item.id))
            )
        }
        records: list[HydraulicResultRecord] = []
        for time_index, timestamp in enumerate(times):
            for section in expected_sections:
                station_column = station_index[section.id]
                cross_section_column = cross_section_index[section.id]
                stage = self._matrix_number(
                    water_level,
                    time_index,
                    station_column,
                    name=mapping.water_level_variable,
                    section_id=section.id,
                    timestamp=timestamp,
                )
                q = self._matrix_number(
                    discharge,
                    time_index,
                    cross_section_column,
                    name=mapping.discharge_variable,
                    section_id=section.id,
                    timestamp=timestamp,
                )
                area = self._matrix_number(
                    flow_area,
                    time_index,
                    cross_section_column,
                    name=mapping.flow_area_variable,
                    section_id=section.id,
                    timestamp=timestamp,
                )
                speed = self._matrix_number(
                    velocity,
                    time_index,
                    cross_section_column,
                    name=mapping.velocity_variable,
                    section_id=section.id,
                    timestamp=timestamp,
                )
                if area < 0.0:
                    raise Hydraulic1DResultError(
                        f"negative flow area at {section.id!r}, t={timestamp:g}",
                        code="DFLOW_RESULT_PHYSICS_INVALID",
                    )
                minimum_bed = min(float(item.elevation_m) for item in section.points)
                depth = stage - minimum_bed
                if depth < -1e-9:
                    raise Hydraulic1DResultError(
                        f"water level lies below the surveyed bed at {section.id!r}",
                        code="DFLOW_RESULT_PHYSICS_INVALID",
                    )
                depth = max(0.0, depth)
                self._validate_flow_identity(
                    q,
                    area,
                    speed,
                    section_id=section.id,
                    timestamp=timestamp,
                )
                geometry = self._wet_geometry(section, stage)
                records.append(
                    HydraulicResultRecord(
                        simulation_id=model.simulation_id,
                        scenario_id=model.scenario_id,
                        engine=DFLOW_ENGINE_ID,
                        engine_version=DFLOW_ENGINE_VERSION,
                        branch_id=section.branch_id,
                        chainage_m=section.chainage_m,
                        cross_section_id=section.id,
                        timestamp=timestamp,
                        water_level_m=stage,
                        depth_m=depth,
                        discharge_m3s=q,
                        velocity_m_s=speed,
                        flow_area_m2=area,
                        wet_area_m2=area,
                        hydraulic_radius_m=None,
                        top_width_m=geometry[0],
                        froude_number=None,
                    )
                )
        records.sort(
            key=lambda item: (
                float(item.timestamp),
                branch_rank[item.branch_id],
                item.chainage_m,
            )
        )
        attrs = getattr(dataset, "attrs", {})
        source = attrs.get("source") if isinstance(attrs, Mapping) else None
        return HydraulicResult(
            simulation_id=model.simulation_id,
            scenario_id=model.scenario_id,
            engine=DFLOW_ENGINE_ID,
            engine_version=DFLOW_ENGINE_VERSION,
            records=tuple(records),
            diagnostics={
                "runtime_seconds": runtime_seconds,
                "source_format": "d-flow-fm-history-netcdf",
                "native_engine_version": DFLOW_NATIVE_VERSION,
                "native_source": str(source) if source is not None else None,
                "mapped_result_rows": len(records),
                "time_count": len(times),
                "station_count": len(station_ids),
                "cross_section_count": len(cross_section_ids),
                "variable_mapping": {
                    "water_level": mapping.water_level_variable,
                    "discharge": mapping.discharge_variable,
                    "flow_area": mapping.flow_area_variable,
                    "velocity": mapping.velocity_variable,
                },
                "prepared_manifest": prepared.manifest_file.name,
            },
            artifacts=(),
        )

    @staticmethod
    def _variables(dataset: Any) -> Mapping[str, Any]:
        variables = getattr(dataset, "variables", None)
        if not isinstance(variables, Mapping):
            raise Hydraulic1DResultError(
                "result reader did not return an xarray-compatible variable mapping",
                code="DFLOW_RESULT_CORRUPT",
            )
        return variables

    @staticmethod
    def _dims(variable: Any) -> tuple[str, ...]:
        dims = getattr(variable, "dims", None)
        if not isinstance(dims, tuple):
            try:
                return tuple(dims)
            except (TypeError, ValueError) as exc:
                raise Hydraulic1DResultError(
                    "NetCDF variable has no readable dimensions",
                    code="DFLOW_RESULT_CORRUPT",
                ) from exc
        return dims

    def _require_dims(
        self,
        variable: Any,
        expected: tuple[str, ...],
        *,
        name: str,
    ) -> None:
        actual = self._dims(variable)
        if actual != expected:
            raise Hydraulic1DResultError(
                f"D-Flow variable {name!r} dimensions {actual!r} != {expected!r}",
                code="DFLOW_RESULT_DIMENSION_INVALID",
            )

    def _require_matrix(
        self,
        variable: Any,
        time_dimension: str,
        location_dimension: str,
        expected_times: int,
        expected_locations: int,
        *,
        name: str,
    ) -> None:
        self._require_dims(
            variable,
            (time_dimension, location_dimension),
            name=name,
        )
        shape = tuple(getattr(variable, "shape", ()))
        if shape != (expected_times, expected_locations):
            raise Hydraulic1DResultError(
                (
                    f"D-Flow variable {name!r} shape {shape!r} != "
                    f"{(expected_times, expected_locations)!r}"
                ),
                code="DFLOW_RESULT_DIMENSION_INVALID",
            )

    @staticmethod
    def _attrs(variable: Any) -> Mapping[str, Any]:
        attrs = getattr(variable, "attrs", None)
        return attrs if isinstance(attrs, Mapping) else {}

    def _require_unit(self, variable: Any, expected: str, *, name: str) -> None:
        actual = self._attrs(variable).get("units")
        if actual != expected:
            raise Hydraulic1DResultError(
                f"D-Flow variable {name!r} unit {actual!r} != {expected!r}",
                code="DFLOW_RESULT_UNIT_INVALID",
            )

    def _finite_vector(self, variable: Any, *, name: str) -> tuple[float, ...]:
        values = self._to_python(getattr(variable, "values", None))
        if not isinstance(values, list):
            raise Hydraulic1DResultError(
                f"D-Flow variable {name!r} is not a vector",
                code="DFLOW_RESULT_DIMENSION_INVALID",
            )
        result: list[float] = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise Hydraulic1DResultError(
                    f"D-Flow variable {name!r} contains a non-numeric value",
                    code="DFLOW_RESULT_CORRUPT",
                ) from exc
            if not isfinite(number):
                raise Hydraulic1DResultError(
                    f"D-Flow variable {name!r} contains a non-finite value",
                    code="DFLOW_RESULT_CORRUPT",
                )
            result.append(number)
        return tuple(result)

    def _ids(self, variable: Any, *, dimension: str, name: str) -> tuple[str, ...]:
        dims = self._dims(variable)
        values = self._to_python(getattr(variable, "values", None))
        if dims == (dimension,):
            if not isinstance(values, list):
                raise Hydraulic1DResultError(
                    f"D-Flow id variable {name!r} is not a vector",
                    code="DFLOW_RESULT_DIMENSION_INVALID",
                )
            raw_ids: Iterable[Any] = values
        elif len(dims) == 2 and dims[0] == dimension:
            if not isinstance(values, list):
                raise Hydraulic1DResultError(
                    f"D-Flow id variable {name!r} is not a character matrix",
                    code="DFLOW_RESULT_DIMENSION_INVALID",
                )
            raw_ids = [self._join_characters(item) for item in values]
        else:
            raise Hydraulic1DResultError(
                f"D-Flow id variable {name!r} has unexpected dimensions {dims!r}",
                code="DFLOW_RESULT_DIMENSION_INVALID",
            )
        result = tuple(self._decode_id(value, name=name) for value in raw_ids)
        if any(not item for item in result):
            raise Hydraulic1DResultError(
                f"D-Flow id variable {name!r} contains a blank identifier",
                code="DFLOW_RESULT_LOCATION_INVALID",
            )
        return result

    @classmethod
    def _join_characters(cls, value: Any) -> bytes | str:
        converted = cls._to_python(value)
        if not isinstance(converted, list):
            return converted
        if all(isinstance(item, bytes) for item in converted):
            return b"".join(converted)
        if all(isinstance(item, str) for item in converted):
            return "".join(converted)
        raise Hydraulic1DResultError(
            "D-Flow identifier character matrix contains mixed value types",
            code="DFLOW_RESULT_LOCATION_INVALID",
        )

    @staticmethod
    def _decode_id(value: Any, *, name: str) -> str:
        if isinstance(value, bytes):
            try:
                result = value.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise Hydraulic1DResultError(
                    f"D-Flow id variable {name!r} contains invalid UTF-8",
                    code="DFLOW_RESULT_LOCATION_INVALID",
                ) from exc
        elif isinstance(value, str):
            result = value
        else:
            raise Hydraulic1DResultError(
                f"D-Flow id variable {name!r} contains a non-string identifier",
                code="DFLOW_RESULT_LOCATION_INVALID",
            )
        return result.rstrip("\x00 ")

    @staticmethod
    def _id_index(values: Sequence[str], *, label: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for index, value in enumerate(values):
            if value in result:
                raise Hydraulic1DResultError(
                    f"D-Flow history result repeats {label} id {value!r}",
                    code="DFLOW_RESULT_LOCATION_DUPLICATE",
                )
            result[value] = index
        return result

    @staticmethod
    def _to_python(value: Any) -> Any:
        if hasattr(value, "tolist"):
            return value.tolist()
        return value

    def _matrix_number(
        self,
        variable: Any,
        time_index: int,
        location_index: int,
        *,
        name: str,
        section_id: str,
        timestamp: float,
    ) -> float:
        values = getattr(variable, "values", None)
        try:
            value = values[time_index, location_index]
        except (IndexError, KeyError, TypeError) as exc:
            raise Hydraulic1DResultError(
                f"D-Flow variable {name!r} cannot be indexed by time/location",
                code="DFLOW_RESULT_CORRUPT",
            ) from exc
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise Hydraulic1DResultError(
                (
                    f"D-Flow variable {name!r} is non-numeric at "
                    f"{section_id!r}, t={timestamp:g}"
                ),
                code="DFLOW_RESULT_CORRUPT",
            ) from exc
        if not isfinite(number):
            raise Hydraulic1DResultError(
                (
                    f"D-Flow variable {name!r} is non-finite at "
                    f"{section_id!r}, t={timestamp:g}"
                ),
                code="DFLOW_RESULT_CORRUPT",
            )
        return number

    @staticmethod
    def _validate_time_axis(model: Hydraulic1DModel, observed: Sequence[float]) -> None:
        expected = model.settings.expected_output_times()
        tolerance = max(1e-6, float(model.settings.output_interval_seconds) * 1e-9)
        if len(observed) != len(expected) or any(
            not isclose(left, right, rel_tol=0.0, abs_tol=tolerance)
            for left, right in zip(observed, expected)
        ):
            raise Hydraulic1DResultError(
                "D-Flow history result does not cover the complete expected output time axis",
                code="DFLOW_RESULT_TIME_AXIS_INVALID",
            )

    @staticmethod
    def _validate_flow_identity(
        discharge: float,
        area: float,
        velocity: float,
        *,
        section_id: str,
        timestamp: float,
    ) -> None:
        if area == 0.0:
            if abs(discharge) > 1e-9 or abs(velocity) > 1e-9:
                raise Hydraulic1DResultError(
                    f"nonzero flow through zero area at {section_id!r}, t={timestamp:g}",
                    code="DFLOW_RESULT_PHYSICS_INVALID",
                )
            return
        reconstructed = area * velocity
        tolerance = max(1e-6, abs(discharge) * 1e-6)
        if not isclose(discharge, reconstructed, rel_tol=0.0, abs_tol=tolerance):
            raise Hydraulic1DResultError(
                (
                    f"Q != A*V at {section_id!r}, t={timestamp:g}: "
                    f"{discharge:g} != {reconstructed:g}"
                ),
                code="DFLOW_RESULT_FLOW_IDENTITY_INVALID",
            )

    @staticmethod
    def _wet_geometry(
        section: HydraulicCrossSection,
        stage_m: float,
    ) -> tuple[float | None, float]:
        """Derive top width/depth from the authoritative profile without solver data."""

        minimum_bed = min(float(item.elevation_m) for item in section.points)
        if stage_m <= minimum_bed:
            return None, max(0.0, stage_m - minimum_bed)
        intersections: list[float] = []
        for left, right in zip(section.points, section.points[1:]):
            left_depth = stage_m - float(left.elevation_m)
            right_depth = stage_m - float(right.elevation_m)
            if left_depth >= 0.0:
                intersections.append(float(left.station_m))
            if right_depth >= 0.0:
                intersections.append(float(right.station_m))
            if left_depth * right_depth < 0.0:
                fraction = left_depth / (left_depth - right_depth)
                intersections.append(
                    float(left.station_m)
                    + fraction * float(right.station_m - left.station_m)
                )
        top_width = (
            max(intersections) - min(intersections) if len(intersections) >= 2 else None
        )
        return top_width, stage_m - minimum_bed

    @staticmethod
    def _ordered_sections(model: Hydraulic1DModel) -> tuple[HydraulicCrossSection, ...]:
        branch_order = {
            branch.id: index
            for index, branch in enumerate(
                sorted(model.branches, key=lambda item: (item.code, item.id))
            )
        }
        return tuple(
            sorted(
                model.cross_sections,
                key=lambda item: (branch_order[item.branch_id], item.chainage_m),
            )
        )


__all__ = ["DFlowFMResultMapping", "DFlowFMResultParser"]
