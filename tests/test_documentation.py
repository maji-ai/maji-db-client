import inspect

from uuid import UUID

from maji_db_client import (
    ApiData, AsyncSupabaseDatabaseClient, DatabaseApiClient,
    SupabaseDatabaseClient, TranscriptionData,
)


CLIENT_METHODS = {
    DatabaseApiClient: (
        "__init__", "close", "tables", "schema", "list", "query",
        "create", "get", "update", "delete", "upsert",
    ),
    SupabaseDatabaseClient: (
        "__init__", "from_env", "close", "list", "query", "get",
        "create", "create_many", "update", "delete", "upsert",
    ),
    AsyncSupabaseDatabaseClient: (
        "__init__", "from_env", "close", "list", "query", "get",
        "create", "create_many", "update", "delete", "upsert",
    ),
}

MODELS = tuple(ApiData.__subclasses__())


def test_every_public_client_api_has_documentation() -> None:
    for client, names in CLIENT_METHODS.items():
        assert inspect.getdoc(client)
        for name in names:
            assert inspect.getdoc(getattr(client, name)), f"{client.__name__}.{name} needs docs"


def test_crud_apis_include_examples() -> None:
    for client, names in CLIENT_METHODS.items():
        for name in names:
            if name in {"__init__", "close"}:
                continue
            assert "Example" in inspect.getdoc(getattr(client, name))


def test_typed_payloads_have_documentation() -> None:
    assert len(MODELS) == 19
    for model in MODELS:
        assert inspect.getdoc(model)


def test_transcription_payload_uses_sequence_number() -> None:
    payload = TranscriptionData(
        transcription_id=UUID("00000000-0000-0000-0000-000000000001"),
        meeting_id=UUID("00000000-0000-0000-0000-000000000002"),
        speaker_user_id=UUID("00000000-0000-0000-0000-000000000003"),
        sequence_number=4,
        text="Test transcript",
    )

    assert payload.sequence_number == 4
    assert "start_ms" not in TranscriptionData.model_fields
    assert "end_ms" not in TranscriptionData.model_fields
