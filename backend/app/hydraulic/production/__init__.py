"""Production-grade hydraulic import, QA, calibration, comparison, and products."""

from app.hydraulic.production.calibration import (
    build_parameter_sweep,
    evaluate_acceptance,
    evaluate_validation_independence,
    rank_calibration_candidates,
)
from app.hydraulic.production.comparison import compare_external_result
from app.hydraulic.production.contracts import *  # noqa: F403
from app.hydraulic.production.importers import EngineeringDataImporter
from app.hydraulic.production.metrics import align_and_score
from app.hydraulic.production.products import build_result_products
from app.hydraulic.production.qa import HydraulicModelQA
from app.hydraulic.production.workflow import build_acceptance_manifest

__all__ = [
    "EngineeringDataImporter",
    "HydraulicModelQA",
    "align_and_score",
    "build_acceptance_manifest",
    "build_parameter_sweep",
    "build_result_products",
    "compare_external_result",
    "evaluate_acceptance",
    "evaluate_validation_independence",
    "rank_calibration_candidates",
]
