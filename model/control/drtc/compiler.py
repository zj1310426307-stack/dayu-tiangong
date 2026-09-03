"""Fail-closed compiler for the runtime-verified minimal D-RTC subset."""

from __future__ import annotations

from collections import Counter

from model.control.drtc.acceptance import controlled_runtime_accepted
from model.control.drtc.contracts import DRTCCompileReport, DRTCRuleCompileRecord
from model.control.rules import ThresholdRule
from model.provenance import snapshot_hash


DRTC_COMPILER_VERSION = "dayu.drtc-compiler.v3"


class DRTCCompiler:
    """Compile the single-Gate threshold semantics proven by DRTC-S01/G03."""

    def compile(
        self,
        rules: tuple[ThresholdRule, ...],
        *,
        manual_actuators: tuple[tuple[str, int], ...] = (),
    ) -> DRTCCompileReport:
        """Return per-rule support and preserve every unverified feature as blocked."""

        actuator_counts = Counter(
            (
                str(rule.action_template["structure_type"]),
                int(rule.action_template["structure_id"]),
            )
            for rule in rules
            if rule.enabled
        )
        manual = set(manual_actuators)
        runtime_validated = controlled_runtime_accepted()
        records: list[DRTCRuleCompileRecord] = []
        for index, rule in enumerate(rules):
            source = {
                "observation_type": rule.observation_type,
                "observation_object_id": rule.observation_object_id,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "hysteresis": rule.hysteresis,
                "minimum_hold_seconds": rule.minimum_hold_seconds,
                "cooldown_seconds": rule.cooldown_seconds,
                "priority": rule.priority,
                "action_template": dict(rule.action_template),
                "inactive_semantics": "emit_no_target_and_preserve_other_policy_or_state",
            }
            actuator = (
                str(rule.action_template["structure_type"]),
                int(rule.action_template["structure_id"]),
            )
            if not rule.enabled:
                records.append(
                    DRTCRuleCompileRecord(
                        rule_id=rule.id,
                        status="COMPILED",
                        source_semantics=source,
                        target_semantics={"operation": "omit_disabled_rule"},
                        compiled_component=None,
                        warnings=("disabled rule is intentionally omitted",),
                        unsupported_reason=None,
                    )
                )
                continue
            reasons: list[str] = []
            structure_type = str(rule.action_template["structure_type"])
            command_type = str(rule.action_template["command_type"])
            if not runtime_validated:
                reasons.append(
                    "source-controlled DIMR/FBC acceptance registry is missing or drifted"
                )
            if structure_type != "gate" or command_type != "gate_opening_m":
                reasons.append(
                    "only the runtime-verified Gate opening target is supported"
                )
            if rule.observation_type not in {
                "node_water_level",
                "section_water_level",
            }:
                reasons.append(
                    "only one exact scalar node/section water-level observation is verified"
                )
            if rule.minimum_hold_seconds > 0:
                reasons.append(
                    "minimum_hold_seconds has no runtime-verified exact mapping"
                )
            if rule.cooldown_seconds > 0:
                reasons.append("cooldown_seconds has no runtime-verified exact mapping")
            if rule.hysteresis > 0:
                reasons.append(
                    "deadBand state equivalence is not benchmarked on the pinned FBC"
                )
            if actuator_counts[actuator] > 1:
                reasons.append(
                    "multiple rules for one actuator require unverified priority semantics"
                )
            if actuator in manual:
                reasons.append(
                    "manual/rule fallback requires unverified merger tie-break semantics"
                )
            if reasons:
                records.append(
                    DRTCRuleCompileRecord(
                        rule_id=rule.id,
                        status="UNSUPPORTED",
                        source_semantics=source,
                        target_semantics={
                            "verified_candidate": "FBC standard trigger and two constant rules",
                            "xsd": "rtcToolsConfig.xsd@DIMRset_2026.02",
                        },
                        compiled_component=None,
                        warnings=(),
                        unsupported_reason="; ".join(reasons),
                    )
                )
                continue
            component_id = f"dayu_gate_rule_{rule.id or index + 1}"
            records.append(
                DRTCRuleCompileRecord(
                    rule_id=rule.id,
                    status="COMPILED",
                    source_semantics={
                        **source,
                        "inactive_semantics": (
                            "explicit_frozen_initial_actuator_state_fallback"
                        ),
                    },
                    target_semantics={
                        "operation": "FBC standard trigger selects true/fallback constant rule",
                        "operator": rule.operator,
                        "threshold": rule.threshold,
                        "target_value": rule.action_template["target_value"],
                        "fallback_source": "frozen initial actuator state",
                        "xsd": "rtcToolsConfig.xsd@DIMRset_2026.02",
                        "acceptance_case": "DRTC-S01",
                    },
                    compiled_component=component_id,
                    warnings=(
                        "inactive output is the explicit frozen initial state, not implicit retention",
                    ),
                    unsupported_reason=None,
                )
            )
        status = (
            "UNSUPPORTED"
            if any(item.status == "UNSUPPORTED" for item in records)
            else "COMPILED"
        )
        payload = {
            "compiler_version": DRTC_COMPILER_VERSION,
            "pinned_runtime_tag": "DIMRset_2026.02",
            "status": status,
            "rules": [item.model_dump(mode="json") for item in records],
            "runtime_validated": runtime_validated,
        }
        return DRTCCompileReport(**payload, artifact_hash=snapshot_hash(payload))
