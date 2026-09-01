"""External hydraulic result comparison without treating a reference as ground truth."""

from __future__ import annotations

from collections import defaultdict

from app.hydraulic.production.contracts import (
    ExternalComparisonRequest,
    ExternalComparisonResult,
    ProductionSeries,
)
from app.hydraulic.production.metrics import align_and_score


def _identity(series: ProductionSeries) -> tuple[str | None, float | None, str]:
    """Return the explicit comparison-location and variable identity."""

    return series.branch_id, float(series.chainage_m) if series.chainage_m is not None else None, series.variable


def _good_samples(series: ProductionSeries) -> dict[float, float]:
    """Keep only factual GOOD values for presentation."""

    return {
        float(sample.time_seconds): float(sample.value)
        for sample in series.samples
        if sample.quality_flag == "GOOD" and sample.value is not None
    }


def compare_external_result(request: ExternalComparisonRequest) -> ExternalComparisonResult:
    """Compare matched locations and return metrics, profiles, and raw series rows."""

    dayu = {_identity(series): series for series in request.dayu_series}
    external = {_identity(series): series for series in request.external_series}
    if len(dayu) != len(request.dayu_series) or len(external) != len(request.external_series):
        raise ValueError("comparison series identities must be unique")
    shared = sorted(set(dayu) & set(external), key=lambda item: (str(item[0]), item[1] or 0, item[2]))
    if not shared:
        raise ValueError("no explicitly mapped Dayu/external comparison locations overlap")
    metrics = []
    time_series: list[dict[str, object]] = []
    longitudinal_values: dict[tuple[str, float], dict[str, float | str | None]] = defaultdict(dict)
    for identity in shared:
        dayu_series = dayu[identity]
        external_series = external[identity]
        if (
            identity[2] == "water_level"
            and dayu_series.vertical_datum != external_series.vertical_datum
        ):
            raise ValueError(
                "water-level comparison requires matching vertical datum or an explicit transformation"
            )
        metrics.append(align_and_score(external_series, dayu_series, request.alignment))
        dayu_samples = _good_samples(dayu_series)
        external_samples = _good_samples(external_series)
        for time_seconds in sorted(set(dayu_samples) | set(external_samples)):
            left = dayu_samples.get(time_seconds)
            right = external_samples.get(time_seconds)
            time_series.append(
                {
                    "branch_id": identity[0],
                    "chainage_m": identity[1],
                    "variable": identity[2],
                    "time_seconds": time_seconds,
                    "dayu_value": left,
                    "external_value": right,
                    "difference": left - right if left is not None and right is not None else None,
                }
            )
        if identity[0] is not None and identity[1] is not None:
            profile = longitudinal_values[(identity[0], identity[1])]
            profile.update({"branch_id": identity[0], "chainage_m": identity[1]})
            dayu_max = max(dayu_samples.values()) if dayu_samples else None
            external_max = max(external_samples.values()) if external_samples else None
            profile[f"dayu_max_{identity[2]}"] = dayu_max
            profile[f"external_max_{identity[2]}"] = external_max
            profile[f"difference_{identity[2]}"] = (
                dayu_max - external_max
                if dayu_max is not None and external_max is not None
                else None
            )
    return ExternalComparisonResult(
        metrics=metrics,
        longitudinal=[
            longitudinal_values[key]
            for key in sorted(longitudinal_values, key=lambda item: (item[0], item[1]))
        ],
        time_series=time_series,
        reference_not_ground_truth=True,
    )


__all__ = ["compare_external_result"]
