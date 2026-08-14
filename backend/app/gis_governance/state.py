"""Explicit, small governance state machine kept in the business service layer."""

from app.gis_governance.errors import GovernanceError


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"staged"}),
    "staged": frozenset({"validating"}),
    "validating": frozenset({"validated", "validation_failed"}),
    "validation_failed": frozenset({"staged", "validating"}),
    "validated": frozenset({"in_review", "validating"}),
    "in_review": frozenset({"approved", "changes_requested", "rejected"}),
    "changes_requested": frozenset({"staged", "validating"}),
    "rejected": frozenset(),
    "approved": frozenset({"promoting", "validating"}),
    "promoting": frozenset({"promoted"}),
    "promoted": frozenset({"published"}),
    "published": frozenset(),
}


def require_transition(current: str, target: str) -> None:
    """Reject every lifecycle jump not explicitly allowed by the workflow."""

    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise GovernanceError(
            "INVALID_BATCH_TRANSITION",
            f"Batch cannot transition from {current!r} to {target!r}.",
            status_code=409,
            context={"current": current, "target": target},
        )
