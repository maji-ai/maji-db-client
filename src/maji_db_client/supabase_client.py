"""Direct, tenant-scoped client for the Supabase Data API (PostgREST).

The API key identifies the backend service. The organization UUID is supplied
for each verified application request and is injected into every write and
filter. Secret/service-role keys bypass RLS, so this automatic filter prevents
accidents but does not replace authentication and authorization.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SupabaseApiError(RuntimeError):
    """Error returned by the Supabase Data API.

    Attributes:
        status_code: HTTP response status, such as ``400``, ``404``, or ``409``.
        detail: Parsed PostgREST error object or plain response text.
    """

    def __init__(self, status_code: int, detail: Any):
        """Create an exception from an unsuccessful Supabase response."""

        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Supabase Data API returned HTTP {status_code}: {detail}")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid table or column name: {value!r}")
    return value


def _json_value(value: Any, *, exclude_none: bool = False) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=exclude_none)
    if isinstance(value, Mapping):
        return {key: _json_value(item, exclude_none=exclude_none) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, exclude_none=exclude_none) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _filter_value(value: Any) -> str:
    if value is None:
        return "is.null"
    if isinstance(value, bool):
        return f"eq.{str(value).lower()}"
    return f"eq.{_json_value(value)}"


class SupabaseDatabaseClient:
    """Synchronous CRUD client scoped to one organization request.

    Create the client after authenticating the incoming user and resolving the
    user's organization. Credentials remain in the backend environment while
    ``organization_id`` changes for each request.

    Example:
        >>> organization_id = current_user.organization_id
        >>> with SupabaseDatabaseClient.from_env(organization_id) as db:
        ...     projects = db.list("projects")

    Warning:
        Never accept ``organization_id`` from an unverified frontend header or
        form field. Resolve it from a verified JWT or server-side membership.
    """

    def __init__(
        self,
        supabase_url: str,
        api_key: str,
        organization_id: UUID | str,
        *,
        access_token: str | None = None,
        timeout: float = 20.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Configure direct Supabase access for one organization request.

        Args:
            supabase_url: Project URL with or without ``/rest/v1``.
            api_key: Backend ``sb_secret_...`` key, legacy service-role JWT, or
                a publishable key when proper RLS is configured.
            organization_id: Tenant UUID resolved from the authenticated user.
            access_token: Optional Supabase Auth user JWT. When provided it is
                sent as the bearer token while ``api_key`` remains ``apikey``.
            timeout: HTTP timeout in seconds.
            http_client: Optional externally managed ``httpx.Client`` for
                custom proxies, TLS settings, pooling, or tests.

        Raises:
            ValueError: If ``organization_id`` is not a valid UUID.
        """

        base_url = supabase_url.rstrip("/")
        if base_url.endswith("/rest/v1"):
            base_url = base_url[:-8]
        self._rest_url = f"{base_url}/rest/v1"
        self.organization_id = str(UUID(str(organization_id)))

        headers = {"apikey": api_key}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif api_key.count(".") == 2:
            # Legacy anon/service_role keys are JWTs. New sb_* keys use only apikey.
            headers["Authorization"] = f"Bearer {api_key}"

        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(headers=headers, timeout=timeout)
        if http_client is not None:
            self._client.headers.update(headers)

    @classmethod
    def from_env(
        cls,
        organization_id: UUID | str,
        **kwargs: Any,
    ) -> "SupabaseDatabaseClient":
        """Create a request-scoped client using backend environment secrets.

        Key lookup order is ``SUPABASE_SECRET_KEY``, legacy
        ``SUPABASE_SERVICE_ROLE_KEY``, ``SUPABASE_API_KEY``,
        ``SUPABASE_PUBLISHABLE_KEY``, then ``SUPABASE_ANON_KEY``.

        Args:
            organization_id: Tenant UUID from the current verified user.
            **kwargs: Optional constructor settings such as ``access_token``,
                ``timeout``, or ``http_client``.

        Returns:
            Configured request-scoped client.

        Raises:
            RuntimeError: If ``SUPABASE_URL`` or an API key is missing.
            ValueError: If ``organization_id`` is not a UUID.

        Example:
            >>> with SupabaseDatabaseClient.from_env(user.organization_id) as db:
            ...     meetings = db.list("meetings")
        """

        url = os.getenv("SUPABASE_URL")
        api_key = (
            os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_API_KEY")
            or os.getenv("SUPABASE_PUBLISHABLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
        )
        missing = [
            name for name, value in (
                ("SUPABASE_URL", url),
                ("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY", api_key),
            ) if not value
        ]
        if missing:
            raise RuntimeError(f"Missing Supabase configuration: {', '.join(missing)}")
        return cls(url, api_key, organization_id, **kwargs)

    def __enter__(self) -> "SupabaseDatabaseClient":
        """Return this client for use in a ``with`` block."""

        return self

    def __exit__(self, *_: object) -> None:
        """Close resources created by this client when leaving a ``with`` block."""

        self.close()

    def close(self) -> None:
        """Close the internally created HTTP connection pool.

        Call this if the client is not used in a ``with`` block. A supplied
        external ``http_client`` stays owned by the caller.
        """

        if self._owns_client:
            self._client.close()

    def _request(self, method: str, table: str, **kwargs: Any) -> Any:
        response = self._client.request(
            method, f"{self._rest_url}/{_identifier(table)}", **kwargs
        )
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise SupabaseApiError(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _tenant_filters(self, filters: Mapping[str, Any] | None = None) -> dict[str, str]:
        values = dict(filters or {})
        values["organization_id"] = self.organization_id
        return {_identifier(name): _filter_value(value) for name, value in values.items()}

    def _create_data(self, data: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
        values = dict(_json_value(data, exclude_none=True))
        values["organization_id"] = self.organization_id
        return values

    def list(
        self,
        table: str,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by: str | None = None,
        direction: str = "asc",
    ) -> list[dict[str, Any]]:
        """List rows belonging to the current organization.

        Args:
            table: Table name, for example ``projects`` or ``meetings``.
            offset: Number of rows to skip.
            limit: Maximum rows to return, between 1 and 1000.
            order_by: Optional column used for sorting.
            direction: ``asc`` or ``desc`` when ``order_by`` is set.

        Returns:
            Tenant-filtered rows as dictionaries.

        Example:
            >>> meetings = db.list(
            ...     "meetings", limit=50,
            ...     order_by="scheduled_at", direction="desc",
            ... )
        """

        return self.query(
            table, {}, offset=offset, limit=limit,
            order_by=order_by, direction=direction,
        )

    def query(
        self,
        table: str,
        filters: Mapping[str, Any],
        *,
        select: str = "*",
        offset: int = 0,
        limit: int = 100,
        order_by: str | None = None,
        direction: str = "asc",
    ) -> list[dict[str, Any]]:
        """Query rows using equality filters and optional ordering.

        The configured ``organization_id`` always overrides any value in
        ``filters``.

        Args:
            table: Table to query.
            filters: Column-to-value equality filters. Use ``None`` for SQL
                ``IS NULL``.
            select: PostgREST select expression; ``*`` returns all columns.
            offset: Number of matching rows to skip.
            limit: Maximum rows to return, between 1 and 1000.
            order_by: Optional column used for sorting.
            direction: Sort direction: ``asc`` or ``desc``.

        Returns:
            Matching tenant rows.

        Raises:
            ValueError: For invalid pagination, direction, or identifiers.
            SupabaseApiError: If Supabase rejects the request.

        Example:
            >>> active = db.query(
            ...     "projects", {"project_status": "active"},
            ...     order_by="created_at", direction="desc",
            ... )
        """

        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be non-negative and limit must be between 1 and 1000")
        if direction not in {"asc", "desc"}:
            raise ValueError("direction must be 'asc' or 'desc'")
        params: dict[str, Any] = {
            "select": select,
            "offset": offset,
            "limit": limit,
            **self._tenant_filters(filters),
        }
        if order_by:
            params["order"] = f"{_identifier(order_by)}.{direction}"
        return self._request("GET", table, params=params)

    def get(self, table: str, key: Mapping[str, Any]) -> dict[str, Any]:
        """Fetch one tenant row using its key fields.

        Args:
            table: Table to read.
            key: Primary-key fields excluding ``organization_id``.

        Returns:
            The first matching row.

        Raises:
            SupabaseApiError: With status ``404`` if no row matches.

        Example:
            >>> project = db.get("projects", {"project_id": project_id})
        """

        rows = self.query(table, key, limit=1)
        if not rows:
            raise SupabaseApiError(404, "Row not found")
        return rows[0]

    def create(self, table: str, data: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
        """Insert one row and return the stored representation.

        ``organization_id`` is injected automatically. ``None`` fields in typed
        models are omitted so database defaults can apply.

        Args:
            table: Destination table.
            data: Typed payload such as ``ProjectData`` or a dictionary.

        Returns:
            Inserted row including generated/default fields.

        Raises:
            SupabaseApiError: For missing fields, invalid values, duplicate
                keys, foreign-key failures, or authorization errors.

        Example:
            >>> saved = db.create("projects", ProjectData(
            ...     project_id=uuid4(), name="Example", description="Demo"
            ... ))
        """

        rows = self._request(
            "POST", table,
            json=self._create_data(data),
            headers={"Prefer": "return=representation"},
        )
        return rows[0]

    def create_many(
        self, table: str, records: Sequence[BaseModel | Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Insert multiple rows in one Supabase request.

        Args:
            table: Destination table.
            records: Typed payloads and/or dictionaries. Organization ID is
                injected into every row.

        Returns:
            Inserted rows in response order. An empty input returns ``[]``
            without making an HTTP request.

        Example:
            >>> db.create_many("meeting_attendees", [
            ...     {"meeting_id": meeting_id, "user_id": first_user_id},
            ...     {"meeting_id": meeting_id, "user_id": second_user_id},
            ... ])
        """

        rows = [self._create_data(record) for record in records]
        if not rows:
            return []
        return self._request(
            "POST", table, json=rows,
            headers={"Prefer": "return=representation"},
        )

    def update(
        self,
        table: str,
        key: Mapping[str, Any],
        data: BaseModel | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Update selected fields on one tenant row.

        Args:
            table: Table containing the row.
            key: Key fields identifying the row.
            data: Fields to change. A dictionary value of ``None`` explicitly
                stores SQL ``NULL``; ``organization_id`` cannot be changed.

        Returns:
            Complete updated row.

        Raises:
            SupabaseApiError: With status ``404`` if absent, or with the
                Supabase error when validation fails.

        Example:
            >>> db.update(
            ...     "projects", {"project_id": project_id},
            ...     {"description": "Updated description"},
            ... )
        """

        values = dict(_json_value(data))
        values.pop("organization_id", None)
        rows = self._request(
            "PATCH", table,
            params=self._tenant_filters(key),
            json=values,
            headers={"Prefer": "return=representation"},
        )
        if not rows:
            raise SupabaseApiError(404, "Row not found")
        return rows[0]

    def delete(self, table: str, key: Mapping[str, Any]) -> dict[str, Any]:
        """Delete exactly one tenant row and return its previous values.

        Args:
            table: Table containing the row.
            key: Key fields identifying the row. Include all non-tenant parts
                of a composite primary key.

        Returns:
            Deleted row as it existed before deletion.

        Raises:
            SupabaseApiError: If the row is absent, referenced by protected
                rows, or deletion is denied.

        Example:
            >>> deleted = db.delete("projects", {"project_id": project_id})
        """

        rows = self._request(
            "DELETE", table,
            params=self._tenant_filters(key),
            headers={"Prefer": "return=representation"},
        )
        if not rows:
            raise SupabaseApiError(404, "Row not found")
        return rows[0]

    def upsert(
        self,
        table: str,
        data: BaseModel | Mapping[str, Any],
        *,
        on_conflict: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Atomically insert a row or merge it on a unique-key conflict.

        Args:
            table: Destination table.
            data: Full row payload including conflict-key fields.
            on_conflict: Unique or primary-key columns that identify a
                conflict. Tenant-owned composite keys usually include
                ``organization_id``.

        Returns:
            Inserted or updated row.

        Raises:
            SupabaseApiError: If the conflict columns are not backed by a
                unique constraint or Supabase rejects the data.

        Example:
            >>> saved = db.upsert(
            ...     "projects", project,
            ...     on_conflict=["organization_id", "project_id"],
            ... )
        """

        params = None
        if on_conflict:
            params = {"on_conflict": ",".join(_identifier(name) for name in on_conflict)}
        rows = self._request(
            "POST", table,
            params=params,
            json=self._create_data(data),
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0]
