"""Parse audited D-Flow FM history NetCDF into the unified hydraulic result."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isclose, isfinite
from pathlib import Path
from shutil import copyfile
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
    DFlowFMPreparedCase,
)
from model.hydraulic_1d.errors import (
    Hydraulic1DResultError,
    Hydraulic1DRuntimeUnavailable,
)


DFLOW_HISTORY_TIME_UNIT = "seconds since 2020-01-01 00:00:00 +00:00"


@dataclass(frozen=True, slots=True)
class DFlowFMGateSample:
    """One exact Orifice/Gate history record from D-Flow FM 2026.02."""

    time_seconds: float
    structure_id: str
    discharge_m3s: float | None
    crest_level_m: float
    crest_width_m: float
    gate_lower_edge_level_m: float
    actual_opening_m: float
    upstream_water_level_m: float
    downstream_water_level_m: float
    head_difference_m: float
    flow_area_m2: float | None
    velocity_mps: float | None


@dataclass(frozen=True, slots=True)
class DFlowFMPumpSample:
    """One exact non-staged Pump history record from D-Flow FM 2026.02."""

    time_seconds: float
    structure_id: str
    actual_discharge_m3s: float
    native_applied_capacity_m3s: float
    oriented_discharge_m3s: float
    intake_water_level_m: float
    outlet_water_level_m: float
    structure_head_difference_m: float
    pump_head_m: float
    reduction_factor: float
    delivery_water_level_m: float
    suction_water_level_m: float
    active_stage: int | None


@dataclass(frozen=True, slots=True)
class DFlowFMMassBalance:
    """Global cumulative balance plus separately reported internal Gate transfer."""

    inflow_m3: float
    outflow_m3: float
    storage_change_m3: float
    structure_transfer_m3: float
    residual_m3: float
    relative_residual: float
    native_max_abs_volume_error_m3: float


@dataclass(frozen=True, slots=True)
class DFlowFMResultMapping:
    """Declare exact variable and dimension names for one audited HIS contract.

    The defaults are the names documented by the D-Flow FM 2026.02 history-file
    contract.  A different upstream build must provide a complete explicit mapping;
    the parser never scans for similarly named variables or nearest locations.
    """

    time_dimension: str = "time"
    time_variable: str = "time"
    expected_time_unit: str = DFLOW_HISTORY_TIME_UNIT
    station_dimension: str = "station"
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


class _MaterializedNetCDFVariable:
    """Expose one netCDF4 variable through the strict parser's tiny interface."""

    def __init__(self, variable: Any) -> None:
        self.dims = tuple(variable.dimensions)
        self.shape = tuple(variable.shape)
        self.attrs = {
            name: variable.getncattr(name) for name in variable.ncattrs()
        }
        self.values = variable[:]


class _MaterializedNetCDFDataset:
    """Detach required data from a native Dataset before closing the file."""

    def __init__(self, dataset: Any) -> None:
        self.variables = {
            name: _MaterializedNetCDFVariable(variable)
            for name, variable in dataset.variables.items()
        }
        self.attrs = {name: dataset.getncattr(name) for name in dataset.ncattrs()}


def _open_unicode_windows_netcdf(result_file: Path, owner_token: str) -> Any:
    """Read a Unicode-path HIS file via a unique ASCII relative staging name."""

    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise Hydraulic1DRuntimeUnavailable(
            "netCDF4 is required to parse D-Flow NetCDF results on Windows",
            code="DFLOW_RESULT_READER_NOT_AVAILABLE",
        ) from exc
    repository_root = Path(__file__).resolve().parents[3]
    current_directory = Path.cwd().resolve()
    if not current_directory.is_relative_to(repository_root):
        raise Hydraulic1DResultError(
            "D-Flow result parsing must run from inside the Dayu repository",
            code="DFLOW_RESULT_PATH_UNAVAILABLE",
        )
    relative_directory = (
        Path("outputs") / "dflow-native-io" / f"{owner_token}-result"
    )
    absolute_directory = current_directory / relative_directory
    absolute_directory.mkdir(parents=True, exist_ok=False)
    staged_relative = relative_directory / result_file.name
    staged_absolute = current_directory / staged_relative
    try:
        copyfile(result_file, staged_absolute)
        with Dataset(staged_relative, mode="r") as dataset:
            return _MaterializedNetCDFDataset(dataset)
    finally:
        if staged_absolute.exists():
            staged_absolute.unlink()
        if absolute_directory.exists():
            absolute_directory.rmdir()


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
        if any(not character.isascii() for character in str(result_file)):
            owner_token = sha256(
                str(result_file.resolve()).encode("utf-8")
            ).hexdigest()
            try:
                dataset = _open_unicode_windows_netcdf(result_file, owner_token)
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

    def parse_gate_and_mass_balance(
        self,
        prepared: DFlowFMPreparedCase,
        *,
        expected_structure_id: str,
    ) -> tuple[tuple[DFlowFMGateSample, ...], DFlowFMMassBalance]:
        """Parse only the exact 2026.02 Orifice and balance variables.

        D-Flow emits an undefined discharge at the initialization sample.  It is
        represented as ``None`` only at ``t=0``; every active sample must be
        finite.  No similarly named variable fallback is permitted.
        """

        result_file = prepared.result_file
        if not result_file.is_file():
            raise Hydraulic1DResultError(
                f"D-Flow history result is missing: {result_file.name}",
                code="DFLOW_RESULT_MISSING",
            )
        owner_token = sha256(str(result_file.resolve()).encode("utf-8")).hexdigest()
        try:
            if any(not character.isascii() for character in str(result_file)):
                dataset = _open_unicode_windows_netcdf(result_file, owner_token)
            else:
                from netCDF4 import Dataset

                with Dataset(result_file, mode="r") as source:
                    dataset = _MaterializedNetCDFDataset(source)
            return self.parse_gate_and_mass_balance_dataset(
                dataset,
                expected_structure_id=expected_structure_id,
            )
        except Hydraulic1DResultError:
            raise
        except Exception as exc:
            raise Hydraulic1DResultError(
                f"cannot parse D-Flow Gate history: {exc}",
                code="DFLOW_RESULT_CORRUPT",
            ) from exc

    def parse_gate_and_mass_balance_dataset(
        self,
        dataset: Any,
        *,
        expected_structure_id: str,
    ) -> tuple[tuple[DFlowFMGateSample, ...], DFlowFMMassBalance]:
        """Parse a materialized or test dataset under the exact native schema."""

        variables = self._variables(dataset)
        units = {
            "orifice_discharge": "m3 s-1",
            "orifice_crest_level": "m",
            "orifice_crest_width": "m",
            "orifice_gate_lower_edge_level": "m",
            "orifice_gate_opening_height": "m",
            "orifice_s1up": "m",
            "orifice_s1dn": "m",
            "orifice_head": "m",
            "orifice_flow_area": "m2",
            "orifice_velocity": "m s-1",
            "water_balance_storage": "m3",
            "water_balance_volume_error": "m3",
            "water_balance_boundaries_in": "m3",
            "water_balance_boundaries_out": "m3",
        }
        required = {"time", "orifice_name", *units}
        missing = sorted(required.difference(variables))
        if missing:
            raise Hydraulic1DResultError(
                "D-Flow Gate result lacks required variables: " + ", ".join(missing),
                code="DFLOW_RESULT_SCHEMA_MISMATCH",
            )
        time = self._finite_vector(variables["time"], name="time")
        self._require_dims(variables["time"], ("time",), name="time")
        self._require_unit(
            variables["time"],
            DFLOW_HISTORY_TIME_UNIT,
            name="time",
        )
        ids = self._ids(
            variables["orifice_name"],
            dimension="orifice",
            name="orifice_name",
        )
        if ids != (expected_structure_id,):
            raise Hydraulic1DResultError(
                "D-Flow Gate structure identity does not match the frozen model",
                code="DFLOW_RESULT_IDENTITY_MISMATCH",
            )
        values: dict[str, Any] = {}
        for name, expected_unit in units.items():
            variable = variables[name]
            self._require_unit(variable, expected_unit, name=name)
            if name.startswith("orifice_"):
                self._require_dims(variable, ("time", "orifice"), name=name)
                self._require_matrix(
                    variable,
                    "time",
                    "orifice",
                    len(time),
                    1,
                    name=name,
                )
                values[name] = variable
            else:
                self._require_dims(variable, ("time",), name=name)
                values[name] = self._finite_vector(variable, name=name)

        samples: list[DFlowFMGateSample] = []
        for index, current_time in enumerate(time):
            raw_discharge = values["orifice_discharge"].values[index, 0]
            if bool(getattr(raw_discharge, "mask", False)):
                discharge_raw = float("nan")
            else:
                try:
                    discharge_raw = float(raw_discharge)
                except (TypeError, ValueError) as exc:
                    raise Hydraulic1DResultError(
                        "D-Flow Gate discharge contains a non-numeric value",
                        code="DFLOW_RESULT_CORRUPT",
                    ) from exc
            if not isfinite(discharge_raw):
                if index == 0 and isclose(current_time, 0.0, abs_tol=1e-12):
                    discharge_raw = None
                else:
                    raise Hydraulic1DResultError(
                        "active D-Flow Gate discharge is non-finite",
                        code="DFLOW_RESULT_NONFINITE",
                    )
            sample_values: dict[str, float | None] = {}
            for name in units:
                if not name.startswith("orifice_") or name == "orifice_discharge":
                    continue
                raw_value = values[name].values[index, 0]
                if bool(getattr(raw_value, "mask", False)):
                    number = float("nan")
                else:
                    try:
                        number = float(raw_value)
                    except (TypeError, ValueError) as exc:
                        raise Hydraulic1DResultError(
                            f"D-Flow variable {name!r} contains a non-numeric value",
                            code="DFLOW_RESULT_CORRUPT",
                        ) from exc
                if isfinite(number):
                    sample_values[name] = number
                elif (
                    index == 0
                    and isclose(current_time, 0.0, abs_tol=1e-12)
                    and name in {"orifice_flow_area", "orifice_velocity"}
                ):
                    sample_values[name] = None
                else:
                    raise Hydraulic1DResultError(
                        f"D-Flow variable {name!r} is non-finite during active simulation",
                        code="DFLOW_RESULT_NONFINITE",
                    )
            samples.append(
                DFlowFMGateSample(
                    time_seconds=current_time,
                    structure_id=expected_structure_id,
                    discharge_m3s=discharge_raw,
                    crest_level_m=float(sample_values["orifice_crest_level"]),
                    crest_width_m=float(sample_values["orifice_crest_width"]),
                    gate_lower_edge_level_m=sample_values[
                        "orifice_gate_lower_edge_level"
                    ],
                    actual_opening_m=float(sample_values["orifice_gate_opening_height"]),
                    upstream_water_level_m=float(sample_values["orifice_s1up"]),
                    downstream_water_level_m=float(sample_values["orifice_s1dn"]),
                    head_difference_m=float(sample_values["orifice_head"]),
                    flow_area_m2=sample_values["orifice_flow_area"],
                    velocity_mps=sample_values["orifice_velocity"],
                )
            )
        if len(samples) < 2:
            raise Hydraulic1DResultError(
                "D-Flow Gate result requires at least two time samples",
                code="DFLOW_RESULT_SCHEMA_MISMATCH",
            )
        transfer = 0.0
        for previous, current in zip(samples, samples[1:], strict=False):
            q0 = previous.discharge_m3s
            q1 = current.discharge_m3s
            if q1 is None:
                raise Hydraulic1DResultError(
                    "active D-Flow Gate discharge is undefined",
                    code="DFLOW_RESULT_NONFINITE",
                )
            if q0 is None:
                q0 = 0.0
            transfer += 0.5 * (q0 + q1) * (
                current.time_seconds - previous.time_seconds
            )
        inflow = values["water_balance_boundaries_in"]  # type: ignore[assignment]
        outflow = values["water_balance_boundaries_out"]  # type: ignore[assignment]
        storage = values["water_balance_storage"]  # type: ignore[assignment]
        errors = values["water_balance_volume_error"]  # type: ignore[assignment]
        inflow_delta = float(inflow[-1] - inflow[0])
        outflow_delta = float(outflow[-1] - outflow[0])
        storage_delta = float(storage[-1] - storage[0])
        residual = float(errors[-1] - errors[0])
        denominator = max(abs(inflow_delta), abs(outflow_delta), abs(storage_delta), 1.0)
        balance = DFlowFMMassBalance(
            inflow_m3=inflow_delta,
            outflow_m3=outflow_delta,
            storage_change_m3=storage_delta,
            structure_transfer_m3=transfer,
            residual_m3=residual,
            relative_residual=abs(residual) / denominator,
            native_max_abs_volume_error_m3=max(abs(float(value)) for value in errors),
        )
        return tuple(samples), balance

    def parse_pump_and_mass_balance(
        self,
        prepared: DFlowFMPreparedCase,
        *,
        expected_structure_id: str,
    ) -> tuple[tuple[DFlowFMPumpSample, ...], DFlowFMMassBalance]:
        """Parse the exact non-staged Pump variables and cumulative balance."""

        result_file = prepared.result_file
        if not result_file.is_file():
            raise Hydraulic1DResultError(
                f"D-Flow history result is missing: {result_file.name}",
                code="DFLOW_RESULT_MISSING",
            )
        owner_token = sha256(str(result_file.resolve()).encode("utf-8")).hexdigest()
        try:
            if any(not character.isascii() for character in str(result_file)):
                dataset = _open_unicode_windows_netcdf(result_file, owner_token)
            else:
                from netCDF4 import Dataset

                with Dataset(result_file, mode="r") as source:
                    dataset = _MaterializedNetCDFDataset(source)
            return self.parse_pump_and_mass_balance_dataset(
                dataset,
                expected_structure_id=expected_structure_id,
            )
        except Hydraulic1DResultError:
            raise
        except Exception as exc:
            raise Hydraulic1DResultError(
                f"cannot parse D-Flow Pump history: {exc}",
                code="DFLOW_RESULT_CORRUPT",
            ) from exc

    def parse_pump_and_mass_balance_dataset(
        self,
        dataset: Any,
        *,
        expected_structure_id: str,
    ) -> tuple[tuple[DFlowFMPumpSample, ...], DFlowFMMassBalance]:
        """Validate only the pinned native Pump schema; no name fallback is allowed."""

        variables = self._variables(dataset)
        units = {
            "pump_structure_discharge": "m3 s-1",
            "pump_capacity": "m3 s-1",
            "pump_discharge_dir": "m3 s-1",
            "pump_s1up": "m",
            "pump_s1dn": "m",
            "pump_structure_head": "m",
            "pump_actual_stage": "",
            "pump_head": "m",
            "pump_reduction_factor": "1",
            "pump_s1_delivery_side": "m",
            "pump_s1_suction_side": "m",
            "water_balance_storage": "m3",
            "water_balance_volume_error": "m3",
            "water_balance_boundaries_in": "m3",
            "water_balance_boundaries_out": "m3",
        }
        required = {"time", "pump_name", *units}
        missing = sorted(required.difference(variables))
        if missing:
            raise Hydraulic1DResultError(
                "D-Flow Pump result lacks required variables: " + ", ".join(missing),
                code="DFLOW_RESULT_SCHEMA_MISMATCH",
            )
        time = self._finite_vector(variables["time"], name="time")
        self._require_dims(variables["time"], ("time",), name="time")
        self._require_unit(
            variables["time"],
            DFLOW_HISTORY_TIME_UNIT,
            name="time",
        )
        ids = self._ids(
            variables["pump_name"],
            dimension="pump",
            name="pump_name",
        )
        if ids != (expected_structure_id,):
            raise Hydraulic1DResultError(
                "D-Flow Pump structure identity does not match the frozen model",
                code="DFLOW_RESULT_IDENTITY_MISMATCH",
            )
        values: dict[str, Any] = {}
        for name, expected_unit in units.items():
            variable = variables[name]
            self._require_unit(variable, expected_unit, name=name)
            if name.startswith("pump_"):
                self._require_matrix(
                    variable,
                    "time",
                    "pump",
                    len(time),
                    1,
                    name=name,
                )
                values[name] = variable
            else:
                self._require_dims(variable, ("time",), name=name)
                values[name] = self._finite_vector(variable, name=name)

        samples: list[DFlowFMPumpSample] = []
        finite_names = tuple(
            name for name in units if name.startswith("pump_") and name != "pump_actual_stage"
        )
        for index, current_time in enumerate(time):
            sample_values: dict[str, float] = {}
            for name in finite_names:
                raw_value = values[name].values[index, 0]
                try:
                    number = (
                        float("nan")
                        if bool(getattr(raw_value, "mask", False))
                        else float(raw_value)
                    )
                except (TypeError, ValueError) as exc:
                    raise Hydraulic1DResultError(
                        f"D-Flow variable {name!r} contains a non-numeric value",
                        code="DFLOW_RESULT_CORRUPT",
                    ) from exc
                if not isfinite(number):
                    raise Hydraulic1DResultError(
                        f"D-Flow variable {name!r} is non-finite",
                        code="DFLOW_RESULT_NONFINITE",
                    )
                sample_values[name] = number
            raw_stage = values["pump_actual_stage"].values[index, 0]
            if bool(getattr(raw_stage, "mask", False)):
                stage = None
            else:
                try:
                    stage_number = float(raw_stage)
                except (TypeError, ValueError) as exc:
                    raise Hydraulic1DResultError(
                        "D-Flow Pump stage contains a non-numeric value",
                        code="DFLOW_RESULT_CORRUPT",
                    ) from exc
                if stage_number != stage_number:
                    stage = None
                elif not isfinite(stage_number) or not stage_number.is_integer():
                    raise Hydraulic1DResultError(
                        "D-Flow Pump stage is invalid",
                        code="DFLOW_RESULT_NONFINITE",
                    )
                else:
                    stage = int(stage_number)
            capacity = sample_values["pump_capacity"]
            reduction = sample_values["pump_reduction_factor"]
            if capacity < -1e-12 or not -1e-12 <= reduction <= 1.0 + 1e-12:
                raise Hydraulic1DResultError(
                    "D-Flow Pump capacity or reduction factor is outside its native range",
                    code="DFLOW_RESULT_RANGE_INVALID",
                )
            upstream = sample_values["pump_s1up"]
            downstream = sample_values["pump_s1dn"]
            structure_head = sample_values["pump_structure_head"]
            if not isclose(structure_head, upstream - downstream, rel_tol=1e-9, abs_tol=1e-9):
                raise Hydraulic1DResultError(
                    "D-Flow Pump structure head is inconsistent with endpoint levels",
                    code="DFLOW_RESULT_FLOW_IDENTITY_INVALID",
                )
            actual_discharge = sample_values["pump_structure_discharge"]
            oriented_discharge = sample_values["pump_discharge_dir"]
            delivery = sample_values["pump_s1_delivery_side"]
            suction = sample_values["pump_s1_suction_side"]
            pump_head = sample_values["pump_head"]
            if not isclose(actual_discharge, oriented_discharge, rel_tol=1e-9, abs_tol=1e-9):
                raise Hydraulic1DResultError(
                    "D-Flow Pump discharge outputs are inconsistent",
                    code="DFLOW_RESULT_FLOW_IDENTITY_INVALID",
                )
            if not isclose(pump_head, delivery - suction, rel_tol=1e-9, abs_tol=1e-9):
                raise Hydraulic1DResultError(
                    "D-Flow Pump head is inconsistent with delivery/suction levels",
                    code="DFLOW_RESULT_FLOW_IDENTITY_INVALID",
                )
            if not (
                isclose(min(delivery, suction), min(upstream, downstream), rel_tol=1e-9, abs_tol=1e-9)
                and isclose(max(delivery, suction), max(upstream, downstream), rel_tol=1e-9, abs_tol=1e-9)
            ):
                raise Hydraulic1DResultError(
                    "D-Flow Pump endpoint level identities are inconsistent",
                    code="DFLOW_RESULT_FLOW_IDENTITY_INVALID",
                )
            samples.append(
                DFlowFMPumpSample(
                    time_seconds=current_time,
                    structure_id=expected_structure_id,
                    actual_discharge_m3s=actual_discharge,
                    native_applied_capacity_m3s=capacity,
                    oriented_discharge_m3s=oriented_discharge,
                    intake_water_level_m=upstream,
                    outlet_water_level_m=downstream,
                    structure_head_difference_m=structure_head,
                    pump_head_m=pump_head,
                    reduction_factor=reduction,
                    delivery_water_level_m=delivery,
                    suction_water_level_m=suction,
                    active_stage=stage,
                )
            )
        if len(samples) < 2:
            raise Hydraulic1DResultError(
                "D-Flow Pump result requires at least two time samples",
                code="DFLOW_RESULT_SCHEMA_MISMATCH",
            )
        transfer = sum(
            0.5
            * (previous.actual_discharge_m3s + current.actual_discharge_m3s)
            * (current.time_seconds - previous.time_seconds)
            for previous, current in zip(samples, samples[1:], strict=False)
        )
        inflow = values["water_balance_boundaries_in"]
        outflow = values["water_balance_boundaries_out"]
        storage = values["water_balance_storage"]
        errors = values["water_balance_volume_error"]
        inflow_delta = float(inflow[-1] - inflow[0])
        outflow_delta = float(outflow[-1] - outflow[0])
        storage_delta = float(storage[-1] - storage[0])
        residual = float(errors[-1] - errors[0])
        denominator = max(abs(inflow_delta), abs(outflow_delta), abs(storage_delta), 1.0)
        balance = DFlowFMMassBalance(
            inflow_m3=inflow_delta,
            outflow_m3=outflow_delta,
            storage_change_m3=storage_delta,
            structure_transfer_m3=transfer,
            residual_m3=residual,
            relative_residual=abs(residual) / denominator,
            native_max_abs_volume_error_m3=max(abs(float(value)) for value in errors),
        )
        return tuple(samples), balance

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
        if None in converted:
            first_padding = converted.index(None)
            if any(item is not None for item in converted[first_padding:]):
                raise Hydraulic1DResultError(
                    "D-Flow identifier character matrix has non-trailing padding",
                    code="DFLOW_RESULT_LOCATION_INVALID",
                )
            converted = converted[:first_padding]
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
