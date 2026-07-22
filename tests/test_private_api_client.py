import json
from uuid import UUID

import httpx

from maji_db_client import DatabaseApiClient, ProjectData


def test_typed_model_is_serialized_with_service_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Service-Name"] == "project-service"
        assert request.headers["X-Organization-ID"] == "00000000-0000-0000-0000-000000000001"
        payload = json.loads(request.content)
        assert payload["data"]["project_id"] == "00000000-0000-0000-0000-000000000002"
        return httpx.Response(201, json=payload["data"])

    http_client = httpx.Client(
        base_url="http://database-api", transport=httpx.MockTransport(handler)
    )
    client = DatabaseApiClient(
        "http://database-api",
        "project-service",
        UUID("00000000-0000-0000-0000-000000000001"),
        http_client=http_client,
    )
    result = client.create("projects", ProjectData(
        project_id=UUID("00000000-0000-0000-0000-000000000002"),
        name="Test",
        description="Test project",
    ))
    assert result["name"] == "Test"
    http_client.close()
