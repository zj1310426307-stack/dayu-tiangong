"""Define the small server-owned role-to-permission mapping."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final


ROLES: Final[frozenset[str]] = frozenset(
    {"viewer", "engineer", "engineering_reviewer", "dataset_freezer", "security_admin"}
)

ROLE_PERMISSIONS: Final[dict[str, frozenset[str]]] = {
    "viewer": frozenset({"dataset.read", "audit.read"}),
    "engineer": frozenset(
        {"dataset.read", "dataset.edit", "dataset.clone", "dataset.submit_review", "audit.read"}
    ),
    "engineering_reviewer": frozenset(
        {"dataset.read", "dataset.review", "dataset.approve", "audit.read"}
    ),
    "dataset_freezer": frozenset(
        {"dataset.read", "dataset.freeze", "dataset.publish", "dataset.retire", "audit.read"}
    ),
    "security_admin": frozenset({"dataset.read", "audit.read", "security.roles.manage"}),
}


def permissions_for_roles(roles: Iterable[str]) -> frozenset[str]:
    """Resolve permissions only from server-recognized local roles."""

    permissions: set[str] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, ()))
    return frozenset(permissions)
