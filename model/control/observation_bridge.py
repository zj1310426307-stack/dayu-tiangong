"""Explicit D-Flow BMI observation bindings for the Dayu rule whitelist."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class ObservationBinding(BaseModel):
    """Bind one Dayu observation to exact, direction-audited BMI variables."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_type: Literal[
        "node_water_level",
        "section_water_level",
        "gate_head_difference",
        "pump_intake_level",
    ]
    observation_object_id: int = Field(gt=0)
    source_kind: Literal[
        "observation_point",
        "cross_section",
        "oriented_observation_pair",
    ]
    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    upstream_source_id: str | None = Field(default=None, min_length=1, max_length=255)
    downstream_source_id: str | None = Field(default=None, min_length=1, max_length=255)
    unit: Literal["m"] = "m"
    binding_evidence: Literal["SOURCE_DATA", "SYNTHETIC_ASSUMPTION"]

    @model_validator(mode="after")
    def validate_source(self) -> "ObservationBinding":
        """Reject nearest-location inference and ambiguous head orientation."""

        is_pair = self.observation_type == "gate_head_difference"
        if is_pair:
            if self.source_kind != "oriented_observation_pair":
                raise ValueError(
                    "gate head difference requires an oriented observation pair"
                )
            if not self.upstream_source_id or not self.downstream_source_id:
                raise ValueError(
                    "gate head difference requires upstream and downstream ids"
                )
            if self.upstream_source_id == self.downstream_source_id:
                raise ValueError("gate head observation ids must be distinct")
            if self.source_id is not None:
                raise ValueError("oriented observation pair must not define source_id")
            return self
        if self.source_kind == "oriented_observation_pair" or not self.source_id:
            raise ValueError("scalar observation requires one explicit source_id")
        if self.upstream_source_id is not None or self.downstream_source_id is not None:
            raise ValueError("scalar observation must not define an observation pair")
        if (
            self.observation_type == "section_water_level"
            and self.source_kind != "cross_section"
        ):
            raise ValueError("section water level requires an explicit cross section")
        if self.observation_type in {"node_water_level", "pump_intake_level"} and (
            self.source_kind != "observation_point"
        ):
            raise ValueError(
                "node and intake levels require explicit observation points"
            )
        return self

    def bmi_variables(self) -> tuple[str, ...]:
        """Return only BMI names documented by the pinned Deltares runtime."""

        if self.source_kind == "cross_section":
            return (f"crosssections/{self.source_id}/water_level",)
        if self.source_kind == "observation_point":
            return (f"observations/{self.source_id}/water_level",)
        return (
            f"observations/{self.upstream_source_id}/water_level",
            f"observations/{self.downstream_source_id}/water_level",
        )


class HydraulicObservationAdapter:
    """Translate an exact BMI value map into Dayu observation identities."""

    def __init__(self, bindings: tuple[ObservationBinding, ...]) -> None:
        keys = [
            (item.observation_type, item.observation_object_id) for item in bindings
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("observation bindings must have unique Dayu identities")
        self._bindings = bindings

    def required_bmi_variables(self) -> tuple[str, ...]:
        """Return the stable union needed by the DIMR flow-to-RTC coupler."""

        return tuple(
            sorted({name for item in self._bindings for name in item.bmi_variables()})
        )

    def adapt(self, values: Mapping[str, FiniteFloat]) -> dict[tuple[str, int], float]:
        """Read exact sources and compute only an explicitly oriented head difference."""

        result: dict[tuple[str, int], float] = {}
        for binding in self._bindings:
            variables = binding.bmi_variables()
            missing = [name for name in variables if name not in values]
            if missing:
                raise KeyError("missing D-Flow BMI observations: " + ", ".join(missing))
            if len(variables) == 1:
                value = float(values[variables[0]])
            else:
                value = float(values[variables[0]]) - float(values[variables[1]])
            result[(binding.observation_type, binding.observation_object_id)] = value
        return result
