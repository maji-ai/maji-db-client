import inspect

from uuid import UUID

from maji_db_client import (
    ApiData, AsyncSupabaseDatabaseClient, ChatData, ClarificationData,
    DatabaseApiClient, MeetingData, ProjectData, SupabaseDatabaseClient,
    TranscriptionData,
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
    assert len(MODELS) == 20
    for model in MODELS:
        assert inspect.getdoc(model)


def test_project_chat_and_meeting_fields_match_database_contract() -> None:
    assert ProjectData.model_fields["is_active"].default is True
    assert ChatData.model_fields["project_id"].default is None
    assert MeetingData.model_fields["meeting_link"].default is None
    assert MeetingData.model_fields["meeting_platform"].default is None


def test_clarification_payload_matches_database_contract() -> None:
    payload = ClarificationData(
        meeting_id=UUID("00000000-0000-0000-0000-000000000001"),
        clarification_content="Clarified answer",
        trigger_content="Original question",
        trigger_type="question",
        feedback=True,
    )

    assert payload.clarification_id is None
    assert ClarificationData.model_fields["feedback"].is_required()
    assert not ClarificationData.model_fields["clarification_id"].is_required()
    assert "created_at" not in ClarificationData.model_fields


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
