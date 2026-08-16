"""Bounded HTTP client; no database, admin, arbitrary URL, or actor injection."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


GET_ROUTES = {
    "health": "/api/v1/health",
    "batch": "/api/v1/gis-governance/batches/{batch_id}",
    "validation": "/api/v1/gis-governance/batches/{batch_id}/validation",
    "issues": "/api/v1/gis-governance/batches/{batch_id}/issues",
    "diff": "/api/v1/gis-governance/batches/{batch_id}/diff",
    "publications": "/api/v1/gis-governance/publications",
}
POST_ROUTES = {
    "validate": "/api/v1/gis-governance/batches/{batch_id}/validate",
    "submit_review": "/api/v1/gis-governance/batches/{batch_id}/submit-review",
}


class BridgeError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BridgeApiClient:
    """Call only frozen governance routes and redact authorization from errors."""

    def __init__(self, base_url: str | None = None, token: str | None = None, mode: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("DAYU_API_BASE_URL", "http://127.0.0.1:8001")).rstrip("/")
        self.token = token or os.getenv("DAYU_IAM_TOKEN")
        self.mode = mode or os.getenv("DAYU_BRIDGE_MODE", "demo")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise BridgeError("API base URL is invalid")
        if self.mode == "production" and parsed.scheme != "https":
            raise BridgeError("Production bridge requires HTTPS")

    @property
    def identity_label(self) -> str:
        return "IAM/OIDC TOKEN" if self.token else "UNVERIFIED LOCAL IDENTITY"

    @property
    def mutation_allowed(self) -> bool:
        return self.mode != "production" or bool(self.token)

    def get(self, route_key: str, *, batch_id: int | None = None) -> Any:
        return self._call("GET", self._route(GET_ROUTES, route_key, batch_id), None)

    def post(self, route_key: str, payload: dict[str, Any] | None = None, *, batch_id: int | None = None) -> Any:
        if not self.mutation_allowed:
            raise BridgeError("PRODUCTION_MUTATION_REQUIRES_IAM")
        return self._call("POST", self._route(POST_ROUTES, route_key, batch_id), payload or {})

    @staticmethod
    def _route(routes: dict[str, str], key: str, batch_id: int | None) -> str:
        template = routes.get(key)
        if template is None:
            raise BridgeError("API route is outside the plugin allow-list")
        if "{batch_id}" in template:
            if batch_id is None or batch_id <= 0:
                raise BridgeError("A positive batch id is required")
            return template.format(batch_id=batch_id)
        return template

    def _call(self, method: str, path: str, payload: dict[str, Any] | None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.base_url}{path}", data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 - validated fixed base URL
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise BridgeError(
                f"API request rejected with HTTP {exc.code}", status_code=exc.code
            ) from exc
        except URLError as exc:
            raise BridgeError("API is unavailable") from exc

    def deep_link(self, dataset_version_id: int, layer_key: str, feature_id: int) -> str:
        if dataset_version_id <= 0 or feature_id <= 0 or not layer_key.replace("_", "").isalnum():
            raise BridgeError("Feature identity is invalid")
        query = urlencode({"datasetVersionId": dataset_version_id, "selectedAsset": f"{layer_key}:{feature_id}"})
        return f"{self.base_url}/gis?{query}"
