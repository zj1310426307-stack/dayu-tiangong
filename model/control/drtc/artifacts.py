"""Version-pinned FBC/D-RTC artifacts for the verified Gate control subset.

The module emits configuration only.  DIMR remains the time-step owner and no
Python process reads or advances the hydraulic model between coupling steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from model.provenance import snapshot_hash


FBC_ARTIFACT_SCHEMA = "dayu.drtc-fbc-artifacts.v1"
FBC_RUNTIME_TAG = "DIMRset_2026.02"
FBC_NATIVE_VERSION = "1.6.1"
_RTC_NS = "http://www.wldelft.nl/fews"
_DIMR_NS = "http://schemas.deltares.nl/dimr"
_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_OPERATOR = {
    ">": "Greater",
    ">=": "GreaterEqual",
    "<": "Less",
    "<=": "LessEqual",
}


def _finite(value: float, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _identifier(value: str, field: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} is not a safe FBC identifier")
    return value


def _scalar(value: float) -> str:
    return format(_finite(value, "numeric value"), ".17g")


@dataclass(frozen=True, slots=True)
class DRTCGateThresholdSpec:
    """One runtime-proven simple threshold with an explicit false fallback."""

    rule_id: str
    observation_bmi_variable: str
    actuator_bmi_variable: str
    operator: str
    threshold: float
    target_native_value: float
    fallback_native_value: float

    def __post_init__(self) -> None:
        _identifier(self.rule_id, "rule_id")
        if self.operator not in _OPERATOR:
            raise ValueError("operator is outside the verified D-RTC subset")
        if not self.observation_bmi_variable.startswith(
            ("observations/", "crosssections/")
        ) or not self.observation_bmi_variable.endswith("/water_level"):
            raise ValueError("only exact D-Flow water-level observations are supported")
        if not self.actuator_bmi_variable.startswith("orifices/") or not (
            self.actuator_bmi_variable.endswith("/gateLowerEdgeLevel")
        ):
            raise ValueError("only the audited Orifice Gate lower-edge target is supported")
        _finite(self.threshold, "threshold")
        _finite(self.target_native_value, "target_native_value")
        _finite(self.fallback_native_value, "fallback_native_value")


@dataclass(frozen=True, slots=True)
class DRTCManualGateScheduleSpec:
    """One precompiled absolute Gate schedule executed inside FBC."""

    schedule_id: str
    actuator_bmi_variable: str
    records: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        _identifier(self.schedule_id, "schedule_id")
        if not self.actuator_bmi_variable.startswith("orifices/") or not (
            self.actuator_bmi_variable.endswith("/gateLowerEdgeLevel")
        ):
            raise ValueError("only the audited Orifice Gate lower-edge target is supported")
        if not self.records or self.records[0][0] != 0:
            raise ValueError("a Gate schedule requires an explicit t0 value")
        times = tuple(_finite(item[0], "schedule time") for item in self.records)
        if any(value < 0 for value in times) or tuple(sorted(times)) != times:
            raise ValueError("schedule times must be non-negative and ordered")
        if len(set(times)) != len(times):
            raise ValueError("schedule times must be unique")
        for _, value in self.records:
            _finite(value, "schedule native value")


@dataclass(frozen=True, slots=True)
class DRTCFBCArtifacts:
    """Paths and a content hash for one immutable generated coupling bundle."""

    dimr_config: Path
    settings: Path
    data_config: Path
    runtime_config: Path
    tools_config: Path
    manifest: Path
    artifact_hash: str


def _element(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    child = ET.SubElement(parent, tag, attrs)
    if text is not None:
        child.text = text
    return child


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class DRTCFBCArtifactWriter:
    """Write the reviewed DIMR/FBC contract without solver source vendoring."""

    def write_threshold(
        self,
        *,
        job_root: Path,
        dflow_input_file: str,
        start: datetime,
        duration_seconds: float,
        coupling_step_seconds: float,
        spec: DRTCGateThresholdSpec,
    ) -> DRTCFBCArtifacts:
        """Emit a true/false constant-rule state machine for DRTC-S01/G03."""

        stem = spec.rule_id
        input_series = f"input_{stem}_water_level"
        output_series = f"output_{stem}_gate_lower_edge_level"
        tools = ET.Element("rtcToolsConfig", {"xmlns": _RTC_NS})
        general = _element(tools, "general")
        _element(general, "description", "Dayu verified simple Gate threshold")
        _element(general, "poolRoutingScheme", "Theta")
        _element(general, "theta", "0.5")
        rules = _element(tools, "rules")
        target_rule = f"{stem}.true"
        fallback_rule = f"{stem}.false"
        for rule_name, value in (
            (target_rule, spec.target_native_value),
            (fallback_rule, spec.fallback_native_value),
        ):
            rule = _element(rules, "rule")
            constant = _element(rule, "constant", id=rule_name)
            _element(constant, "constant", _scalar(value))
            output = _element(constant, "output")
            _element(output, "y", output_series)
        triggers = _element(tools, "triggers")
        trigger = _element(_element(triggers, "trigger"), "standard", id=f"{stem}.trigger")
        condition = _element(trigger, "condition")
        _element(condition, "x1Series", input_series, ref="IMPLICIT")
        _element(condition, "relationalOperator", _OPERATOR[spec.operator])
        _element(condition, "x2Value", _scalar(spec.threshold))
        _element(trigger, "default", "false")
        for branch_name, rule_name in (("true", target_rule), ("false", fallback_rule)):
            branch = _element(trigger, branch_name)
            nested = _element(branch, "trigger")
            _element(nested, "ruleReference", rule_name)
        output = _element(trigger, "output")
        _element(output, "status", f"status_{stem}")
        return self._write(
            job_root=job_root,
            dflow_input_file=dflow_input_file,
            start=start,
            duration_seconds=duration_seconds,
            coupling_step_seconds=coupling_step_seconds,
            import_series=((input_series, "water_level", "m"),),
            export_series=(
                (output_series, "gate_lower_edge_level", "m"),
                # FBC 1.6.1 only accepts its closed unit enumeration here.
                # Trigger status is an internal scalar and is never coupled;
                # ``s`` is the native schema-compatible convention.
                (f"status_{stem}", "trigger_status", "s"),
            ),
            flow_to_rtc=((spec.observation_bmi_variable, input_series),),
            rtc_to_flow=((output_series, spec.actuator_bmi_variable),),
            tools=tools,
            semantic_payload={
                "kind": "simple_threshold_with_explicit_fallback",
                "rule_id": spec.rule_id,
                "operator": spec.operator,
                "threshold": spec.threshold,
                "target_native_value": spec.target_native_value,
                "fallback_native_value": spec.fallback_native_value,
                "observation_bmi_variable": spec.observation_bmi_variable,
                "actuator_bmi_variable": spec.actuator_bmi_variable,
            },
        )

    def write_schedule(
        self,
        *,
        job_root: Path,
        dflow_input_file: str,
        start: datetime,
        duration_seconds: float,
        coupling_step_seconds: float,
        spec: DRTCManualGateScheduleSpec,
    ) -> DRTCFBCArtifacts:
        """Emit a BLOCK-interpolated absolute table for G02."""

        output_series = f"output_{spec.schedule_id}_gate_lower_edge_level"
        tools = ET.Element("rtcToolsConfig", {"xmlns": _RTC_NS})
        general = _element(tools, "general")
        _element(general, "description", "Dayu compiled manual Gate schedule")
        _element(general, "poolRoutingScheme", "Theta")
        _element(general, "theta", "0.5")
        rules = _element(tools, "rules")
        rule = _element(rules, "rule")
        timed = _element(rule, "timeRelative", id=spec.schedule_id)
        _element(timed, "mode", "NATIVE")
        _element(timed, "valueOption", "ABSOLUTE")
        _element(timed, "maximumPeriod", _scalar(duration_seconds))
        _element(timed, "interpolationOption", "BLOCK")
        table = _element(timed, "controlTable")
        for time_seconds, value in spec.records:
            _element(
                table,
                "record",
                time=_scalar(time_seconds),
                value=_scalar(value),
            )
        output = _element(timed, "output")
        _element(output, "y", output_series)
        _element(output, "timeActive", f"time_active_{spec.schedule_id}")
        return self._write(
            job_root=job_root,
            dflow_input_file=dflow_input_file,
            start=start,
            duration_seconds=duration_seconds,
            coupling_step_seconds=coupling_step_seconds,
            # rtcDataConfig.xsd requires at least one import series even for a
            # purely time-relative rule.  This internal, uncoupled placeholder
            # satisfies that native contract and never drives the actuator.
            import_series=((f"input_{spec.schedule_id}_clock", "internal_clock", "s"),),
            export_series=(
                (output_series, "gate_lower_edge_level", "m"),
                (f"time_active_{spec.schedule_id}", "time_active", "s"),
            ),
            flow_to_rtc=(),
            rtc_to_flow=((output_series, spec.actuator_bmi_variable),),
            tools=tools,
            semantic_payload={
                "kind": "manual_gate_schedule",
                "schedule_id": spec.schedule_id,
                "actuator_bmi_variable": spec.actuator_bmi_variable,
                "interpolation": "BLOCK",
                "records": [list(item) for item in spec.records],
            },
        )

    def _write(
        self,
        *,
        job_root: Path,
        dflow_input_file: str,
        start: datetime,
        duration_seconds: float,
        coupling_step_seconds: float,
        import_series: tuple[tuple[str, str, str], ...],
        export_series: tuple[tuple[str, str, str], ...],
        flow_to_rtc: tuple[tuple[str, str], ...],
        rtc_to_flow: tuple[tuple[str, str], ...],
        tools: ET.Element,
        semantic_payload: dict[str, object],
    ) -> DRTCFBCArtifacts:
        duration = _finite(duration_seconds, "duration_seconds")
        step = _finite(coupling_step_seconds, "coupling_step_seconds")
        if duration <= 0 or step <= 0 or duration < step:
            raise ValueError("duration and coupling step are invalid")
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if Path(dflow_input_file).name != dflow_input_file:
            raise ValueError("dflow_input_file must be a file name")
        job_root = Path(job_root).resolve()
        control_dir = job_root / "control"
        rtc_dir = control_dir / "rtc"
        xml_dir = rtc_dir / "xml_dir"
        for path in (control_dir, rtc_dir, xml_dir):
            path.mkdir(parents=True, exist_ok=True)

        settings = rtc_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {"schemaDir": "/delft3d/share/drtc", "xmlDir": "xml_dir"},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

        data = ET.Element("rtcDataConfig", {"xmlns": _RTC_NS})
        imports = _element(data, "importSeries")
        for series_id, quantity_id, unit in import_series:
            series = _element(imports, "timeSeries", id=series_id)
            exchange = _element(series, "OpenMIExchangeItem")
            _element(exchange, "elementId", series_id)
            _element(exchange, "quantityId", quantity_id)
            _element(exchange, "unit", unit)
        exports = _element(data, "exportSeries")
        _element(
            exports,
            "CSVTimeSeriesFile",
            decimalSeparator=".",
            delimiter=",",
            adjointOutput="false",
        )
        pi_file = _element(exports, "PITimeSeriesFile")
        _element(pi_file, "timeSeriesFile", "timeseries_export.xml")
        _element(pi_file, "useBinFile", "false")
        for series_id, quantity_id, unit in export_series:
            series = _element(exports, "timeSeries", id=series_id)
            exchange = _element(series, "OpenMIExchangeItem")
            _element(exchange, "elementId", series_id)
            _element(exchange, "quantityId", quantity_id)
            _element(exchange, "unit", unit)
        data_config = xml_dir / "rtcDataConfig.xml"
        _write_xml(data_config, data)

        runtime = ET.Element("rtcRuntimeConfig", {"xmlns": _RTC_NS})
        user = _element(_element(runtime, "period"), "userDefined")
        end = start + timedelta(seconds=duration)
        _element(user, "startDate", date=start.date().isoformat(), time=start.time().isoformat())
        _element(user, "endDate", date=end.date().isoformat(), time=end.time().isoformat())
        _element(
            user,
            "timeStep",
            unit="second",
            multiplier=str(int(step)),
            divider="1",
        )
        simulation = _element(_element(runtime, "mode"), "simulation")
        _element(simulation, "limitedMemory", "true")
        runtime_config = xml_dir / "rtcRuntimeConfig.xml"
        _write_xml(runtime_config, runtime)

        tools_config = xml_dir / "rtcToolsConfig.xml"
        _write_xml(tools_config, tools)
        state = ET.Element("treeVectorFile", {"xmlns": "http://www.openda.org"})
        tree = _element(state, "treeVector")
        state_series_ids = tuple(series_id for series_id, _, _ in import_series) + tuple(
            series_id for series_id, _, _ in export_series
        )
        for series_id in state_series_ids:
            leaf = _element(tree, "treeVectorLeaf", id=series_id)
            _element(leaf, "vector", "NaN")
        state_import = xml_dir / "state_import.xml"
        _write_xml(state_import, state)
        timeseries_export = xml_dir / "timeseries_export.xml"
        timeseries_export.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<TimeSeries xmlns="http://www.wldelft.nl/fews/PI">'
            '<timeZone>0.0</timeZone></TimeSeries>\n',
            encoding="utf-8",
        )

        ET.register_namespace("", _DIMR_NS)
        dimr = ET.Element(f"{{{_DIMR_NS}}}dimrConfig")
        documentation = _element(dimr, "documentation")
        _element(documentation, "fileVersion", "1.3")
        _element(documentation, "createdBy", "Dayu verified D-RTC compiler")
        _element(documentation, "creationDate", start.isoformat())
        control = _element(dimr, "control")
        parallel = _element(control, "parallel")
        group = _element(parallel, "startGroup")
        _element(group, "time", f"0.0 {_scalar(step)} {_scalar(duration)}")
        if flow_to_rtc:
            _element(group, "coupler", name="flow2rtc")
        _element(group, "start", name="fbc")
        _element(group, "coupler", name="rtc2flow")
        _element(parallel, "start", name="dflowfm")
        flow = _element(dimr, "component", name="dflowfm")
        _element(flow, "library", "dflowfm")
        _element(flow, "workingDir", "input")
        _element(flow, "inputFile", dflow_input_file)
        fbc = _element(dimr, "component", name="fbc")
        _element(fbc, "library", "FBCTools_BMI")
        _element(fbc, "workingDir", "control/rtc")
        _element(fbc, "inputFile", ".")
        for name, source, target, items in (
            ("flow2rtc", "dflowfm", "fbc", flow_to_rtc),
            ("rtc2flow", "fbc", "dflowfm", rtc_to_flow),
        ):
            if not items:
                continue
            coupler = _element(dimr, "coupler", name=name)
            _element(coupler, "sourceComponent", source)
            _element(coupler, "targetComponent", target)
            for source_name, target_name in items:
                item = _element(coupler, "item")
                _element(item, "sourceName", source_name)
                _element(item, "targetName", target_name)
        dimr_config = control_dir / "dimr_config.xml"
        _write_xml(dimr_config, dimr)

        content_paths = (
            settings,
            data_config,
            runtime_config,
            tools_config,
            state_import,
            timeseries_export,
            dimr_config,
        )
        content = {
            str(path.relative_to(job_root)).replace("\\", "/"): path.read_text(encoding="utf-8")
            for path in content_paths
        }
        payload = {
            "schema_version": FBC_ARTIFACT_SCHEMA,
            "runtime_tag": FBC_RUNTIME_TAG,
            "fbc_version": FBC_NATIVE_VERSION,
            "duration_seconds": duration,
            "coupling_step_seconds": step,
            "semantic_contract": semantic_payload,
            "files": content,
        }
        artifact_hash = snapshot_hash(payload)
        manifest = control_dir / "drtc-artifact-manifest.json"
        manifest.write_text(
            json.dumps({**payload, "artifact_hash": artifact_hash}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return DRTCFBCArtifacts(
            dimr_config,
            settings,
            data_config,
            runtime_config,
            tools_config,
            manifest,
            artifact_hash,
        )
