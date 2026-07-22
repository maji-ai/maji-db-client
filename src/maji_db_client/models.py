"""Typed request payloads accepted by both Maji database clients.

Pass these Pydantic models to ``create``, ``create_many``, or ``upsert`` for
validation and IDE autocomplete. For partial updates, dictionaries are usually
best because they contain only the fields that should change.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApiData(BaseModel):
    """Base payload that rejects unknown or misspelled database fields."""

    model_config = ConfigDict(extra="forbid")


class OrganizationData(ApiData):
    """Create or replace an organization; the client injects its ID."""

    name: str
    industry: str
    size_min: int
    size_max: int
    primary_language: str
    organization_status: str = "active"
    context_prompt: str | None = None


class UserData(ApiData):
    """Create or upsert a user; ``password_hash`` must never be plaintext."""

    user_id: UUID
    name: str
    email: str
    job_title: str
    department_id: UUID | None = None
    password_hash: str | None = None
    system_role: str = "member"
    account_status: str = "active"
    first_login_date: date | None = None
    last_login_at: datetime | None = None


class DepartmentData(ApiData):
    """Create or upsert a department led by an existing tenant user."""

    department_id: UUID
    leader_user_id: UUID
    name: str
    description: str
    department_status: str = "active"


class ProjectData(ApiData):
    """Create or upsert a project, optionally attached to a department."""

    project_id: UUID
    name: str
    description: str
    department_id: UUID | None = None
    project_status: str = "active"
    context_prompt: str | None = None


class DocumentData(ApiData):
    """Store metadata for a file already uploaded to Supabase Storage."""

    document_id: UUID
    uploaded_by_user_id: UUID
    title: str
    description: str
    storage_key: str
    file_size_bytes: int
    original_filename: str


class ParentChunkData(ApiData):
    """Link an extracted parent chunk to its source document."""

    chunk_id: UUID
    document_id: UUID
    mdfile_storage_key: str


class MeetingData(ApiData):
    """Create or upsert a meeting using timezone-aware datetimes."""

    meeting_id: UUID
    project_id: UUID
    title: str
    scheduled_at: datetime
    duration_seconds: int | None = None
    n_attendees: int | None = None
    summary: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    currently_running: bool = False


class TranscriptionData(ApiData):
    """Store one speaker-attributed STT transcript segment."""

    transcription_id: UUID
    meeting_id: UUID
    speaker_user_id: UUID
    start_ms: int
    end_ms: int
    text: str
    language: str | None = None
    chunk_id: UUID | None = None


class TaskData(ApiData):
    """Create a meeting task assigned to exactly one tenant user."""

    task_id: UUID
    meeting_id: UUID
    user_id: UUID
    title: str
    deadline: datetime
    description: str | None = None
    system_status: str = "todo"


class ChatData(ApiData):
    """Create a chat opened by an existing tenant user."""

    chat_id: UUID
    opened_by_user_id: UUID
    title: str


class MessageData(ApiData):
    """Append a message to an existing chat; ``message_id`` is generated."""

    chat_id: UUID
    sender_role: str
    content: str
    message_type: str = "text"
    message_id: int | None = None


class SectionSummaryData(ApiData):
    """Create a summary section under one meeting."""

    meeting_id: UUID
    summary_text: str
    section_id: int | None = None


class SectionBulletPointData(ApiData):
    """Create a bullet point under an existing meeting summary section."""

    meeting_id: UUID
    section_id: int
    point_text: str
    point_id: int | None = None


class InvitationData(ApiData):
    """Create a tenant invitation between two pre-existing users."""

    invitation_id: UUID
    invited_by_user_id: UUID
    invited_user_id: UUID
    invitee_email: str
    token_hash: str
    expires_at: datetime
    invitation_status: str = "pending"
    accepted_at: datetime | None = None


class MeetingAttendeeData(ApiData):
    """Link one existing user to one existing meeting."""

    meeting_id: UUID
    user_id: UUID
    talk_time_seconds: int | None = None


class MeetingCoordinatorData(ApiData):
    """Link one coordinating user to one meeting."""

    meeting_id: UUID
    user_id: UUID


class ProjectUserData(ApiData):
    """Link one existing user to one existing project."""

    project_id: UUID
    user_id: UUID


class DocumentProjectData(ApiData):
    """Link one existing document to one existing project."""

    document_id: UUID
    project_id: UUID


class DepartmentDocumentData(ApiData):
    """Link one existing document to one existing department."""

    department_id: UUID
    document_id: UUID
