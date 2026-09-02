"""Fail-closed compiler for Dayu rules whose D-RTC equivalence is unproven."""

from __future__ import annotations

from collections import Counter

from model.control.drtc.contracts import DRTCCompileReport, DRTCRuleCompileRecord
from model.control.rules import ThresholdRule
from model.provenance import snapshot_hash


DRTC_COMPILER_VERSION = "dayu.drtc-compiler.v1"


class DRTCCompiler:
    """Audit a rule set without approximating priority, hold, or inactive semantics."""

    def compile(
        self,
        rules: tuple[ThresholdRule, ...],
        *,
        manual_actuators: tuple[tuple[str, int], ...] = (),
    ) -> DRTCCompileReport:
        """Return detailed blockers until a pinned FBC runtime proves equivalence."""

        actuator_counts = Counter(
            (
                str(rule.action_template["structure_type"]),
                int(rule.action_template["structure_id"]),
            )
            for rule in rules
            if rule.enabled
        )
        manual = set(manual_actuators)
        records: list[DRTCRuleCompileRecord] = []
        for rule in rules:
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
            # Even the syntactically small subset remains blocked: Dayu emits no
            # target while inactive, whereas an FBC output series needs an exact
            # default/fallback.  The pinned runtime and a benchmark must prove
            # that state machine before XML is emitted.
            reasons.append(
                "Dayu inactive-rule state retention is not yet proven equivalent to FBC output"
            )
            records.append(
                DRTCRuleCompileRecord(
                    rule_id=rule.id,
                    status="UNSUPPORTED",
                    source_semantics=source,
                    target_semantics={
                        "candidate": "standard/deadBand trigger plus controlled output",
                        "xsd": "rtcToolsConfig.xsd@DIMRset_2026.02",
                    },
                    compiled_component=None,
                    warnings=(),
                    unsupported_reason="; ".join(reasons),
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
            "runtime_validated": False,
        }
        return DRTCCompileReport(**payload, artifact_hash=snapshot_hash(payload))
