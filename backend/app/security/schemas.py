"""Public security contracts; no bearer token or IdP secret is ever returned."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CurrentPrincipalRecord(BaseModel):
    """Expose the authenticated identity and server-owned authorization grants."""

    model_config = ConfigDict(extra="forbid")
    authenticated: bool = True
    id: int
    issuer: str
    subject: str
    display_name: str
    email: str | None = None
    authentication_method: str
    roles: list[str]
    permissions: list[str]


class RoleBindingRequest(BaseModel):
    """Grant or revoke one allow-listed local application role."""

    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=32)


class RoleBindingRecord(BaseModel):
    """Return a local role binding without relying on token role claims."""

    id: int
    principal_id: int
    role: str
    active: bool
    created_at: datetime


class DatasetReviewRequest(BaseModel):
    """Request an engineering decision using the authenticated reviewer."""

    model_config = ConfigDict(extra="forbid")
    comment: str | None = Field(default=None, max_length=2000)


class DatasetReviewDecisionRequest(DatasetReviewRequest):
    """Approve, reject, or return the exact currently QA-validated graph."""

    action: str = Field(pattern="^(approve|reject|return)$")


class DatasetReviewRecord(BaseModel):
    """Expose immutable review evidence bound to a graph hash."""

    id: int
    dataset_version_id: int
    engineering_content_hash: str
    action: str
    status: str
    reviewer_principal_id: int
    reviewer_issuer: str
    reviewer_subject: str
    reviewer_display_name: str
    comment: str | None = None
    created_at: datetime


class SecurityAuditRecord(BaseModel):
    """Expose immutable, token-free security audit evidence."""

    id: int
    action: str
    actor_principal_id: int
    actor_issuer: str
    actor_subject: str
    actor_display_name: str
    resource_type: str
    resource_id: str
    engineering_content_hash: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    request_id: str | None = None
    details_json: dict[str, object]
    created_at: datetime
