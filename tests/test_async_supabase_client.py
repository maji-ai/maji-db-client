import asyncio
import json
from uuid import UUID

import httpx

from maji_db_client import AsyncSupabaseDatabaseClient, ProjectData


ORG_A = UUID("00000000-0000-0000-0000-000000000001")
ORG_B = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000003")


async def test_two_tenants_share_one_pool_without_context_leakage() -> None:
    seen_organizations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_organizations.append(request.url.params["organization_id"])
        await asyncio.sleep(0)
        return httpx.Response(200, json=[])

    shared = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client_a = AsyncSupabaseDatabaseClient(
        "https://example.supabase.co", "sb_secret_test", ORG_A,
        http_client=shared,
    )
    client_b = AsyncSupabaseDatabaseClient(
        "https://example.supabase.co", "sb_secret_test", ORG_B,
        http_client=shared,
    )

    await asyncio.gather(client_a.list("projects"), client_b.list("projects"))

    assert sorted(seen_organizations) == sorted([f"eq.{ORG_A}", f"eq.{ORG_B}"])
    await client_a.close()
    await client_b.close()
    assert not shared.is_closed
    await shared.aclose()


async def test_async_create_injects_tenant_and_serializes_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.headers["apikey"] == "sb_secret_test"
        assert payload["organization_id"] == str(ORG_A)
        return httpx.Response(201, json=[payload])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncSupabaseDatabaseClient(
        "https://example.supabase.co", "sb_secret_test", ORG_A,
        http_client=http_client,
    )
    saved = await client.create("projects", ProjectData(
        project_id=PROJECT_ID,
        name="Async test",
        description="Created asynchronously",
    ))
    assert saved["project_id"] == str(PROJECT_ID)
    await http_client.aclose()
