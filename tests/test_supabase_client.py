import json
from uuid import UUID

import httpx

from maji_db_client import ProjectData, SupabaseDatabaseClient


ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")


def test_secret_key_create_injects_tenant_without_bearer_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/projects"
        assert request.headers["apikey"] == "sb_secret_test"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["organization_id"] == str(ORGANIZATION_ID)
        return httpx.Response(201, json=[payload])

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = SupabaseDatabaseClient(
        "https://example.supabase.co/rest/v1",
        "sb_secret_test",
        ORGANIZATION_ID,
        http_client=http_client,
    )
    saved = client.create("projects", ProjectData(
        project_id=PROJECT_ID,
        name="Test",
        description="Direct Supabase test",
    ))
    assert saved["project_id"] == str(PROJECT_ID)
    client.close()
    assert not http_client.is_closed
    http_client.close()


def test_query_and_update_override_untrusted_tenant_values() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"project_id": str(PROJECT_ID), "name": "Updated"}])

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = SupabaseDatabaseClient(
        "https://example.supabase.co", "sb_secret_test", ORGANIZATION_ID,
        http_client=http_client,
    )
    client.query("projects", {"organization_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"})
    client.update("projects", {"project_id": PROJECT_ID}, {"name": "Updated"})

    assert requests[0].url.params["organization_id"] == f"eq.{ORGANIZATION_ID}"
    assert requests[1].url.params["organization_id"] == f"eq.{ORGANIZATION_ID}"
    assert requests[1].url.params["project_id"] == f"eq.{PROJECT_ID}"
    http_client.close()


def test_legacy_jwt_key_is_sent_as_bearer_token() -> None:
    legacy_key = "header.payload.signature"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == legacy_key
        assert request.headers["authorization"] == f"Bearer {legacy_key}"
        return httpx.Response(200, json=[])

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = SupabaseDatabaseClient(
        "https://example.supabase.co", legacy_key, ORGANIZATION_ID,
        http_client=http_client,
    )
    assert client.list("projects") == []
    http_client.close()
