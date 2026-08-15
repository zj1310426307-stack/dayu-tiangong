"""Domain errors with stable machine-readable governance semantics."""

from typing import Any


class GovernanceError(ValueError):
    """Describe one rejected governance operation without leaking database details."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}

    def detail(self) -> dict[str, Any]:
        """Return the structured HTTP error contract."""

        return {"code": self.code, "message": self.message, "context": self.context}
