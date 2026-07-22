"""Asynchronous direct client for the Supabase Data API."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

from .supabase_client import SupabaseApiError, _filter_value, _identifier, _json_value


class AsyncSupabaseDatabaseClient:
    """Async CRUD client scoped to one verified organization request.

    For web services, create one shared :class:`httpx.AsyncClient` during
    application startup, then create a lightweight organization-scoped wrapper
    for each request. Wrappers contain no mutable global tenant state.

    Example:
        >>> async with AsyncSupabaseDatabaseClient.from_env(
        ...     current_user.organization_id
        ... ) as db:
        ...     projects = await db.list("projects")
    """

    def __init__(
        self,
        supabase_url: str,
        api_key: str,
        organization_id: UUID | str,
        *,
        access_token: str | None = None,
        timeout: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure async Supabase access for one organization request.

        Args:
            supabase_url: Project URL with or without ``/rest/v1``.
            api_key: Backend secret key, legacy service-role JWT, or a
                publishable key when suitable RLS is configured.
            organization_id: UUID resolved from the authenticated user.
            access_token: Optional Supabase Auth user JWT.
            timeout: HTTP timeout used when creating an internal pool.
            http_client: Optional shared ``httpx.AsyncClient`` connection pool.
                The caller retains ownership and must close it at shutdown.

        Raises:
            ValueError: If ``organization_id`` is not a valid UUID.
        """

        base_url = supabase_url.rstrip("/")
        if base_url.endswith("/rest/v1"):
            base_url = base_url[:-8]
        self._rest_url = f"{base_url}/rest/v1"
        self.organization_id = str(UUID(str(organization_id)))

        self._headers = {"apikey": api_key}
        if access_token:
            self._headers["Authorization"] = f"Bearer {access_token}"
        elif api_key.count(".") == 2:
            self._headers["Authorization"] = f"Bearer {api_key}"

        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            headers=self._headers, timeout=timeout
        )

    @classmethod
    def from_env(
        cls,
        organization_id: UUID | str,
        **kwargs: Any,
    ) -> "AsyncSupabaseDatabaseClient":
        """Create an async request client using backend environment secrets.

        Args:
            organization_id: Tenant UUID from the current verified user.
            **kwargs: Optional ``access_token``, ``timeout``, or shared
                ``http_client``.

        Returns:
            Configured async organization-scoped client.

        Raises:
            RuntimeError: If ``SUPABASE_URL`` or an API key is missing.

        Example:
            >>> db = AsyncSupabaseDatabaseClient.from_env(
            ...     user.organization_id, http_client=shared_http_client
            ... )
            >>> meetings = await db.list("meetings")
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

    async def __aenter__(self) -> "AsyncSupabaseDatabaseClient":
        """Return this client for use in an ``async with`` block."""

        return self

    async def __aexit__(self, *_: object) -> None:
        """Close an internally owned HTTP pool after ``async with``."""

        await self.close()

    async def close(self) -> None:
        """Close the internally created async connection pool.

        A shared externally supplied ``http_client`` is never closed here.
        """

        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, table: str, **kwargs: Any) -> Any:
        request_headers = {**self._headers, **kwargs.pop("headers", {})}
        response = await self._client.request(
            method,
            f"{self._rest_url}/{_identifier(table)}",
            headers=request_headers,
            **kwargs,
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

    async def list(
        self,
        table: str,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by: str | None = None,
        direction: str = "asc",
    ) -> list[dict[str, Any]]:
        """List tenant rows with pagination and optional ordering.

        Args:
            table: Table to read.
            offset: Number of rows to skip.
            limit: Maximum rows to return, between 1 and 1000.
            order_by: Optional sort column.
            direction: ``asc`` or ``desc``.

        Returns:
            Rows belonging to this request's organization.

        Example:
            >>> meetings = await db.list(
            ...     "meetings", order_by="scheduled_at", direction="desc"
            ... )
        """

        return await self.query(
            table, {}, offset=offset, limit=limit,
            order_by=order_by, direction=direction,
        )

    async def query(
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
        """Query tenant rows using equality filters.

        Args:
            table: Table to query.
            filters: Column-to-value equality filters; ``None`` means SQL NULL.
            select: PostgREST select expression.
            offset: Number of matches to skip.
            limit: Maximum rows, between 1 and 1000.
            order_by: Optional sort column.
            direction: ``asc`` or ``desc``.

        Returns:
            Matching rows from the configured organization.

        Raises:
            ValueError: For invalid pagination, direction, or identifiers.
            SupabaseApiError: If Supabase rejects the request.

        Example:
            >>> active = await db.query(
            ...     "projects", {"project_status": "active"}
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
        return await self._request("GET", table, params=params)

    async def get(self, table: str, key: Mapping[str, Any]) -> dict[str, Any]:
        """Fetch one tenant row by key.

        Args:
            table: Table to read.
            key: Primary-key fields excluding ``organization_id``.

        Returns:
            Matching row.

        Raises:
            SupabaseApiError: With status 404 if the row is absent.

        Example:
            >>> project = await db.get("projects", {"project_id": project_id})
        """

        rows = await self.query(table, key, limit=1)
        if not rows:
            raise SupabaseApiError(404, "Row not found")
        return rows[0]

    async def create(
        self, table: str, data: BaseModel | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Insert one tenant row.

        Args:
            table: Destination table.
            data: Typed payload or dictionary; organization ID is injected.

        Returns:
            Inserted row including generated/default values.

        Example:
            >>> saved = await db.create("projects", project)
        """

        rows = await self._request(
            "POST", table,
            json=self._create_data(data),
            headers={"Prefer": "return=representation"},
        )
        return rows[0]

    async def create_many(
        self, table: str, records: Sequence[BaseModel | Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Insert multiple tenant rows in one request.

        Args:
            table: Destination table.
            records: Typed payloads and/or dictionaries.

        Returns:
            Inserted rows, or ``[]`` for empty input.

        Example:
            >>> rows = await db.create_many("meeting_attendees", attendees)
        """

        rows = [self._create_data(record) for record in records]
        if not rows:
            return []
        return await self._request(
            "POST", table, json=rows,
            headers={"Prefer": "return=representation"},
        )

    async def update(
        self,
        table: str,
        key: Mapping[str, Any],
        data: BaseModel | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Update selected fields on one tenant row.

        Args:
            table: Table containing the row.
            key: Key fields identifying the row.
            data: Fields to change; ``organization_id`` cannot be changed.

        Returns:
            Complete updated row.

        Example:
            >>> updated = await db.update(
            ...     "projects", {"project_id": project_id}, {"name": "New"}
            ... )
        """

        values = dict(_json_value(data))
        values.pop("organization_id", None)
        rows = await self._request(
            "PATCH", table,
            params=self._tenant_filters(key),
            json=values,
            headers={"Prefer": "return=representation"},
        )
        if not rows:
            raise SupabaseApiError(404, "Row not found")
        return rows[0]

    async def delete(self, table: str, key: Mapping[str, Any]) -> dict[str, Any]:
        """Delete one tenant row and return its previous values.

        Args:
            table: Table containing the row.
            key: All non-tenant parts of its primary key.

        Returns:
            Deleted row.

        Example:
            >>> deleted = await db.delete(
            ...     "projects", {"project_id": project_id}
            ... )
        """

        rows = await self._request(
            "DELETE", table,
            params=self._tenant_filters(key),
            headers={"Prefer": "return=representation"},
        )
        if not rows:
            raise SupabaseApiError(404, "Row not found")
        return rows[0]

    async def upsert(
        self,
        table: str,
        data: BaseModel | Mapping[str, Any],
        *,
        on_conflict: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Atomically insert or merge a tenant row.

        Args:
            table: Destination table.
            data: Full payload including conflict-key fields.
            on_conflict: Unique key columns, commonly
                ``["organization_id", "record_id"]``.

        Returns:
            Inserted or updated row.

        Example:
            >>> saved = await db.upsert(
            ...     "projects", project,
            ...     on_conflict=["organization_id", "project_id"],
            ... )
        """

        params = None
        if on_conflict:
            params = {"on_conflict": ",".join(_identifier(name) for name in on_conflict)}
        rows = await self._request(
            "POST", table,
            params=params,
            json=self._create_data(data),
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0]
