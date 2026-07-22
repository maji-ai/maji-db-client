"""Client for the private Maji Database API.

Use :class:`DatabaseApiClient` when a service reaches the Maji FastAPI server
through localhost, a private network, or a protected tunnel. For direct
Supabase access, use :class:`maji_db_client.SupabaseDatabaseClient` instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel


class DatabaseApiError(RuntimeError):
    """Error returned by the private Database API.

    Attributes:
        status_code: HTTP response status, such as ``404`` or ``422``.
        detail: Parsed API error body or plain response text.
    """

    def __init__(self, status_code: int, detail: Any):
        """Create an exception from an unsuccessful API response."""

        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Database API returned HTTP {status_code}: {detail}")


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


class DatabaseApiClient:
    """Tenant-scoped synchronous client for the private FastAPI CRUD service.

    Create one client for the organization represented by the current verified
    request context. The client adds ``X-Service-Name`` and
    ``X-Organization-ID`` to every request.

    Example:
        >>> with DatabaseApiClient(
        ...     "http://127.0.0.1:8001", "meeting-service", organization_id
        ... ) as db:
        ...     projects = db.list("projects")
    """

    def __init__(
        self,
        base_url: str,
        service_name: str,
        organization_id: UUID | str,
        *,
        timeout: float = 15.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Configure a private Database API client.

        Args:
            base_url: API origin, for example ``http://127.0.0.1:8001``.
            service_name: Stable name identifying the calling backend service.
            organization_id: Tenant UUID for the current verified request.
            timeout: Request timeout in seconds.
            http_client: Optional preconfigured ``httpx.Client``. Useful for
                proxies, Basic Auth, custom TLS certificates, or tests.
        """

        headers = {
            "X-Service-Name": service_name,
            "X-Organization-ID": str(organization_id),
        }
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )
        if http_client is not None:
            self._client.headers.update(headers)

    def __enter__(self) -> "DatabaseApiClient":
        """Return this client for use in a ``with`` block."""

        return self

    def __exit__(self, *_: object) -> None:
        """Close resources created by this client when leaving a ``with`` block."""

        self.close()

    def close(self) -> None:
        """Close the internally created HTTP connection pool.

        Call this when the client is not used as a context manager. A supplied
        external ``http_client`` remains owned by the caller and is not closed.
        """

        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        if response.is_error:
            try:
                body = response.json()
                detail = body.get("detail", body)
            except ValueError:
                detail = response.text
            raise DatabaseApiError(response.status_code, detail)
        return None if response.status_code == 204 else response.json()

    def tables(self) -> list[str]:
        """Return every table exposed by the private API.

        Returns:
            Sorted table names that can be passed to the CRUD methods.

        Example:
            >>> db.tables()
            ['chats', 'departments', 'documents', ...]
        """

        return self._request("GET", "/v1/tables")

    def schema(self, table: str) -> dict[str, Any]:
        """Return fields, types, defaults, and primary keys for one table.

        Args:
            table: Exposed table name, such as ``projects``.

        Returns:
            JSON Schema plus ``x-primary-keys`` and ``x-api-primary-keys``.

        Raises:
            DatabaseApiError: If the table does not exist or access fails.

        Example:
            >>> schema = db.schema("projects")
            >>> schema["x-api-primary-keys"]
            ['project_id']
        """

        return self._request("GET", f"/v1/tables/{table}/schema")

    def list(self, table: str, *, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """List tenant rows with simple pagination.

        Args:
            table: Table to read.
            offset: Number of rows to skip.
            limit: Maximum rows to return; the API allows up to 500.

        Returns:
            Serialized rows belonging to this client's organization.

        Example:
            >>> projects = db.list("projects", limit=50)
        """

        return self._request(
            "GET", f"/v1/data/{table}", params={"offset": offset, "limit": limit}
        )

    def query(self, table: str, filters: Mapping[str, Any], **options: Any) -> list[dict[str, Any]]:
        """Query rows using equality filters, ordering, and pagination.

        Args:
            table: Table to query.
            filters: Column-to-value equality filters.
            **options: Optional ``offset``, ``limit``, ``order_by``, and
                ``direction`` (``asc`` or ``desc``).

        Returns:
            Matching rows from the current organization.

        Example:
            >>> db.query(
            ...     "projects", {"project_status": "active"},
            ...     order_by="created_at", direction="desc", limit=20,
            ... )
        """

        payload = {"filters": _json_value(filters), **options}
        return self._request("POST", f"/v1/data/{table}/query", json=payload)

    def create(self, table: str, data: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
        """Insert one row using a typed model or dictionary.

        ``organization_id`` is taken from this client, not from ``data``.

        Args:
            table: Destination table.
            data: Typed payload such as ``ProjectData`` or a field dictionary.

        Returns:
            The complete inserted row, including generated fields.

        Raises:
            DatabaseApiError: For missing fields, invalid values, foreign-key
                failures, duplicates, or other API errors.

        Example:
            >>> saved = db.create("projects", {
            ...     "name": "Example", "description": "Created by a service"
            ... })
        """

        return self._request("POST", f"/v1/data/{table}", json={"data": _json_value(data)})

    def get(self, table: str, key: Mapping[str, Any]) -> dict[str, Any]:
        """Fetch one row by its API primary key.

        Args:
            table: Table to read.
            key: Primary-key fields excluding ``organization_id`` because the
                organization is already configured on the client.

        Returns:
            The matching row.

        Raises:
            DatabaseApiError: With status ``404`` when the row is absent.

        Example:
            >>> project = db.get("projects", {"project_id": project_id})
        """

        return self._request("POST", f"/v1/data/{table}/get", json={"key": _json_value(key)})

    def update(
        self, table: str, key: Mapping[str, Any], data: BaseModel | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Update selected fields on one row.

        Args:
            table: Table containing the row.
            key: API primary-key fields identifying the row.
            data: Only fields that should change.

        Returns:
            The complete updated row.

        Raises:
            DatabaseApiError: If the row is missing or validation fails.

        Example:
            >>> db.update(
            ...     "projects", {"project_id": project_id},
            ...     {"description": "New description"},
            ... )
        """

        return self._request(
            "PATCH", f"/v1/data/{table}",
            json={"key": _json_value(key), "data": _json_value(data)},
        )

    def delete(self, table: str, key: Mapping[str, Any]) -> None:
        """Delete one row by primary key.

        Args:
            table: Table containing the row.
            key: API primary-key fields identifying exactly one row.

        Raises:
            DatabaseApiError: If the row is missing, still referenced, or the
                API rejects deletion.

        Example:
            >>> db.delete("projects", {"project_id": project_id})
        """

        self._request("DELETE", f"/v1/data/{table}", json={"key": _json_value(key)})

    def upsert(
        self, table: str, key: Mapping[str, Any], data: BaseModel | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Create a known row or update it when it already exists.

        This helper first calls :meth:`get`; it creates on HTTP 404 and updates
        otherwise. It is convenient for deterministic seed data but is not an
        atomic database upsert.

        Args:
            table: Target table.
            key: Primary key used to detect an existing row.
            data: Full creation payload and desired update values.

        Returns:
            The created or updated row.

        Example:
            >>> db.upsert(
            ...     "projects", {"project_id": project.project_id}, project
            ... )
        """

        try:
            self.get(table, key)
        except DatabaseApiError as exc:
            if exc.status_code != 404:
                raise
            return self.create(table, data)
        return self.update(table, key, data)
