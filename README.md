# Maji DB Client

Typed synchronous and asynchronous Python clients for tenant-scoped access to Supabase and the private Maji Database API.

## Install

From PyPI after publication:

```bash
pip install maji-db-client
```

From GitHub:

```bash
pip install "maji-db-client @ git+https://github.com/maji-ai/maji-db-client.git@main"
```

## Backend configuration

Keep the Supabase key in the backend service's environment or cloud secret manager:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SECRET_KEY=sb_secret_REPLACE_ME
```

The legacy `SUPABASE_SERVICE_ROLE_KEY` is also recognized. Never commit either key or expose it to frontend/browser/mobile code.

`organization_id` is not an environment setting. Resolve it separately for each incoming request from a verified JWT or server-side membership lookup.

## Async usage (recommended for async web services)

Create one shared HTTP connection pool for the application, then create a lightweight organization-scoped wrapper per request:

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from maji_db_client import AsyncSupabaseDatabaseClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.supabase_http = httpx.AsyncClient()
    yield
    await app.state.supabase_http.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/projects")
async def list_projects(
    request: Request,
    current_user=Depends(get_verified_user),
):
    db = AsyncSupabaseDatabaseClient.from_env(
        current_user.organization_id,
        http_client=request.app.state.supabase_http,
    )
    return await db.list("projects")
```

Two simultaneous requests safely use separate tenant wrappers while sharing the same pool:

```text
shared httpx.AsyncClient
├── request A wrapper → organization A
└── request B wrapper → organization B
```

## Synchronous usage

Use the synchronous client for CLI tools, seed scripts, background jobs, and regular FastAPI `def` endpoints:

```python
from maji_db_client import SupabaseDatabaseClient

with SupabaseDatabaseClient.from_env(current_user.organization_id) as db:
    projects = db.list("projects")
```

## CRUD examples

```python
from uuid import uuid4
from maji_db_client import ProjectData

project = await db.create("projects", ProjectData(
    project_id=uuid4(),
    name="Example",
    description="Created by another service",
    is_active=True,
))

active = await db.query(
    "projects",
    {"project_status": "active"},
    order_by="created_at",
    direction="desc",
)

updated = await db.update(
    "projects",
    {"project_id": project["project_id"]},
    {"description": "Updated description"},
)

deleted = await db.delete(
    "projects",
    {"project_id": project["project_id"]},
)
```

The sync client uses the same method names without `await`.

Additional methods:

- `list`: paginated table rows
- `get`: one row by key
- `create_many`: bulk insert
- `upsert`: atomic PostgREST merge on a unique key

Typed models provide validation and autocomplete. Tables without a dedicated model accept dictionaries.

Current schema fields:

- `ProjectData.is_active` defaults to `True`.
- `ChatData.project_id` optionally links a chat to one project.
- `MeetingData.meeting_link` and `meeting_platform` are optional.

Clarifications belong to a meeting. The database generates `clarification_id` and `created_at`; use the returned ID together with `meeting_id` for later operations:

```python
from maji_db_client import ClarificationData

clarification = await db.create("clarifications", ClarificationData(
    meeting_id=meeting_id,
    clarification_content="The clarified answer",
    trigger_content="The text that triggered clarification",
    trigger_type="question",
    feedback=True,
))

key = {
    "meeting_id": meeting_id,
    "clarification_id": clarification["clarification_id"],
}
await db.update("clarifications", key, {"feedback": False})
```

Transcriptions use `sequence_number` for optional STT ordering; the removed `start_ms` and `end_ms` fields must not be sent:

```python
from maji_db_client import TranscriptionData

segment = TranscriptionData(
    transcription_id=transcription_id,
    meeting_id=meeting_id,
    speaker_user_id=speaker_user_id,
    sequence_number=1,
    text="Transcript text",
    language="en",
    chunk_id=chunk_id,
)
saved = await db.create("transcriptions", segment)
```

## Private Maji API

`DatabaseApiClient` remains available for services using the protected Maji FastAPI database endpoint rather than direct Supabase access.

```python
from maji_db_client import DatabaseApiClient

with DatabaseApiClient(
    "http://127.0.0.1:8001",
    "meeting-service",
    organization_id,
) as db:
    meetings = db.list("meetings")
```

## Security

Secret and legacy service-role keys bypass Row Level Security. The package always injects and filters the configured organization ID, which prevents accidental cross-tenant operations during normal usage, but anyone holding the key can bypass this package and call Supabase directly.

Only give server keys to trusted backend services. Never trust an arbitrary organization UUID supplied by a frontend.

## API help

All public methods include arguments, return values, errors, and examples:

```python
help(AsyncSupabaseDatabaseClient.query)
help(SupabaseDatabaseClient.create)
help(ProjectData)
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m build
python -m twine check dist/*
```
