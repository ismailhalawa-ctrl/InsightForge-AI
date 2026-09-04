# InsightForge AI — Backend

A multi-source **Voice-of-Customer / Community Intelligence** platform: collect feedback from
any source a *connector* implements, normalize it into one generic pipeline, and run the same
language-aware sentiment/Text Intelligence/insight extraction over all of it. YouTube comments and
uploaded CSV/XLSX/JSON files are the first two connectors, not a hardcoded assumption baked into
the core — see [Connector architecture](#connector-architecture) below for how a new source plugs
in without touching Analysis Jobs, Evidence, Insights, auth, or workers.

## What currently works

- YouTube video metadata lookup (`POST /api/v1/youtube/video`)
- YouTube comment retrieval with caching (`GET /api/v1/youtube/{video_id}/comments`)
- Full video sentiment analysis: comment collection, text processing, multi-model sentiment
  scoring, and a summary/coverage report (`GET /api/v1/youtube/{video_id}/sentiment`)
- A source-agnostic **Text Intelligence** rule layer (emoji, spam, sarcasm, Arabizi, lexical
  polarity, negation, contrast, target, and intent signals) that enriches sentiment with
  explainable, deterministic evidence before/alongside the transformer models — see
  [Text Intelligence](#text-intelligence) below
- Persistent, resumable, cancellable **analysis jobs** for large comment volumes (100–5000+
  comments), backed by PostgreSQL and processed by a separate worker process so no HTTP request
  is held open for the duration — see [Persistent Analysis Jobs](#persistent-analysis-jobs) below
- **Content Intelligence**: evidence-grounded topics, complaints, suggestions, questions,
  praise, criticism, audience requests, repeated themes, and recommendations generated from a
  completed job's persisted evidence, in `local`, `ai` (Gemini/OpenAI), or `hybrid` mode — see
  [Content Intelligence](#content-intelligence) below
- A generic **multi-source domain** (connectors, datasets, records, checkpoints) that YouTube now
  runs through as its first implementation, plus a capability-discovery API so a client can ask
  which sources are actually usable — see
  [Multi-source domain foundation](#multi-source-domain-foundation) below
- **File import**: upload a CSV, XLSX, or JSON file of existing feedback, map its columns, and run
  it through the same collection/Text Intelligence/Content Intelligence pipeline as YouTube — see
  [File import connector](#file-import-connector) below
- Swagger UI and ReDoc for exploring and calling the API interactively

**Not implemented yet:** a custom frontend dashboard, charts, exports, RAG chat, OAuth/social
login, organizations/teams, billing/subscriptions, a Celery-style task queue, per-comment
sentiment persistence (only the final aggregated report is persisted per job — see
[Resume and checkpoint boundary](#resume-and-checkpoint-boundary)), and any connector beyond
YouTube -- GitHub issues, file import (CSV/JSON), app store/Google Play reviews, and survey/
support-ticket sources all have reserved `SourceType` enum values and always report
`available=false` from the capabilities API until a real connector is built for them (see
[Multi-source domain foundation](#multi-source-domain-foundation)). See
[Current UI limitations](#current-ui-limitations) below.

Redis **is** present, but only as the distributed rate-limiting backend and transient outbox
signaling — it is not a task queue or message broker; analysis jobs and the email outbox remain
PostgreSQL-backed, worker-polled queues (see
[Distributed rate limiting, email verification, and password reset](#distributed-rate-limiting-email-verification-and-password-reset)).

## Requirements

- Python 3.13 (this is the version this guide was tested against; `pyproject.toml` declares a
  minimum of `^3.11`, but no version between 3.11 and 3.13 has been verified in this repository)
- Docker Desktop (recommended, for PostgreSQL) **or** a locally installed PostgreSQL 16
- ~3–5 GB free disk space the first time sentiment models are downloaded (see
  [First model download behavior](#first-model-download-behavior))

## Actual dependency workflow (read this first)

`pyproject.toml` is written in Poetry's dependency format, but **Poetry is not installed or used
in this environment** — there is no `poetry.lock` file, and the `poetry` command is not
available. The tested, working setup is a plain virtual environment with `pip`. Use the commands
below, not `poetry install`.

## Project setup

All commands in this guide assume your terminal's working directory is `backend/` (the folder
this file is in), since the app reads its `.env` file relative to the current directory.

### 1. Virtual environment

PowerShell:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Command Prompt:

```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
```

macOS/Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

There is no lock file, so install the packages listed in `pyproject.toml` directly:

```powershell
python -m pip install --upgrade pip
python -m pip install fastapi "uvicorn[standard]" sqlalchemy alembic pydantic pydantic-settings psycopg2-binary python-dotenv "httpx>=0.28.1" langdetect emoji transformers torch sentencepiece protobuf
python -m pip install pytest pytest-asyncio pytest-cov black ruff mypy pre-commit
```

`torch` and `transformers` are large downloads (roughly 1–2 GB combined) — this step can take
several minutes depending on your connection.

## Environment variables

Copy the example file into place. **You need two copies**: one inside `backend/` (read by the
FastAPI app and Alembic) and one at the repository root (read by `docker/docker-compose.yml`).

PowerShell:

```powershell
Copy-Item ..\.env.example .env
Copy-Item ..\.env.example ..\.env
```

Command Prompt:

```cmd
copy ..\.env.example .env
copy ..\.env.example ..\.env
```

macOS/Linux:

```bash
cp ../.env.example .env
cp ../.env.example ../.env
```

**Important edit:** `.env.example`'s `DATABASE_URL` uses the hostname `db`, which only resolves
inside the Docker network (i.e. if the backend itself is also containerized). Since this guide
runs PostgreSQL in Docker but FastAPI directly on your machine, open `backend/.env` and change
the host from `db` to `localhost`:

```
DATABASE_URL=postgresql://insightforge:changeme@localhost:5432/insightforge
```

Add your own key to `YOUTUBE_API_KEY` in `backend/.env` when you're ready to run a real analysis
(see [First real sentiment run](#first-real-sentiment-run)). Never commit a real key — both
`.env` files are already covered by `.gitignore`.

Variables you will actually use, with their purpose:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string used by the app and Alembic |
| `YOUTUBE_API_KEY` | Your YouTube Data API v3 key (leave blank until you have one) |
| `YOUTUBE_VIDEO_CACHE_TTL_MINUTES` | How long cached video metadata is considered fresh |
| `YOUTUBE_COMMENT_CACHE_TTL_MINUTES` | How long cached comments are considered fresh |
| `YOUTUBE_SENTIMENT_COMMENT_LIMIT` | Max comments the sentiment endpoint collects per run |
| `SENTIMENT_ARABIC_MODEL` / `SENTIMENT_ENGLISH_MODEL` / `SENTIMENT_MIXED_MODEL` | Hugging Face model identifiers per language route |
| `SENTIMENT_DEVICE` | `auto`, `cpu`, or `cuda` |
| `SENTIMENT_MIN_CONFIDENCE` | Below this confidence, a prediction is reported as `uncertain` |
| `SENTIMENT_BATCH_SIZE` | Comments per inference batch |
| `MIXED_MIN_ARABIC_TOKENS` / `MIXED_MIN_ENGLISH_TOKENS` / `MIXED_MIN_SCRIPT_RATIO` / `MIXED_IGNORED_TECHNICAL_TERMS` | Tuning for mixed-language detection |

## PostgreSQL startup

This repository already has a Docker Compose file at `docker/docker-compose.yml`. Start only the
database service (the `backend`/`frontend` services in that file are separate scaffolding not
covered by this guide):

```powershell
docker compose -f ..\docker\docker-compose.yml up -d db
```

Confirm it's healthy before continuing:

```powershell
docker inspect --format "{{.State.Health.Status}}" docker-db-1
```

Wait until this prints `healthy` (typically a few seconds).

**No Docker?** Install PostgreSQL 16 locally, create a database and user matching your
`backend/.env` (`insightforge` / `changeme` / database `insightforge` by default), and make sure
`DATABASE_URL` points at it.

## Database migrations

```powershell
python -m alembic upgrade head
```

This creates every table at the latest schema. Verify with:

```powershell
python -m alembic current
```

You should see `fba31548b594 (head)` — the single current head across every sprint's migrations
(`python -m alembic heads` must always list exactly one).

## Running FastAPI

From `backend/`, with the virtual environment activated:

```powershell
python -m uvicorn app.main:app --reload
```

- Local URL: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

`GET /health` reports `"database": "ok"` or `"database": "unavailable"` — use it as a quick
sanity check before testing anything else.

## Current UI limitations

**There is no custom frontend dashboard.** The `frontend/` directory in this repository is an
unfinished scaffold (a single placeholder page) and is not part of this guide. The current
interface to this project **is** FastAPI's Swagger UI at `/docs`. ReDoc (`/redoc`) is read-only
API documentation, not an interactive tool or a product dashboard.

### Using Swagger UI

1. Open `http://127.0.0.1:8000/docs`.
2. Expand the endpoint you want (e.g. `GET /api/v1/youtube/{video_id}/sentiment`).
3. Click **Try it out**.
4. Enter the bare 11-character YouTube video ID in the `video_id` field — for example
   `dQw4w9WgXcQ`. The service does accept a full URL internally, but Swagger's path parameter
   field is not URL-encoding-aware for slashes, so use the bare ID here.
5. Click **Execute**.
6. Read the response body and status code in the panel below.

## Running a video sentiment analysis

```
GET /api/v1/youtube/{video_id}/sentiment
```

### First real sentiment run

1. Add a valid YouTube Data API v3 key to `YOUTUBE_API_KEY` in `backend/.env`.
2. Start PostgreSQL (see above) and confirm it's healthy.
3. Apply migrations: `python -m alembic upgrade head`.
4. Start FastAPI: `python -m uvicorn app.main:app --reload`.
5. Open `http://127.0.0.1:8000/docs`.
6. Execute `GET /api/v1/youtube/{video_id}/sentiment` with a real video ID.

### Example response shape

This illustrates the response's structure — actual numbers depend on the video's real comments:

```json
{
  "video_id": "dQw4w9WgXcQ",
  "summary": {
    "total_comments": 87,
    "processable_comments": 85,
    "analyzed_comments": 80,
    "unsupported_comments": 5,
    "positive_count": 50,
    "negative_count": 20,
    "uncertain_count": 10,
    "positive_percentage": 62.5,
    "negative_percentage": 25.0,
    "uncertain_percentage": 12.5,
    "overall_sentiment": "positive",
    "average_confidence": 0.87,
    "language_breakdown": { "arabic": 30, "english": 45, "mixed": 5, "unsupported": 7 },
    "comments_available": 87,
    "collection_complete": true,
    "collection_limit": 100,
    "coverage_percentage": 91.95,
    "spam_count": 3,
    "clean_comments_count": 84,
    "sarcasm_count": 4,
    "question_count": 6,
    "request_count": 5,
    "suggestion_count": 3,
    "complaint_count": 2,
    "praise_count": 40,
    "arabizi_count": 2,
    "emoji_only_count": 6,
    "escalation_recommended_count": 9,
    "unsupported_breakdown": [
      { "reason": "unsupported_language", "count": 4, "percentage": 4.6, "examples": ["..."] },
      { "reason": "empty_text", "count": 1, "percentage": 1.15, "examples": [""] }
    ],
    "top_emojis": [{ "emoji": "🔥", "count": 12 }, { "emoji": "❤️", "count": 9 }],
    "target_breakdown": { "audio": 3, "editing": 2, "unknown": 60 },
    "intent_breakdown": { "praise": 40, "question": 6, "request": 5 },
    "clean_summary": {
      "clean_comments_count": 84,
      "analyzed_comments": 78,
      "positive_count": 49,
      "negative_count": 19,
      "uncertain_count": 10,
      "positive_percentage": 62.82,
      "negative_percentage": 24.36,
      "uncertain_percentage": 12.82,
      "overall_sentiment": "positive",
      "average_confidence": 0.87
    }
  },
  "positive_examples": [{ "comment": "Great video!", "confidence": 0.95, "language": "en" }],
  "negative_examples": [],
  "uncertain_examples": []
}
```

`comments_available` is intentionally always equal to `total_comments` — it is kept as a
separately named field for API clarity, not because the two values can diverge. The top-level
counts/percentages (`positive_count`, `negative_percentage`, etc.) are **raw** — they include
spam-flagged comments. `clean_summary` recomputes the same shape over non-spam comments only, so
neither view hides the other's denominator.

### First-model-download behavior

The first time a request needs a given language route (Arabic, English, or mixed), that route's
Hugging Face model is downloaded to your local cache. Only the models actually required by the
video's comments load — if a video has no Arabic comments, the Arabic model never loads.

- This first request will take substantially longer than later ones — expect anywhere from tens
  of seconds to a few minutes depending on your connection; there is no fixed guaranteed
  duration.
- The application is **not frozen** during this time — download and load progress is normally
  visible in the terminal running `uvicorn`.
- Disk usage and memory increase as each model loads.
- Once a model is loaded, the process keeps it in memory — later requests using the same route
  are much faster as long as the `uvicorn` process stays running.

## Example requests

Replace `VIDEO_ID` with a real 11-character video ID.

curl.exe:

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/youtube/VIDEO_ID/sentiment"
```

PowerShell (`Invoke-RestMethod`):

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/youtube/VIDEO_ID/sentiment"
```

macOS/Linux:

```bash
curl "http://127.0.0.1:8000/api/v1/youtube/VIDEO_ID/sentiment"
```

Avoid PowerShell's `curl`/`wget` *aliases* for anything beyond the simplest GET — they map to
`Invoke-WebRequest`, which behaves differently from real curl (different flags, different
response object). Use `curl.exe` explicitly, or `Invoke-RestMethod`.

## Persistent Analysis Jobs

For large comment volumes (hundreds to thousands of comments), don't use the synchronous
`/sentiment` endpoint above — it holds one HTTP request open until every comment is analyzed.
Instead, create a **job**: it returns immediately, runs on a separate worker process, and can be
polled, cancelled, and resumed.

### Architecture: why a database-backed worker, not Celery/Redis

This project has no message queue, no Redis, and no async DB driver (`psycopg2`, plain
`sqlalchemy.orm.Session`, matching everything else in this codebase). Adding Celery/Redis for a
single local worker would be new infrastructure with no current justification. Instead:

- **PostgreSQL is the only source of truth.** Job state, progress, and checkpoints are columns
  on the `analysis_jobs` row — nothing meaningful lives only in a Python process's memory.
- **FastAPI never runs a job.** `AnalysisJobService` (used by the API router) only creates,
  reads, lists, and cancels rows. All collection/analysis work happens in `AnalysisJobRunner`,
  driven exclusively by `python -m app.workers.analysis_worker`.
- **The worker is a plain polling loop** that atomically claims one queued/retryable/lease-expired
  job at a time using `SELECT ... FOR UPDATE SKIP LOCKED` (see
  `AnalysisJobRepository.claim_next_job`). Two workers racing this query can never receive the
  same row — proven with real concurrent threads against real PostgreSQL in
  `tests/integration/analysis_job/test_atomic_claiming.py`, not just asserted.
- This keeps the door open for a real queue later (SQS, Celery, etc.) without changing the job
  model or API contract — only the claiming loop inside the worker would need to change.

### Job model

`AnalysisJob` (table `analysis_jobs`) tracks, among other fields: `status` (lifecycle),
`stage` (current operation), `progress_percentage`, per-phase comment counters
(`comments_discovered/collected/available/processed/analyzed/failed`), `collection_complete`,
`cancellation_requested`, `attempt_count`/`max_attempts`, `next_attempt_at` (retry backoff),
`last_checkpoint` (JSONB — collection page token / batch index), `error_code`/`error_message`
(sanitized), `worker_id`/`lease_expires_at` (claim ownership), and the usual lifecycle timestamps.
The completed report is stored separately in `analysis_job_results` (`report_json` JSONB +
`schema_version`), so `GET .../result` never reruns any model.

**Statuses:** `queued`, `running`, `retrying`, `completed`, `failed`, `cancelled`.
**Stages:** `validating_source`, `loading_metadata`, `collecting_comments`, `processing_text`,
`running_text_intelligence`, `running_sentiment`, `aggregating`, `storing_result`, `completed`.

> `running_sentiment` is defined for schema completeness but is not currently emitted as its own
> persisted stage: `TextIntelligenceService.analyze()` intentionally bundles rule processing and
> model sentiment inference into one call (this sprint deliberately did not split that pipeline
> apart — see Part 1's "do not duplicate the sentiment/Text Intelligence pipeline"), so both are
> reported together under `running_text_intelligence`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/analysis/jobs` | Create a job. Returns **202** + `job_id` immediately. |
| GET | `/api/v1/analysis/jobs/{job_id}` | Lifecycle status, stage, progress, counters, sanitized error. |
| GET | `/api/v1/analysis/jobs/{job_id}/result` | Completed report. **409** if not completed yet, **404** if unknown. |
| POST | `/api/v1/analysis/jobs/{job_id}/cancel` | Persistent cancellation request. Idempotent once cancelled. |
| GET | `/api/v1/analysis/jobs` | Paginated list, newest first, optional `?status=` filter. |

The existing `GET /api/v1/youtube/{video_id}/sentiment` endpoint is unchanged and still the right
choice for quick demos or small analyses.

### Swagger workflow

1. Open `http://127.0.0.1:8002/docs`.
2. `POST /api/v1/analysis/jobs` with `{"source_type": "youtube", "source": "VIDEO_ID_OR_URL",
   "comment_limit": 500}` → copy `job_id` from the response.
3. `GET /api/v1/analysis/jobs/{job_id}` repeatedly → watch `status`, `progress.progress_percentage`,
   `progress.current_stage` change (needs the worker running — see below).
4. `POST /api/v1/analysis/jobs/{job_id}/cancel` any time before completion, or let it finish.
5. `GET /api/v1/analysis/jobs/{job_id}/result` once `status` is `completed`.

### Comment limits and collection modes

`comment_limit` accepts any positive integer up to `ANALYSIS_MAX_COMMENT_LIMIT` (default 5000);
omit it to use `ANALYSIS_DEFAULT_COMMENT_LIMIT` (default 100). `collection_mode` accepts `bounded`
(default) or `all_available` — **`all_available` is defined in the schema but rejected with 422
at creation time** in this release: it isn't implemented because quota protection, cancellation,
progress, and resume semantics for a truly unbounded YouTube comment stream aren't all reliable
yet. Use a large `comment_limit` with `bounded` instead.

### Progress formula (stage-weighted, monotonic)

Total available comments aren't always known up front, so progress is weighted by stage rather
than a single global counter:

| Stage | Weight |
|---|---|
| Validating source + loading metadata | 5% |
| Collecting comments | 35% |
| Text Intelligence + sentiment inference (combined — see note above) | 50% |
| Aggregating + storing result | 10% |

Within collection, progress is `collected / requested_limit` inside that 35% band (and the stage
is marked fully complete immediately if YouTube runs out of comments before the limit is
reached). Within analysis, progress is `batches_completed / total_batches` inside the 50% band,
where a batch is `ANALYSIS_BATCH_SIZE` comments (default 200) sent to `TextIntelligenceService`
in one call — checkpointed after every batch.

**Progress never decreases.** `AnalysisJobRepository.update_progress` clamps every write to
`max(current_value, new_value)`. This matters most on retry: if an attempt fails at, say, 75%
progress and is retried, the new attempt's real computed progress starts back around 40% (once
collection re-verifies from persisted comments) — the *displayed* `progress_percentage` stays
pinned at 75% throughout that stretch and only starts advancing again once the new attempt's
real progress exceeds the old high-water mark. `stage`/`stage_progress_percentage` are not
subject to this clamp — they describe the current attempt's actual current operation, which is
allowed to look "earlier" than the frozen overall percentage.

### Resume and checkpoint boundary

Jobs survive FastAPI restart, worker restart, and temporary DB/YouTube failures because state
lives in PostgreSQL, not in the worker's memory. Precisely what resumes and what doesn't:

- **Collection resumes from its own checkpoint.** `last_checkpoint` stores `next_page_token` and
  `comments_collected` after every page. If this job is reclaimed after a crash, it continues
  pagination from that token — it does not refetch pages it already has, and `bulk_upsert`
  deduplicates by `youtube_comment_id` regardless.
- **A brand-new job (no checkpoint of its own) reuses already-persisted comments** if the video's
  own collection is already marked complete or already has enough comments (same TTL-based reuse
  the synchronous endpoint has always had) — no redundant API calls in that case.
- **Cross-job resume has a real, YouTube-imposed limit:** a *different*, later job for the same
  video that asks for *more* comments than an earlier job already collected cannot resume from
  where that earlier job's pagination left off (YouTube's API has no offset-based pagination) —
  it re-paginates from page 1. Already-persisted comments are still deduplicated, so no duplicate
  rows are ever created; only redundant API calls are possible in this specific scenario.
- **Per-comment sentiment is intentionally NOT persisted** (Part 3 explicitly allows omitting
  this "if not required for resume efficiency and clearly justified"). Justification: rule
  processing and batched model inference over already-collected comments are cheap relative to
  network I/O (see performance numbers below), so retrying the whole analysis phase from batch 0
  is a bounded, small cost — not worth the complexity of persisting and resuming partial batch
  results. **In practice: comment collection resumes from persistence; sentiment analysis
  restarts from the beginning on any retry.**
- Completed jobs are never re-executed (excluded from the claim query's status filter).
  Cancelled jobs never resume automatically.

### Cancellation

`POST .../cancel` sets `cancellation_requested=true` in PostgreSQL. A `queued` job transitions
directly to `cancelled`. A `running` job's worker checks the flag (a fresh DB read, not a
process-local flag) between collection pages, between analysis batches, and before aggregation —
never via unsafe thread termination — and exits cleanly, leaving whatever was already persisted
in place. Cancelling an already-cancelled job returns 200 idempotently; cancelling a
completed/failed job returns 409.

### Retry policy and error classification

Failures are classified using the *existing* exception taxonomy (no new exception types were
added solely for this) into retryable and non-retryable:

- **Retryable** (scheduled via bounded exponential backoff — `ANALYSIS_RETRY_BASE_DELAY_SECONDS`
  doubling up to `ANALYSIS_RETRY_MAX_DELAY_SECONDS`, up to `ANALYSIS_JOB_MAX_ATTEMPTS` attempts):
  temporary DB unavailability, YouTube service errors/timeouts, sentiment-service unavailability,
  model load failures.
- **Non-retryable** (fail immediately with a sanitized `error_code`): invalid video ID/URL, video
  not found, comments disabled, YouTube auth errors, **quota exceeded** (deliberately not
  retried — YouTube doesn't give a reliable retry-after signal, so retrying quickly would just
  waste more quota), invalid sentiment/Text Intelligence configuration, unsupported source type,
  invalid job configuration, and any unclassified/unexpected error.

Only `error_code` and a sanitized `error_message` are ever persisted or returned — never a raw
exception string, stack trace, or secret.

### Idempotency

Pass an `Idempotency-Key` header on job creation. The same key always returns the same job
(enforced by a unique DB constraint plus the same create-then-refetch-on-conflict pattern already
used by `YouTubeRepository.save_or_update`, so a race between two identical concurrent requests
can't create two jobs). Different keys (or no key) always create separate jobs — there's no
implicit merging of what might be two intentionally separate analyses.

### Configuration

| Setting | Default | Meaning |
|---|---|---|
| `ANALYSIS_WORKER_POLL_INTERVAL_SECONDS` | 5 | How often an idle worker checks for new jobs |
| `ANALYSIS_JOB_LEASE_SECONDS` | 120 | How long a claim is valid before another worker may reclaim it |
| `ANALYSIS_JOB_MAX_ATTEMPTS` | 3 | Attempts before a retryable failure becomes terminal |
| `ANALYSIS_PROGRESS_UPDATE_INTERVAL` | 1 | Reserved for future batch-level progress throttling |
| `ANALYSIS_DEFAULT_COMMENT_LIMIT` | 100 | Used when `comment_limit` is omitted |
| `ANALYSIS_MAX_COMMENT_LIMIT` | 5000 | Hard ceiling enforced at job creation (422 above it) |
| `ANALYSIS_BATCH_SIZE` | 200 | Comments per `TextIntelligenceService.analyze()` call during a job |
| `ANALYSIS_RETRY_BASE_DELAY_SECONDS` | 5 | First retry backoff |
| `ANALYSIS_RETRY_MAX_DELAY_SECONDS` | 300 | Backoff ceiling |
| `ANALYSIS_EMBEDDED_WORKER_ENABLED` | `true` in development, `false` otherwise, when unset | Runs the worker on a background thread of the API process (see below) |

### Embedded worker (local development only)

`python -m uvicorn app.main:app --reload` alone is enough to both serve the API and process
queued analysis jobs: FastAPI's lifespan starts `app.workers.analysis_worker.run_worker()` (the
exact same claim/lease/retry/execute loop the standalone worker process uses) on a background
thread, and stops it on shutdown. This is controlled by `ANALYSIS_EMBEDDED_WORKER_ENABLED`
(`app/config/settings.py`): left unset, it's `true` only when `ENVIRONMENT=development` and
`false` in every other environment; setting it explicitly always wins.

- `uvicorn --reload` runs a separate file-watching supervisor process that never executes the
  ASGI lifespan protocol itself -- only the actual reloaded server subprocess does -- so the
  embedded worker starts exactly once per running server, not once per reload-watcher.
- A second embedded-worker start attempt in the same process (e.g. a defensive re-entry) is a
  no-op; `app/workers/embedded.py` tracks the single running instance per process.
- **Production must not rely on this.** A single background thread cannot scale horizontally and
  is killed the moment the API process restarts or is redeployed, instead of surviving
  independently like a dedicated worker deployment. Set `ANALYSIS_EMBEDDED_WORKER_ENABLED=false`
  and run `python -m app.workers.analysis_worker` (one or more instances) as its own process --
  a warning is also logged at startup (`embedded_worker_enabled_in_production`) if the embedded
  worker is ever left enabled with `ENVIRONMENT=production`.

### Running the worker locally

Three terminals, in addition to Docker Postgres:

Terminal 1 — PostgreSQL (see [PostgreSQL startup](#postgresql-startup)):

```powershell
docker compose -f docker/docker-compose.yml up -d db
```

Terminal 2 — FastAPI:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002
```

Terminal 3 — worker:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -m app.workers.analysis_worker
```

The worker logs `worker_started`, `job_claimed`, `job_completed`/`job_failed_terminal`/
`job_cancelled`/`job_retry_scheduled`/`job_released_for_shutdown` as structured JSON — never
comment text or secrets. Stop it with `Ctrl+C`: it finishes checkpointing whatever unit of work is
in flight, releases the job back to `queued`/`retrying` with all progress intact, and exits — it
does not force-kill mid-batch.

### Concurrency

One job is processed at a time per worker process by design (this project's models are CPU-heavy
and this sprint deliberately did not add multiprocessing model workers). Run multiple `python -m
app.workers.analysis_worker` processes against the same database for more throughput — atomic
claiming guarantees they never step on each other; there is no configuration flag for in-process
concurrency yet.

## Multi-source domain foundation

Sprint 15 introduces a generic connector/dataset/record/checkpoint architecture so a future source
(GitHub issues, app store reviews, a CSV/JSON file upload) plugs into the *same* Analysis Job →
Evidence → Insight pipeline without modifying any of those three layers. YouTube is refactored to
be the first connector, not a special case the core knows about.

### Connector architecture

```
SourceConnector (app/connectors/base.py)          <- contract every source implements
  ├── validate_source()   -- parse/validate a reference, no network required
  ├── describe_source()   -- resolve real title/URL/metadata (network allowed)
  ├── get_capabilities()  -- what this connector supports, and whether it's usable right now
  ├── collect_page()      -- one paginated, checkpointable batch of NormalizedSourceRecord
  └── classify_error()    -- maps a connector-specific exception to (retryable, error_code)

ConnectorRegistry (app/connectors/registry.py)    <- resolves a connector by SourceType
  build_default_registry() registers YouTubeConnector for SourceType.youtube; every other
  SourceType enum value exists for forward compatibility but is_registered() is False for it.

YouTubeConnector (app/connectors/youtube.py)      <- wraps the existing YouTubeService/
  YouTubeClient/YouTubeCommentRepository pipeline exactly as before -- same caching, same TTLs,
  same YouTubeVideo/YouTubeComment tables -- and additionally emits NormalizedSourceRecord
  objects the generic pipeline consumes.
```

**Dependency direction is one-way and enforced by a test**
(`tests/unit/test_architecture_boundaries.py`, which parses every generic module's imports and
fails if a YouTube-specific module appears):

```
Connector  ->  NormalizedSourceRecord  ->  generic pipeline (ingestion / evidence / insights)
```

A connector never imports `AnalysisJob`, insight generation, sentiment, or Text Intelligence.
`AnalysisJobRunner` never imports a specific connector's client/service/repository/exception
classes — it only calls `SourceConnector` methods resolved through the registry. The one narrow,
documented exception is `AnalysisJobService.create_job()`, which still calls
`extract_video_id()` directly for a single synchronous, network-free reference check at job
creation time (see that class's docstring) — the runner, which does the actual collection work,
has no such exception.

### Generic domain models

| Model | Table | Purpose |
|---|---|---|
| `SourceConnection` | `source_connections` | A user's configured link to an external source (e.g. a connected GitHub org). Never stores credentials -- no credential vault exists yet, so connectors needing auth read it from application settings. |
| `SourceDataset` | `source_datasets` | One collectible unit (a video's comments, a repo's issues). Analysis jobs target a dataset, not a raw reference, so the same dataset can be re-analyzed and deduplicated across jobs. |
| `SourceRecord` | `source_records` | One normalized collected item (comment, review, ticket). `original_text` is bounded to `SOURCE_RECORD_TEXT_MAX_LENGTH`; `content_hash` is a SHA-256 of the (bounded) text. Unique on `(dataset_id, source_key)` -- the idempotency guarantee. |
| `CollectionCheckpoint` | `collection_checkpoints` | Resumable collection progress per `(dataset, connector)`, independent of any specific job. Updated via `SELECT ... FOR UPDATE`, the same row-lock pattern as refresh-token rotation and job claiming. |

`YouTubeVideo`/`YouTubeComment` are **not removed** -- they remain the YouTube connector's own
cache/dedup table, exactly as before. `SourceRecord` is a separate, source-agnostic table the
connector also populates; it is not a duplicate-for-duplicate's-sake table, it is what the generic
pipeline (evidence, future connectors) actually reads.

### YouTube adapter behavior

`YouTubeConnector.collect_page()` reuses `YouTubeService.ensure_video()` (TTL-cached metadata) and
the exact same `YouTubeClient.get_comments()` + `YouTubeCommentRepository.bulk_upsert()` calls the
pre-Sprint-15 runner made directly -- collection, caching, and quota behavior are byte-for-byte
unchanged. Each persisted `YouTubeComment` is additionally converted to a `NormalizedSourceRecord`
(`source_key`=`youtube_comment_id`, `engagement`={`like_count`, `reply_count`}, `author_reference`
= the channel id, never the display name) and handed to the generic ingestion layer, which
upserts it into `SourceRecord`. `describe_source()` resolves the real video title/URL once
collection starts (in the worker, never in the job-creation HTTP request) and updates the
dataset's placeholder display name.

### Dataset / record / evidence lifecycle

1. `POST /api/v1/analysis/jobs` resolves/creates a `SourceDataset` synchronously (no network call)
   via `SourceDatasetRepository.get_or_create`, keyed on `(user_id, source_type, external_id)`, and
   sets `AnalysisJob.source_dataset_id`. The dataset's `display_name` is a placeholder at this
   point (e.g. `youtube:dQw4w9WgXcQ`).
2. The worker's `AnalysisJobRunner` resolves the connector via the registry, calls
   `describe_source()` to fill in the real title/URL, then drives `collect_page()` in a loop,
   persisting `SourceRecord` rows through `SourceIngestionService` after every page.
3. Once collection completes, the runner reads all persisted `SourceRecord`s for the dataset
   (capped at the job's requested limit) and runs them through the *unchanged*
   `TextIntelligenceService.analyze(texts, source_keys)` -- Text Intelligence has never depended on
   `YouTubeComment` and required no changes.
4. Evidence is written to `AnalysisRecordEvidence` (see below) with `source_record_id` pointing at
   the `SourceRecord` row, `record_type`, `engagement`, and `occurred_at` populated generically.

### Generic evidence: `AnalysisRecordEvidence`

The pre-Sprint-15 `AnalysisCommentEvidence` model is renamed to **`AnalysisRecordEvidence`** --
the "retain table, generalize the model" strategy: the physical table name
(`analysis_comment_evidence`) and every existing column are kept unchanged for compatibility,
and four new nullable/defaulted columns are added: `record_type` (defaults to `comment` for every
existing row), `source_record_id` (nullable FK to `source_records`, `ON DELETE SET NULL`),
`engagement` (JSONB, backfilled from `like_count`), and `occurred_at` (backfilled from
`published_at`). `app/services/insights/evidence.py` already only ever imported the model class,
never `YouTubeComment` directly -- the rename alone makes "insight services consume a generic
evidence interface" true with no behavior change to insight generation.

### Checkpoints and idempotency

Two independent checkpoint mechanisms now exist, intentionally:

- `AnalysisJob.last_checkpoint` -- this job's own progress bookkeeping (unchanged from Sprint 11),
  still updated every collection page/analysis batch for the progress API.
- `CollectionCheckpoint` (dataset + connector scoped) -- the actual resume state. A fresh
  `AnalysisJobRunner` instance (e.g. after a worker restart) resolves the *dataset's* checkpoint,
  not the job's, so collection resumes from the real last-known cursor regardless of which job
  instance is driving it. Proven with a real controlled-interruption test
  (`test_shutdown_mid_collection_then_fresh_runner_resumes_from_dataset_checkpoint`): a runner is
  stopped mid-page, a brand-new runner instance is constructed, and it resumes from the exact
  `next_page_token` the first instance last saved -- never re-fetching page 1.

Every collection page is upserted through `SourceRecordRepository.bulk_upsert`, unique on
`(dataset_id, source_key)` -- collecting the same video twice (two separate jobs, or a retried
job) never creates duplicate `SourceRecord` rows; the second pass updates the existing row in
place. Proven under real concurrent Postgres writers in the integration suite (8 threads racing
to upsert the same `source_key` produce exactly one row).

### Capability discovery API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/sources/capabilities` | Every `SourceType` enum value's capabilities -- `available`, supported dataset/record types, input modes, checkpoint/reply/rating/engagement support, auth requirement, configured limits, and a sanitized `unavailable_reason` for anything not implemented. |
| GET | `/api/v1/sources/capabilities/{source_type}` | Same, for one source type. |
| GET | `/api/v1/sources/datasets` | The caller's own datasets, paginated. |
| GET | `/api/v1/sources/datasets/{id}` | One owned dataset; 404 for unknown or another user's. |

YouTube reports `available=true` only when `YOUTUBE_API_KEY` is configured (`unavailable_reason`
otherwise: `missing_api_key`). Every other `SourceType` value always reports `available=false`,
`unavailable_reason="not_implemented"` -- an enum value existing is never mistaken for a usable
connector. All four routes require authentication.

### Adding a new connector

1. Implement `SourceConnector` (`app/connectors/base.py`) for the new source -- `validate_source`,
   `describe_source`, `get_capabilities`, `collect_page`, and `classify_error`.
2. Register it in a `build_*_registry()`-style factory (see `app/connectors/__init__.py`), keyed
   by a new or existing `SourceType` enum value.
3. Define its `ConnectorCapabilities` -- accurate `dataset_types`/`record_types`/
   `authentication_requirement`, and `available=False` with a real `unavailable_reason` until it's
   genuinely usable.
4. Have `collect_page` emit `NormalizedSourceRecord`s with a deterministic `source_key`; the
   generic ingestion layer handles persistence, content hashing, and checkpointing.
5. Add connector-specific unit tests (mirroring `tests/unit/connectors/test_youtube_connector.py`)
   and, if the new source needs its own cache/credential table, integration tests for it.
6. The generic pipeline (`AnalysisJobRunner`, `SourceIngestionService`, evidence, insights)
   requires **no changes** -- this is enforced by `tests/unit/test_architecture_boundaries.py`.

`app/connectors/file_import.py` is a completed, worked example of all six steps for a source with
its own multi-step upload/configure workflow ahead of collection -- see [File import
connector](#file-import-connector) below for what it does and why, and note it required zero
changes to `AnalysisJobRunner` or any generic pipeline module, exactly as step 6 promises.

### Migration and backfill policy

Migration `f2f9429bdd68` creates `source_connections`/`source_datasets`/`source_records`/
`collection_checkpoints`, adds `analysis_jobs.source_dataset_id` (nullable, `ON DELETE SET NULL`),
and adds the four generic columns to `analysis_comment_evidence` described above. Backfill is
**bounded and dataset-level only**: one `SourceDataset` is created per distinct
`(user_id, source_external_id)` pair among existing YouTube jobs (reusing the real video title
from `youtube_videos` when available), and existing jobs are linked to it. **Historical
`YouTubeComment` rows are deliberately not backfilled into `SourceRecord`** -- doing so would
duplicate every comment ever collected for no immediate benefit. Instead, `SourceRecord` rows are
populated lazily: the first time an existing dataset is collected again through a post-Sprint-15
job, its `SourceRecord`s are populated from that run. Old jobs remain fully readable (status,
progress, result, evidence) whether or not their dataset has been "recollected" yet.

### Compatibility guarantees

- The `POST /api/v1/analysis/jobs` request body is unchanged (`source_type`, `source`,
  `comment_limit`, `collection_mode`) -- `source_dataset_id` is resolved server-side, never
  client-supplied.
- Every existing YouTube endpoint (`/api/v1/youtube/*`), job endpoint, and insight endpoint keeps
  its exact request/response shape; no field was removed or repurposed.
- `AnalysisReport`/insight JSON schemas and prompt/cache versions are unchanged.
- Pre-Sprint-15 `AnalysisJob` rows with `source_dataset_id IS NULL` remain valid and fully
  functional -- dataset resolution is best-effort/optional everywhere it's read.

### Known limitations

- YouTube and file import (see [File import connector](#file-import-connector) below) are the
  only real connectors; every other `SourceType` value is reserved but reports `available=false`.
  Next planned: GitHub issues and app store/Google Play review connectors.
- `SourceConnection` has no credential vault behind it yet -- a future authenticated connector
  (e.g. a private GitHub repo) reads its credential from application settings, not from a
  per-user encrypted store.
- Historical (pre-Sprint-15) comments are not backfilled into `SourceRecord`; a dataset's
  `SourceRecord`s and its evidence's `source_record_id` links populate only once that dataset is
  collected again through a post-Sprint-15 job.
- Concurrency is still one job per worker process (see [Concurrency](#concurrency) above) --
  collection speed for a large dataset is unchanged by this sprint.

## File import connector

Sprint 16's first real non-YouTube connector: users upload a CSV, XLSX, or JSON file of existing
feedback (reviews, tickets, survey responses) and it flows through the exact same generic
pipeline -- `SourceDataset`/`SourceRecord`/`CollectionCheckpoint`, the same worker, the same Text
Intelligence and Content Intelligence layers -- as YouTube. No generic module changed to support
this; only `app/connectors/file_import.py` and the new `app/imports/` package were added, and both
are registered through the same `ConnectorRegistry` from [Connector
architecture](#connector-architecture).

### Supported formats

| Format | Extension | Notes |
|---|---|---|
| CSV | `.csv` | UTF-8 / UTF-8-sig (BOM), delimiter auto-detected from `,` `;` tab `|` |
| Excel | `.xlsx` only | Read-only, formulas never evaluated (cached value or null), macros/external links/encrypted workbooks rejected |
| JSON | `.json` | Top-level array of objects, or an array at a configured dot-path (e.g. `data.reviews`) |

`.xls`, `.xlsm`, NDJSON, and any other format are rejected outright -- NDJSON was considered and
deliberately excluded because a genuinely streaming implementation was out of scope for this
sprint (see Known limitations). Format is never trusted from the filename or client-declared MIME
type alone: the upload is validated against its actual magic bytes / archive structure before
anything is parsed.

### Two-phase workflow

```
POST /api/v1/sources/imports                       (upload + bounded profile)
POST /api/v1/sources/imports/{id}/configure         (dataset title/type + column mapping)
POST /api/v1/sources/imports/{id}/preview           (optional: preview a mapping before saving it)
POST /api/v1/sources/imports/{id}/start             (idempotent -- creates the AnalysisJob)
GET  /api/v1/sources/imports                        (list the caller's imports)
GET  /api/v1/sources/imports/{id}                   (full detail incl. profile + mapping)
GET  /api/v1/sources/imports/{id}/invalid-rows       (bounded sample + true total count)
POST /api/v1/sources/imports/{id}/cancel
DELETE /api/v1/sources/imports/{id}
```

**Phase A** (`POST /imports`) streams the upload straight to storage while hashing and bounding
its size, validates its format, and profiles a bounded sample (`FILE_IMPORT_PROFILE_ROWS`, default
200 rows) -- column names, inferred types (`string`/`integer`/`float`/`boolean`/`datetime`/`null`/
`mixed`), null percentages, a few sanitized sample values, and a suggested mapping guessed from
column names. It never parses the whole file. The response's `profile_complete` flag tells you
whether the sample covered every row or was truncated.

**Phase B** (`configure` then `start`) is where the caller supplies the actual column mapping and
dataset metadata, then triggers collection. `start` is idempotent: calling it again for an import
that already has a linked `AnalysisJob` returns that same job rather than creating a second one --
proven under real concurrent requests, not just sequential retries (see Checkpoints below).

### Column mapping

```json
{
  "dataset_title": "Q1 support tickets",
  "dataset_type": "custom_feedback",
  "mapping": {
    "text_column": "body",
    "external_id_column": "ticket_id",
    "occurred_at_column": "created_at",
    "rating_column": "csat_score",
    "author_reference_column": "customer_email",
    "record_type_column": "category",
    "default_record_type": "ticket",
    "metadata_columns": ["channel", "priority"],
    "empty_text_policy": "skip"
  },
  "parser_options": { "delimiter": ",", "encoding": "utf-8", "header_row": 1 }
}
```

Only `text_column` is required. Every other field is optional and independently validated: a
mapped column must actually exist in the profiled columns, no column may be mapped to two
incompatible roles at once, `metadata_columns` is capped, and `default_record_type` must be a real
`RecordType`. Mapping is pure configuration -- column names and enum values only, never a Python
expression, template, or `eval`.

### Deterministic source keys

A mapped `external_id_column` value becomes the record's identity directly. Without one, the
connector falls back to a stable hash of `(file_sha256, sheet/path, row_location, identity
fields)` -- deterministic across retries and resumes for the *same upload*, so a retried or
resumed collection never creates duplicate `SourceRecord`s. Re-uploading the same file content as
a brand-new import is a new dataset by design (each `FileImport` is its own bounded analyzable
unit), not merged with a previous one.

### Storage

Uploaded files never touch PostgreSQL and are never served as static content. `FILE_IMPORT_STORAGE_PATH`
(default `var/file_imports`, outside `app/`, gitignored) is a local directory the
`ImportFileStorage` abstraction owns exclusively:

- every file is written under a server-generated 32-character key, never the client's filename;
- writes are atomic (`.part-<uuid>` sibling file, renamed into place only once fully written and
  hashed) -- an interrupted upload never leaves a corrupt file visible under its final name;
- every key is validated against its exact expected shape before ever being joined onto the root,
  and every read/delete additionally re-checks the resolved path is still under the root and isn't
  a symlink;
- swapping in an object-storage backend later means implementing one new class against
  `ImportFileStorage`, not touching `app/imports/service.py` or the connector.

### Security

- **Path traversal / symlinks**: covered above -- keys are never client input, and every access is
  re-validated against the root regardless.
- **ZIP bombs**: before opening a workbook with openpyxl, its ZIP archive is inspected directly --
  total uncompressed size, per-entry compression ratio, and shared-string count are all bounded
  (`FILE_IMPORT_XLSX_MAX_UNCOMPRESSED_BYTES`, `FILE_IMPORT_XLSX_MAX_COMPRESSION_RATIO`,
  `FILE_IMPORT_XLSX_MAX_SHARED_STRINGS`) and an oversized/implausible archive is rejected before
  openpyxl ever decompresses it.
- **Macros / external links**: an `.xlsx` containing `xl/vbaProject.bin` or `xl/externalLinks/*`
  is rejected outright, even if it otherwise looks like a valid workbook.
- **Formula execution**: openpyxl is opened `data_only=True`, `keep_links=False` -- it never
  evaluates a formula; a formula cell's cached value is used if present, otherwise the cell reads
  as empty. There is no code path that executes spreadsheet formulas.
- **MIME/extension spoofing**: format is confirmed from magic bytes (ZIP signature for `.xlsx`,
  `[`/`{` for JSON) independent of the filename extension and declared `Content-Type`; a mismatch
  is rejected.
- **CSV/formula injection in output**: values are never re-emitted as a spreadsheet. The one place
  a value could plausibly be pasted into Excel by a human (the mapping `/preview` endpoint) still
  neutralizes any leading `=`/`+`/`-`/`@` with a leading `'`, defensively, even though the response
  itself is JSON.
- **Resource exhaustion**: rows, columns, cell length, and JSON nesting depth are all bounded
  (`FILE_IMPORT_MAX_ROWS`, `FILE_IMPORT_MAX_COLUMNS`, `FILE_IMPORT_MAX_CELL_CHARACTERS`,
  `FILE_IMPORT_MAX_JSON_DEPTH`) and enforced during parsing, not just profiling.
- Uploaded file **content** is never logged; audit/log entries reference only the import id,
  format, size, and row counts.

### Invalid rows and coverage disclosure

A row that fails mapping (most commonly: the mapped text column is blank) is skipped, not fatal to
the import. Up to `FILE_IMPORT_MAX_PERSISTED_ROW_ERRORS` (default 1000) individual row errors are
persisted per import for diagnostics via `GET /imports/{id}/invalid-rows`; `FileImport.invalid_row_count`
is the **true** total and keeps counting past that cap, so a pathological file's invalid-row count
is never silently truncated even though the persisted sample is bounded. A `FileImport` always
discloses `row_count` (total rows encountered), `valid_row_count`, `invalid_row_count`, and
`duplicate_row_count` (rows whose computed source key collided with an earlier row in the same
collection batch -- a deliberately batch-scoped check, the same precedent as Text Intelligence's
duplicate-signature grouping).

### Checkpoints and idempotency

Collection is driven through the same `CollectionCheckpoint` mechanism as YouTube: the connector
caches its row iterator in-process across pages within one job run, and on a genuine cross-process
resume (worker restart, crash) a fresh connector instance re-opens the file and skips forward to
the checkpoint's row count exactly once, then continues -- not an O(n) re-skip per page.

Starting the same import twice concurrently is safe by construction, not just by convention: the
`ready -> importing` transition is an atomic `UPDATE ... WHERE status = 'ready' ... RETURNING`
single statement, not a held row lock. A held `SELECT ... FOR UPDATE` was tried first and found
insufficient -- dataset/job creation each commit their own unit of work internally, and any commit
ends the transaction and releases the lock, leaving a window for a second caller to slip in before
the job is actually linked. The atomic compare-and-swap UPDATE has no such window: a losing
concurrent caller either observes the winner's already-linked job, or gets a 409 asking it to retry
-- proven under real concurrent PostgreSQL requests in the integration suite.

### Cleanup

Uploaded files are reclaimed -- never the `FileImport` row itself, so history remains queryable --
in two cases: an import that was never started before `FILE_IMPORT_RETENTION_HOURS` (default 24)
passed, or a completed/failed/cancelled import whose file has sat past that same retention window.
An import still `importing` is never touched regardless of age. Run it periodically (no scheduler
dependency is bundled):

```powershell
python -m app.cli.cleanup_imports
python -m app.cli.cleanup_imports --batch-limit 200
```

### Settings

```
FILE_IMPORT_ENABLED=true
FILE_IMPORT_STORAGE_BACKEND=local
FILE_IMPORT_STORAGE_PATH=var/file_imports
FILE_IMPORT_MAX_FILE_SIZE_MB=25
FILE_IMPORT_MAX_ROWS=100000
FILE_IMPORT_MAX_COLUMNS=100
FILE_IMPORT_MAX_CELL_CHARACTERS=10000
FILE_IMPORT_MAX_JSON_DEPTH=5
FILE_IMPORT_PROFILE_ROWS=200
FILE_IMPORT_BATCH_SIZE=500
FILE_IMPORT_RETENTION_HOURS=24
FILE_IMPORT_MAX_ACTIVE_IMPORTS_PER_USER=5
FILE_IMPORT_MAX_STORED_BYTES_PER_USER=262144000
FILE_IMPORT_MAX_BYTES_PER_USER_PER_DAY=524288000
FILE_IMPORT_UPLOAD_RATE_LIMIT_REQUESTS=10
FILE_IMPORT_UPLOAD_RATE_LIMIT_WINDOW_SECONDS=3600
```

Every collection-time limit (rows per job) is additionally capped by the existing, unchanged
`ANALYSIS_MAX_COMMENT_LIMIT` / `USAGE_MAX_COMMENT_LIMIT_PER_JOB` -- a file-import job can never
request more analysis than a YouTube job could. "Maximum concurrent import jobs" is not a separate
setting: it's the existing `USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER`, inherited for free since a
started import *is* an `AnalysisJob`.

### Known limitations

- JSON is parsed as one bounded in-memory document, not streamed incrementally -- justified by the
  already-enforced `FILE_IMPORT_MAX_FILE_SIZE_MB` upload cap (25 MB by default), the same bound
  CSV/XLSX row batching already relies on. CSV and XLSX are read row-by-row.
- NDJSON is not supported -- a genuinely bounded, streaming implementation was out of scope this
  sprint; documented here rather than shipped half-done.
- Duplicate-row detection is scoped to one collection batch, not the whole file -- a duplicate
  split across two batch boundaries is still upserted correctly (idempotent on `source_key`) but
  isn't counted twice in `duplicate_row_count`.

## GitHub repository connector

Sprint 18 adds GitHub as a third source connector -- repository issues, pull requests, comments,
reviews, and releases flow through the exact same generic pipeline (`SourceDataset`/
`SourceRecord`/`CollectionCheckpoint`, the same worker, the same Text Intelligence / Content
Intelligence / Structured Signal layers) as YouTube and file imports. No generic module changed;
only `app/connectors/github.py`, `app/clients/github.py`, the new `app/core/credential_vault.py`
abstraction, and the `app/services/github/` package were added.

This is also the first connector that needs a per-user secret (a GitHub personal access token),
which is why this sprint introduces the credential vault -- see [Credential
vault](#credential-vault) below.

### Supported data

| GitHub entity | Normalized `record_type` | Notes |
|---|---|---|
| Repository | n/a (dataset metadata) | description, stars, language, default branch, `private` flag |
| Issue | `issue` | title+body, labels, state, comments/reactions counts, author login |
| Pull request | `pull_request` | same shape as issue, plus `merged_at`; detected from the `issues` API response, never fetched separately |
| Issue comment / PR conversation comment | `issue_comment` | linked to its parent issue or PR via `parent_source_key` |
| Review comment (a comment on a diff line) | `review_comment` | linked to its parent PR |
| Pull request review | `review` | linked to its parent PR |
| Release | `release` | name/tag + release notes as the analyzable text |

Only what is listed above is ever collected. Source code, diffs, patches, commit contents, binary
release assets, and email addresses are never fetched or stored -- every author reference is a
public GitHub login (`user.login`), never an email or profile field.

### Public vs. private repositories

Public repositories work with **no token** (subject to GitHub's unauthenticated rate limit).
Private repositories, and higher rate limits on public ones, require a connection with a personal
access token (classic `repo` scope, or a fine-grained token scoped to the specific repositories
you want to analyze). GitHub is asked case-insensitively, but a repository's dataset identity
(`SourceDataset.external_id`) is always the lowercased `owner/repo` form, so `Owner/Repo` and
`owner/repo` always resolve to the same dataset for the same user.

### Credential vault

`app/core/credential_vault.py` is a small, source-agnostic abstraction -- nothing in it is
GitHub-specific, so a future connector needing its own secret reuses it directly:

- **Authenticated encryption**: AES-256-GCM (`cryptography`'s `AESGCM`), keyed from a SHA-256
  digest of `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY` so any sufficiently long passphrase-shaped
  secret works, the same convention as every other secret in this project. A fresh random nonce is
  generated per encryption, so encrypting the same token twice never produces the same ciphertext.
- **At rest**: `connector_credentials.nonce` / `.ciphertext` (`BYTEA`) -- there is no plaintext
  column, and decryption with the wrong key raises `CredentialDecryptionError` rather than
  returning corrupted data.
- **Never exposed**: no API response, log line, or `repr()` ever includes a token, a nonce, or
  ciphertext -- `GitHubConnectionResponse` reports only a boolean `has_credential`.
- **User-owned, connection-scoped**: exactly one credential per `SourceConnection`
  (`source_connection_id` is unique), cascading only when that connection itself is deleted.
  Deleting a credential or its connection **never** deletes `SourceDataset`/`SourceRecord`/
  `AnalysisJob` history -- those foreign keys are `ON DELETE SET NULL`, never `CASCADE` (see
  [Compatibility guarantees](#compatibility-guarantees) for the same pattern elsewhere).
- **Scope validation is best-effort**: a classic PAT's scopes are read from GitHub's own
  `X-OAuth-Scopes` response header (fine-grained tokens don't expose this and simply report no
  scopes); a token that cannot currently be validated (network blip, GitHub outage) is still saved
  -- validation failure never blocks storing the credential the user just supplied.

### Connections and analyses API

```
POST   /api/v1/sources/github/connections               create a connection, optionally with a token
GET    /api/v1/sources/github/connections                list the caller's connections
GET    /api/v1/sources/github/connections/{id}           get one (404 if unowned/unknown)
POST   /api/v1/sources/github/connections/{id}/test      check reachability + credential validity
PUT    /api/v1/sources/github/connections/{id}/credential replace the stored token
DELETE /api/v1/sources/github/connections/{id}           delete the connection (and its credential)

POST   /api/v1/sources/github/repositories/validate      parse + fetch public metadata for a reference
POST   /api/v1/sources/github/analyses                   resolve/create the dataset and queue an AnalysisJob
```

Example: connect a private repository and start an analysis (placeholders only -- never paste a
real token into a shell history or a committed file):

```bash
curl -X POST http://localhost:8000/api/v1/sources/github/connections \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"display_name": "My GitHub", "token": "<your PAT>"}'
# -> {"id": "...", "has_credential": true, ...}   -- the token itself is never echoed back

curl -X POST http://localhost:8000/api/v1/sources/github/analyses \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"repository": "owner/private-repo", "connection_id": "<connection id>", "analysis_limit": 500}'
# -> {"job_id": "...", "job_status": "queued", "dataset_id": "...", ...}
```

`POST /analyses` never accepts a `user_id` -- ownership always comes from the authenticated
principal, exactly like every other job-creation endpoint. Analyzing the same repository again
(with or without a connection) resolves the same `SourceDataset`; two different users analyzing
the same public repository each get their own, fully isolated dataset -- private repository
metadata collected under one user's credential is never visible to another user.

### Collection options

`POST /analyses` accepts, all optional:

```json
{
  "repository": "owner/repo",
  "connection_id": null,
  "include_issues": true,
  "include_pull_requests": true,
  "include_comments": true,
  "include_reviews": true,
  "include_releases": true,
  "state": "all",
  "since": null,
  "until": null,
  "analysis_limit": null
}
```

`state` is one of `open` / `closed` / `all`.

`since`/`until` are **both** bounds on a record's own occurrence timestamp -- when the issue, pull
request, comment or review was created, or when a release was published -- and both ends are
inclusive. A naive datetime is read as UTC. This is one concept with two ends, which it was not
before Phase 1: `since` used to be GitHub's *updated-after* filter while `until` was compared
against creation time, so an issue opened years ago but commented on yesterday was kept by one end
of the range and rejected by the other. GitHub's own `since` parameter is still sent on the
endpoints that support it, but purely as a server-side narrowing hint -- `updated_at >= created_at`
always holds, so it can never exclude a record the window would have kept -- and the exact window
is applied locally.

`analysis_limit` is optional. Omitted, it means "collect what this repository has": the job runs in
`all_available` collection mode and paginates until GitHub is exhausted, cancellation, or quota
stops it. There is deliberately **no** per-job record ceiling -- the former
`GITHUB_MAX_RECORDS_PER_JOB=2000` silently truncated every real repository while still reporting the
run complete, and conflated source *retrieval* with the separate question of how much evidence an
LLM should later be shown. Supplied, it is honoured exactly and remains bounded by the same
`ANALYSIS_MAX_COMMENT_LIMIT` / `USAGE_MAX_COMMENT_LIMIT_PER_JOB` every other source respects.

Every entity is read from the endpoint that is canonical for it: issues from `/issues`, pull
requests from `/pulls`, reviews by re-walking `/pulls`. GitHub's `/issues` listing does return pull
requests too, but its PR representation is genuinely thinner -- no draft flag, no base/head refs, no
requested reviewers -- so PR items are skipped there and collected from `/pulls` instead. That costs
one extra *listing* request per 100 pull requests, never a per-item detail call. As a result
"reviews without issues" is a first-class configuration rather than the silent no-op it once was.

### Evidence metadata (grounding)

Collection is only half the path. The job runner used to drop
`SourceRecord.record_metadata` entirely when writing an `AnalysisRecordEvidence` row, so every
structural fact -- repository, entity number, labels, file path, canonical URL -- was lost at exactly
the layer RAG, the Assistant, insights and reports read from. `AnalysisRecordEvidence.source_metadata`
now carries a bounded projection of it (`app/services/analysis_job/evidence_metadata.py`), which is
deliberately a **projection and not a copy**:

- **Strict allow-list.** Only known structural fields survive, so a connector cannot widen the
  evidence schema by writing a new key. A second, redundant guard rejects credential-shaped key
  names, so a future addition to the allow-list cannot quietly admit one.
- **Hard size bound** (`EVIDENCE_SOURCE_METADATA_MAX_BYTES`, 2 KB -- far below a source record's
  8 KB, because evidence rows are batched in memory, embedded, and serialized into API, report and
  prompt payloads). Fields are dropped **whole**, in a fixed priority order, so the stored value is
  always valid JSON rather than a truncated string that happens to parse. Long strings, `diff_hunk`
  and arrays are individually bounded first, so one pathological field cannot push out the identity
  fields.
- **The URL is never dropped.** It is the highest-priority field and the one thing a citation
  cannot be rebuilt without.

What survives per entity: issues keep number/state/`state_reason`/labels/assignees/milestone/
`author_association`/timestamps; pull requests add draft, `merged_at`, base and head refs and
requested reviewers; comments keep their parent's number and **type**; reviews keep state and
`commit_id`; review comments keep the full code locator (`path`, `line`, `original_line`,
`start_line`, `side`, `start_side`, `commit_id`, `original_commit_id`, bounded `diff_hunk`);
releases keep tag, `target_commitish`, draft/prerelease and publication time.

Deliberately **not** collected: a pull request's additions/deletions/changed_files and mergeable
state. GitHub only populates those on the per-PR detail endpoint -- one request per pull request, an
N+1 pattern whose cost scales with repository size -- and none of them are needed to ground evidence
in a specific pull request. They belong to a later PR-intelligence phase that can justify the quota.

### Citations and deep links

`app/services/assistant/grounding.py` turns persisted evidence metadata into one **source-agnostic**
citation contract (`source_type`, `source_key`, `label`, `url`, `path`, `line`) used by the
Assistant, insight evidence references and report sections alike. Every field is optional, so a
YouTube comment and a pre-Phase-2 row remain valid citations that simply carry less.

Nothing about a citation is authored by the model. It chooses *which* retrieved record to cite; the
label, URL and locator all come from persisted metadata. The URL is deliberately kept out of the
prompt context entirely -- a model that can see URLs writes them into prose, where an invented one
is indistinguishable from a real one. Links are re-validated against a trusted-host allow-list at
emission (`app/utils/source_links.py`) and again in the client before rendering an anchor: storage
is not a trust boundary, and a link is the one field where being wrong is actively harmful.

### Rate limits and checkpoints

- Rate-limit headers (`X-RateLimit-Limit/Remaining/Used/Reset`, `Retry-After`) are parsed from
  **every** response, success included, and returned to callers as a `GitHubRateLimit` value object
  alongside the data -- no caller ever touches an `httpx.Response`. Before Phase 1 these were only
  read after a request had already been rejected, so collection could neither see exhaustion coming
  nor know when it would clear.
- **Primary quota exhaustion** (403 + `X-RateLimit-Remaining: 0`) and a **secondary/abuse limit**
  (403/429 + `Retry-After`) both raise a `SourceQuotaExhaustedError` subclass carrying GitHub's own
  reset instant. The job runner reschedules the job for that instant and the wait does **not**
  consume one of `ANALYSIS_JOB_MAX_ATTEMPTS` -- waiting is not failing. This replaces the previous
  behavior, where a rate limit went onto the ordinary retry ladder (5s, 10s, 20s &hellip; capped at
  `ANALYSIS_RETRY_MAX_DELAY_SECONDS`), burned all three attempts *inside* the same hour-long reset
  window it was waiting for, and failed the job permanently -- discarding a partially collected
  repository. Waiting is bounded per-wait and in total (`ANALYSIS_QUOTA_WAIT_MAX_SINGLE_SECONDS`,
  `ANALYSIS_QUOTA_WAIT_MAX_TOTAL_SECONDS`) so a permanently throttled source can never park a job
  forever, and floored (`ANALYSIS_QUOTA_WAIT_MIN_SECONDS`) so an already-elapsed reset cannot
  produce a hot loop. `SourceQuotaExhaustedError` is generic and subclasses `SourceRateLimitError`,
  so sources that publish no reset time (YouTube) keep the ordinary ladder unchanged.
- A secondary limit whose `Retry-After` is at or below `GITHUB_INLINE_RETRY_MAX_WAIT_SECONDS` is
  simply slept off inside the client; anything longer is escalated so a worker is never parked on a
  long sleep. Transient failures (connection errors, timeouts, 5xx) are retried up to
  `GITHUB_MAX_RETRIES` times with a short bounded exponential delay -- safe because every request
  this connector makes is a GET.
- Collection is broken into phases (`issues` &rarr; `issue_comments` &rarr; `review_comments` &rarr;
  `reviews` &rarr; `releases`, skipping any phase whose `include_*` flag is off) tracked inside
  `CollectionCheckpoint.cursor`: a **version**, the current phase, the page number, an **offset into
  that page**, and a `/pulls` page cursor for the `reviews` phase. The cursor is constant-size
  regardless of repository size -- it no longer accumulates discovered pull-request numbers, which
  previously capped review collection at 1000 PRs.
- **Pagination geometry is fixed.** `per_page` is always `GITHUB_COLLECTION_PAGE_SIZE` (100,
  GitHub's documented maximum) and never varies within a pagination sequence. The collection budget
  decides only whether to accept more records; when it runs out mid-page the cursor's `item_offset`
  stays pointing at the first unconsumed item, so the next call re-requests the same page and
  continues exactly there. Previously `per_page` was `min(remaining_budget, PAGE_SIZE)`, which meant
  a resume with a smaller budget re-addressed `page=N` at a narrower width and **silently skipped
  every record in between**. End-of-listing comes from GitHub's own `Link: rel="next"` header, never
  inferred from page length -- inference is wrong exactly at the boundary that matters (a final page
  that happens to be exactly full).
- Upstream rate-limit/auth headers are never included in any exception message, log line, or API
  response -- only a sanitized error code (e.g. `github_rate_limited`) ever surfaces.

### Normalization and evidence

Every collected item maps to a `NormalizedSourceRecord` exactly like every other source: bounded
`original_text` (title+body, or just body for comments/reviews), a deterministic `source_key`
(`issue:<number>`, `pr:<number>`, `issue_comment:<id>`, `review_comment:<id>`, `review:<id>`,
`release:<id>`) unique per dataset, `parent_source_key`/`thread_source_key` linking comments and
reviews back to their issue/PR, `occurred_at` from the item's creation timestamp, and `engagement`
(comment/reaction counts). Every record also carries `record_metadata["url"]` -- GitHub's own
`html_url`, taken only from the API response and never assembled by string-building from a
user-supplied reference -- so any ingested item can be linked back to GitHub.

Comment parentage is recorded truthfully rather than assumed. Issue and review comments are
collected repository-wide (one request per 100 comments instead of one per issue), so a comment can
arrive whose parent was never ingested -- because the user disabled issues and pull requests, or
because the parent falls outside the date window. Each comment therefore carries its parent's real
number, a resolvable deep link, and an explicit `parent_content_included` flag; no parent content is
ever invented. Pull-request *conversation* comments are served by GitHub from `/issues/comments`
with an `issue_url` of `/issues/{n}` even when `{n}` is a pull request, so the comment's own
`html_url` is used to key them to `pr:{n}` rather than a non-existent `issue:{n}`.

Labels, state, and closed/merged timestamps are preserved as bounded
`record_metadata` **hints** -- Text Intelligence and Structured Signal Intelligence never read
them to decide a signal's type; a "good-first-issue"-labeled issue whose text reads as a complaint
still becomes a `problem` signal, exactly as if it carried no label at all (see [Measured vs.
inferred vs. recommended](#measured-vs-inferred-vs-recommended)).

### Security

- **SSRF**: the outbound HTTP client only ever calls `GITHUB_API_BASE_URL` -- a user-supplied
  repository reference is *parsed* for its `owner/repo`, never dereferenced as a URL to fetch, so a
  malicious or lookalike host in the input can never redirect an outbound request anywhere.
  `app/utils/github.py` additionally rejects any URL whose host isn't exactly `github.com` /
  `www.github.com` before that parsing even happens.
- **Token leakage**: see [Credential vault](#credential-vault) above -- encrypted at rest, never
  echoed in a response, never logged.
- **Credential cross-user access**: every connection/credential lookup is scoped to
  `(id, owner_user_id)`; an unowned or unknown id is a 404, indistinguishable from each other.
- **Prompt injection**: issue/comment/review text is untrusted evidence, never instructions --
  Structured Signal Intelligence's AI enrichment (when enabled) already treats every source's text
  this way (bounded excerpts, metadata allow-lists, no free-form text ever reinterpreted as a
  directive); GitHub text receives no special trust.
- **Oversized bodies**: `original_text`/`record_metadata` are bounded by the same
  `SOURCE_RECORD_TEXT_MAX_LENGTH` / `SOURCE_METADATA_MAX_BYTES` every source already respects.
- **Log injection**: no raw GitHub response body or header is ever interpolated into a log message
  or exception text.
- **Private repository disclosure**: a private repository's dataset/records are only ever
  resolved under the analyzing user's own `user_id` -- there is no cross-user dataset sharing for
  any source, GitHub included.

### Settings

```
GITHUB_CONNECTOR_ENABLED=false
GITHUB_API_BASE_URL=https://api.github.com
GITHUB_API_VERSION=2022-11-28
GITHUB_REQUEST_TIMEOUT_SECONDS=15
GITHUB_MAX_RETRIES=2
GITHUB_RETRY_BASE_DELAY_SECONDS=0.5
GITHUB_COLLECTION_PAGE_SIZE=100
GITHUB_REVIEW_PRS_PER_PAGE=10
GITHUB_INLINE_RETRY_MAX_WAIT_SECONDS=30
GITHUB_CONDITIONAL_REQUESTS_ENABLED=true
CONNECTOR_CREDENTIAL_ENCRYPTION_KEY=
```

`GITHUB_CONNECTOR_ENABLED` gates everything: `GET /sources/capabilities` reports `github` with
`available=false, unavailable_reason="disabled"` until it's turned on, and every
`/sources/github/*` endpoint refuses with a clear 422 rather than silently no-op-ing.
`CONNECTOR_CREDENTIAL_ENCRYPTION_KEY` is required in production whenever the connector is enabled
(auto-generated outside production, with the same "everything encrypted under it becomes
undecryptable on restart" caveat as every other auto-generated secret in this project -- see
[Secrets](#secrets)).

### Known limitations

- Pull-request reviews are collected per pull request (`GET /pulls/{n}/reviews`), not from a
  repo-wide endpoint (GitHub's REST API doesn't expose one) -- bounded to
  `GITHUB_REVIEW_PRS_PER_PAGE` PRs per collection step, discovered from the `issues` phase's own
  pagination, capped at 1000 tracked PR numbers per job.
- `until` filtering happens after collection (GitHub's list endpoints only support a `since` lower
  bound), so a page whose oldest items are already past `until` still costs one API call before
  being filtered out.
- No GitHub App / installation flow, no webhooks, and no organization-level connectors -- this
  sprint is personal-access-token-based, single-repository analysis only, by design.
- No automatic issue creation, action-plan generation, or write access of any kind -- this
  connector only ever reads.

## Content Intelligence

Turns a **completed** analysis job's persisted evidence into a structured report: topics,
complaints, suggestions, questions, praise, criticism, audience requests, repeated themes,
recommendations, and an executive overview. Every item traces back to real comments via
`evidence_id`s — nothing is invented.

### Architecture

```
Completed analysis job
  → persisted AnalysisCommentEvidence rows (written during the job, see below)
  → local deterministic extraction (keywords, embeddings, clustering, ranking, templates)
  → structured local report
  → [optional] bounded evidence package sent to Gemini or OpenAI for refinement
  → evidence-ID validation (unknown ids are rejected, never accepted)
  → versioned, cached AnalysisJobInsight row
```

The **local layer is mandatory** and always runs first, even in `ai`/`hybrid` mode. An AI
provider can only refine labels/descriptions/overview/recommendations on top of it — it can
never replace it, and every AI-sourced item still carries `evidence_ids`/linked local ids
validated against the same bounded package the provider was given.

### Persistent comment evidence

`AnalysisCommentEvidence` (table `analysis_comment_evidence`) is written by `AnalysisJobRunner`
in the same per-batch step that already persists Text Intelligence + sentiment results (Sprint
11), so insight generation never needs a still-running worker, and never re-collects from
YouTube, never reruns the transformer models, and never reruns Text Intelligence.

**Text storage decision**: each row stores a **bounded 500-character excerpt** of both the
original and processed text — not a full duplicate, and not a hard foreign key to
`YouTubeComment`. This keeps the model genuinely source-agnostic (`source_type`/`source_key`/
`source_external_id`, no YouTube-specific required field) while staying practical: keyword
extraction, embeddings, and short quoted evidence in reports only need a preview, not every
character of an unbounded comment. The authoritative full text remains available via
`YouTubeComment.text` (joinable by `source_key`) for this source type; evidence itself never
depends on that join to function.

Writes are **idempotent** (upsert on `(job_id, source_key)`), so a retried job attempt never
creates duplicate evidence. Spam/sarcasm/intent/target/emoji/duplicate-group metadata already
computed by Text Intelligence is persisted alongside sentiment — nothing is recomputed.

### Evidence selection

By default, insight generation uses only comments that are processable, analyzed, non-spam, and
part of the "clean" analysis (`included_in_clean_analysis=true` — computed once, at write time,
as `analyzed and not is_spam`). For semantic clustering, only **one representative per
duplicate-signature group** contributes an embedding — so a flood of copy-pasted comments cannot
manufacture an artificially dominant topic — while comment_count/percentage statistics still
reflect every occurrence once a cluster is identified.

### Local extraction

- **Keywords** (`local/keywords.py`): multilingual unigram/bigram/trigram extraction with
  English + Arabic stopword lists, a lightweight Arabic prefix-stripper (و/ف/ب/ل/ك/ال and
  combinations — a heuristic, not true morphological analysis), and noise exclusion (isolated
  numbers, digit-run "random ids", filler reactions like "lol"/"hahaha"). Tracks frequency,
  unique-comment support, and **duplicate-normalized support** separately, so a repeated spam
  comment inflates the first two but not the third.
- **Embeddings** (`local/embeddings.py`): `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (Apache-2.0 licensed per its own model card), lazy-imported and lazy-loaded exactly like the
  sentiment models (keyed registry, CPU default, no download at import time or app startup). A
  `FakeDeterministicEmbeddingProvider` (hash-seeded, token-overlap-sensitive) is used everywhere
  in the default test suite so no model download ever happens in CI/automated tests.
- **Clustering** (`local/clustering.py`): agglomerative clustering, cosine distance, average
  linkage, driven by a `distance_threshold` instead of a fixed cluster count — chosen over
  MiniBatchKMeans (which needs `n_clusters` picked up front) and over adding a BERTopic-sized
  dependency (not justified here). Fully deterministic, no random seed needed. Clusters smaller
  than `INSIGHT_CLUSTER_MIN_SIZE` or beyond `INSIGHT_CLUSTER_MAX_TOPICS` (by size) become
  outliers rather than their own topic.
- **Labels** (`local/labels.py`): bilingual (EN/AR) deterministic labels from target + top
  keywords — e.g. audio/sound/volume → "Audio and sound quality", شرح/توضيح/فهم → "وضوح الشرح".
  Always `label_source="local"`, never described as AI-generated.
- **Complaints vs. generic negativity** (`local/complaints.py`): a negative comment only becomes
  a complaint candidate if it also carries a `complaint` intent, a `criticism` intent with a
  concrete target, negative lexical polarity + a concrete target, or a `question` intent (an
  unresolved malfunction report). A bare "this sucks" with no target and no such intent is
  excluded.
- **Suggestions vs. requests vs. complaints vs. questions** (`local/suggestions.py`,
  `local/requests.py`): candidate signals are read from the intent/target fields Text
  Intelligence already computed (which already covers the Arabic/English suggestion/request
  phrases from the spec, e.g. "ياريت"/"please add") — not re-scanned here. `suggestions`
  includes both `suggestion`- and `request`-intent items; the dedicated `audience_requests`
  capability is narrower (request-intent only).
- **Questions** (`local/questions.py`): paraphrase grouping via embeddings. **Local mode never
  invents an answer** — `answerability` is always `"unknown"` locally; only AI/hybrid mode can
  upgrade it, and only when genuinely supported by the evidence.
- **Praise** (`local/praise.py`): positive sentiment alone isn't enough — a vague "nice" with no
  praise intent and no concrete target is excluded, so strengths stay specific (explanation
  clarity, editing quality, etc.).
- **Criticism** (`local/criticism.py`): a broader "negative evaluation or disagreement" category,
  distinct from (but cross-linked to, by shared target) concrete Complaints.
- **Repeated themes** (`local/themes.py`): a bounded set of concrete pattern detectors (praise +
  complaint on different targets, a strongly repeated request, a target-specific question
  cluster suggesting confusion, a multilingual paraphrase of the same question, an unusually high
  spam ratio) — not an open-ended pattern-mining engine.
- **Recommendations** (`local/recommendations.py`): every recommendation links to a real
  `linked_complaint_ids`/`linked_suggestion_ids` and `evidence_ids` — never generic, ungrounded
  advice. Top complaints are paired with a suggestion sharing the same target when one exists.
- **Overview** (`local/overview.py`): deterministic templated summary — "Among the analyzed
  comments...", "The most frequent complaint in this sample...", "This result is based on a
  partial comment collection..." — never "the entire audience..."/"all viewers...".
- **Ranking** (`ranking.py`): explicit, configurable weighted-factor functions for topics,
  complaints, suggestions/requests, and questions. These are deterministic ranks for sorting, not
  probabilities.

### AI providers (Gemini / OpenAI)

Both are real, official-SDK integrations (`google-genai`, `openai`), lazily constructed (no
network call at import time or app startup), used only when `INSIGHT_AI_ENABLED=true` and a
provider's own mode is requested (`ai`/`hybrid`). Local mode never touches either SDK.

- Model identifiers come only from `INSIGHT_AI_GEMINI_MODEL`/`INSIGHT_AI_OPENAI_MODEL` — blank
  means that provider is unavailable; no default is guessed or hardcoded.
- API keys come only from `GEMINI_API_KEY`/`OPENAI_API_KEY` (`SecretStr` end-to-end — never
  appear in `repr()`/logs/error messages).
- Structured JSON output, Pydantic-validated, with a bounded timeout, bounded retries
  (`INSIGHT_AI_MAX_RETRIES`) for transient failures, and **one** structured-output repair retry
  (`INSIGHT_AI_REPAIR_RETRIES`) when the response fails evidence-ID/schema validation.
- **Provider registry + fallback** (`ai/service.py`): primary → (on an allowed failure reason)
  fallback → (if both fail) local result, unless strict mode is on. A genuine programming error
  from a provider implementation is **never** silently treated as an outage — it propagates.
- **Evidence-ID validation** (`ai/validation.py`): every id the model returns under an
  `*_id`/`*_ids` key is checked against the exact bounded package it was given. An unknown id
  (including one the model was tricked into echoing from inside a comment's own text) triggers
  repair → fallback → local, never a silently accepted invented reference.
- **Prompt safety** (`ai/prompts.py`): comment excerpts are always serialized as plain JSON data
  fields, never concatenated into an instruction string. The system prompt explicitly instructs
  the model to treat them as untrusted data, never reveal its own instructions, never invent
  ids/facts, never infer demographics or profile commenters, and never claim full-audience
  representation from a partial sample.

### Insight modes

| Mode | Behavior |
|---|---|
| `local` | Rules + embeddings only. Always available once the embedding model is cached. No network call. |
| `ai` | Local extraction first, then the primary AI provider refines it; falls back per the policy above. |
| `hybrid` (recommended) | Local extraction first; only ambiguous/high-value clusters (low cohesion, or top-N) are sent to the AI provider. Falls back to the complete local result on any failure. |

Every response reports `mode_requested`, `mode_used`, `provider_requested`, `provider_used`,
`fallback_provider`, `fallback_used`, `fallback_reason`, `model_used`, and `ai_status` — AI mode
is never silently claimed when only local results were actually returned.

### Caching and regeneration

Results are cached per `(job_id, capability, mode_requested, output_language, schema_version,
prompt_version)`. A repeated identical request returns the cached row (`cached: true`).
Bumping `INSIGHT_SCHEMA_VERSION` or `INSIGHT_AI_PROMPT_VERSION` permits regeneration without
deleting history; `force_regenerate: true` bypasses the cache for one request. Concurrent
identical requests racing the cache insert resolve to the same row (verified with real
concurrent threads against PostgreSQL), never duplicate rows.

### Sync vs. worker-backed generation

Insight generation is **synchronous** in this release (a normal request/response, `200` on
success) — not a separate persisted job type. This was measured, not assumed: local generation
over 100–1000 comments completes in low milliseconds once the embedding model is warm (see
performance numbers in the Sprint 12 report), and a single bounded AI provider call
(`INSIGHT_AI_TIMEOUT_SECONDS`, default 60s) is within normal HTTP timeout tolerance. If AI
latency in practice exceeds that comfortably, the next step would be an `insight_generation`
work type on the existing PostgreSQL job/worker architecture rather than a new one.

### API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/analysis/jobs/{job_id}/insights` | Readiness, evidence count, cached results, provider availability. |
| POST | `/api/v1/analysis/jobs/{job_id}/insights/{capability}` | Generate (or return cached) one capability. |
| GET | `/api/v1/analysis/jobs/{job_id}/insights/{capability}` | Retrieve a previously cached result only (404 if none yet). |

Capabilities: `overview`, `topics`, `complaints`, `suggestions`, `questions`, `praise`,
`criticism`, `audience_requests`, `repeated_themes`, `recommendations`, `complete_report`.

HTTP status: `200` cached/synchronous success, `404` unknown job or no cached result yet, `409`
job not completed or evidence incomplete, `422` unsupported mode/capability/language, `503` only
for strict AI mode with no provider available (never a `500` for ordinary provider
unavailability).

### Coverage and honesty

Every response includes a `coverage` block (`requested_comment_limit`, `collected_comments`,
`analyzed_comments`, `clean_comments`, `collection_complete`, `coverage_percentage`,
`evidence_count`) and a `partial_comment_collection` warning when collection didn't reach the
true end of available comments — the same honesty invariant Sprint 9–11 established for the
underlying job/report.

### Known limitations

- Arabic prefix-stripping in keyword extraction is a simple heuristic, not true morphological
  analysis, and can occasionally over-strip a word that begins with a prefix-like sequence.
- `criticism` items don't yet compute `related_suggestion_ids` (only `related_complaint_ids`).
- `repeated_themes` covers a fixed set of concrete pattern types, not open-ended pattern mining.
- AI refinement currently supports overriding the overview summary, per-item label/description
  overrides (by local id), and additional AI-sourced recommendations — not a full re-generation
  of every field of every capability.
- No local/authentication control exists yet — **do not expose this API publicly** without
  adding access control first.

## Structured Signal Intelligence

Turns a **completed** analysis job's persisted evidence into persisted, structured,
explainable **signals** — six fixed types (`problem`, `feature_request`, `question`, `praise`,
`opportunity`, `risk`), each linked to the real evidence it came from. This is generated
**automatically, once, at job completion** by `AnalysisJobRunner` — unlike Content Intelligence
above (which is cached but generated **on demand** by an API request), a signal is a row you can
query and filter without triggering any generation work.

**Signals are decision support, not objective truth.** `confidence` and `priority_score` are
explainable estimates computed from measured evidence, not measured facts themselves; `risk`
signals are early indicators, never confirmed outcomes; any AI-suggested "contributing factors"
are hypotheses, not verified root causes; recommendations are suggestions for a human to
consider, never automatic actions with an owner or deadline. Grouping is currently **job-scoped**
— the same underlying complaint reported across two different jobs (e.g. two YouTube videos)
produces two separate signals, not one merged across the whole account.

### Architecture

```
Completed analysis job
  → persisted AnalysisRecordEvidence rows (already written during the job -- Sprint 11/12)
  → classify each evidence row into at most one signal type (deterministic, rule-based)
  → group same-type evidence deterministically (duplicate signature, then token overlap)
  → compute measured metrics per group (counts, distributions, timestamps -- code only)
  → compute confidence (code only, from classifier confidence/cohesion/size/contradictions)
  → compute priority_score for problem/feature_request/risk only (versioned, weighted, capped)
  → generate title/summary/recommendations from deterministic local templates
  → [optional] bounded, grouped-signal-level enrichment from Gemini or OpenAI
  → idempotent upsert: AnalysisSignal + AnalysisSignalEvidence
  → existing insight generation and job completion continue unchanged
```

Grouping deliberately does **not** reuse Content Intelligence's embedding-based clustering
(`services/insights/local/clustering.py`) — that path loads a sentence-transformer model, which
is acceptable for on-demand insight generation but not for a step that must run automatically on
every single job completion. Instead, `services/signals/grouping.py` is a dependency-light, pure
Python algorithm: evidence is sorted into a canonical order (by `source_key`) before grouping
begins, so results are provably stable across retries and independent of database return order;
`duplicate_signature` (already computed by Text Intelligence) is checked first and is
authoritative; remaining items are grouped by Jaccard token overlap against a bounded threshold
(`SIGNAL_GROUPING_THRESHOLD`); a size-based safety valve falls back to signature-only grouping
for pathologically large buckets rather than performing unbounded comparisons.

### The six signal types

| Type | Meaning |
|---|---|
| `problem` | A failure, complaint, obstacle, or undesirable experience. |
| `feature_request` | An explicitly requested addition or change. |
| `question` | A recurring information need. |
| `praise` | A repeated, specific positive strength. |
| `opportunity` | A possible content/product improvement, softer than a direct request. |
| `risk` | An emerging reputation, churn, support-load, adoption, or security **indicator** — not a confirmed outcome. |

Classification (`services/signals/classification.py`) reuses the same intent/target/sentiment/
lexical-polarity/escalation-reason fields Text Intelligence already computed — no phrase
re-scanning, and the same multilingual (Arabic/English/mixed) support Text Intelligence already
provides. Each evidence row is checked against a fixed priority order (`risk` → `problem` →
`feature_request` → `opportunity` → `question` → `praise`) and contributes to **at most one**
signal type; empty, spam, or otherwise-unsupported evidence (already excluded from
`included_in_clean_analysis`) never reaches this step at all, and evidence that matches no
predicate is simply not turned into a signal — nothing is forced.

### Measured vs. inferred vs. recommended

Every `AnalysisSignal` field is one of three kinds, and the distinction is load-bearing:

- **Measured** (`frequency_count`, `evidence_count`, `first_observed_at`, `last_observed_at`, and
  the `sentiment_distribution`/`language_distribution`/`rating_distribution`/`duplicate_count`/
  `contradiction_count` inside `measured_metrics`) — plain counts computed in code from linked
  evidence. An LLM is never permitted to calculate or modify any of these.
- **Inferred** (`confidence`, `priority_score`, `severity`) — deterministic, explainable estimates
  computed from the measured numbers above, persisted alongside a full component breakdown
  (`confidence_factors`, `priority_factors` inside `measured_metrics`) so the number is never
  opaque.
- **Recommended** (`recommended_actions`) — structured suggestions for a human to consider, never
  an automatic action, never assigned an owner or deadline.

`duplicate records must not inflate counts`: `frequency_count` counts every linked evidence row
(including exact duplicates), while `evidence_count` counts only one representative per
`duplicate_signature` — used for confidence/cohesion so a flood of copy-pasted comments cannot
manufacture an artificially strong signal.

### Confidence

`services/signals/confidence.py` computes a single 0–1 score as a weighted combination of:
average classifier confidence (35%), group cohesion — average token overlap of members against
the group's anchor (25%), a size factor capped until a group reaches 10 distinct evidence items
(20% — small groups can never reach full size credit regardless of how confident each individual
item was), and a contradiction factor (20%) — all multiplied by a data-quality factor derived
from each member's own Text Intelligence escalation reasons. An LLM is never permitted to set or
adjust this score.

### Priority scoring

Computed **only** for `problem`, `feature_request`, and `risk` — `praise` and `question` never
receive a `priority_score`, so nothing implies false urgency for a strength or a routine
information need. `services/signals/priority.py` combines five configurable, weighted components
(frequency, severity, recency — exponential decay with a 30-day half-life, negative-sentiment/
low-rating impact, and confidence) into a raw 0–100 score, versioned by
`SIGNAL_PRIORITY_SCORING_VERSION` and persisted verbatim as `priority_factors` inside
`measured_metrics` so the number is always explainable, never just a bare figure.

Two guarantees are enforced structurally, not just by convention:

- **Higher frequency cannot reduce the score** — frequency is a monotonically non-decreasing
  ratio and no other component depends on it.
- **Lower confidence hard-caps the maximum reachable score** — `final_priority =
  min(raw_priority, confidence_ratio * 100)`, applied after the weighted sum, on top of
  confidence already being one of the five weighted components.

### Recommendations

`services/signals/recommendations.py` generates structured, bilingual (EN/AR) suggestions from
fixed local templates keyed by signal type and severity — never an LLM call. Each recommendation
carries `title`, `description`, `action_type`, `urgency` (`now`/`next`/`later`, derived from
severity), `rationale`, `suggested_success_metric`, `confidence`, bounded `evidence_ids`, and
`limitations`. No recommendation is ever assigned an owner, a deadline, or triggers an automatic
action.

### Optional AI enrichment

`services/signals/enrichment/` may improve a signal's `title`, `summary`, likely contributing
factors, and `recommended_actions`/`limitations` text — **only at the already-grouped-signal
level**, structurally mirroring the Content Intelligence AI layer's provider/registry/fallback
pattern but built as an independent, parallel implementation (not shared code) since the input
shapes genuinely differ.

- Uses the same `GEMINI_API_KEY`/`OPENAI_API_KEY`/model settings as Content Intelligence; local
  mode works completely without either configured.
- The response schema (`enrichment/schema.py`) has **no field at all** for priority, confidence,
  or any count — a provider cannot alter a measured or scored value even if it tried, because
  there is structurally nowhere in the validated response for such a value to go.
- Every schema model uses Pydantic `extra="forbid"` — a response that attempts to smuggle an
  extra field (e.g. an injected `"priority_score": 999`) fails validation **wholesale**, and that
  signal safely degrades to its local-only content rather than partially applying anything from
  the malformed response.
- Evidence excerpts are explicitly framed as **untrusted, third-party text data** in the system
  prompt — an embedded instruction like "ignore previous instructions" inside a comment is just
  more text to summarize, never something the model is asked to obey.
- Bounded batching, timeout, and retries; any provider failure (including an unexpected
  exception) degrades to the deterministic local content — enrichment can never fail job
  completion.
- Cached by a fingerprint of `(stable_key, title, summary, sorted evidence ids)` plus provider,
  model, and schema version — a retry with byte-identical evidence reuses the prior enrichment
  without a new provider call; a materially different regrouping correctly invalidates the cache.
- Raw prompts and raw provider responses are never persisted or logged — only status
  (`disabled`/`success`/`cache_hit`/`local_only`), provider, model, and schema version.

### Job integration and idempotency

Runs inside `AnalysisJobRunner._generate_signals`, immediately after this job's evidence is fully
persisted and before the job is marked complete, wrapped in a broad `try`/`except` — any
unexpected failure here is logged and the job still completes normally, since this is a purely
additive feature and a signal-less completed job is a supported, expected state (see "Known
limitations" below). `stable_key` (`f"{signal_type}:{sha256(anchor_source_key)[:32]}"`) is
deterministic, so a retried job upserts the same `AnalysisSignal`/`AnalysisSignalEvidence` rows
in place instead of duplicating them — verified against real PostgreSQL with concurrent upsert
races.

### API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/analysis/jobs/{job_id}/signals` | Paginated, filterable, sortable list. |
| GET | `/api/v1/analysis/jobs/{job_id}/signals/{signal_id}` | One signal with bounded evidence excerpts. |
| GET | `/api/v1/analysis/jobs/{job_id}/signals/summary` | Total count, count by type, and top-priority signals. |

List filters: `signal_type`, `min_confidence`, `min_priority`, `severity`; sort by `priority`
(default), `frequency`, `confidence`, or `recency`. List responses never include raw evidence
text (only already-bounded titles/summaries/recommendations); only the detail endpoint returns
bounded evidence excerpts (≤200 characters each). Ownership is enforced exactly like every other
job-scoped endpoint — an inaccessible or nonexistent job, or a signal that exists but belongs to
a different job, both return `404`, never `403` (so an unauthorized caller can't distinguish
"doesn't exist" from "isn't yours").

### Settings

| Setting | Default | Purpose |
|---|---|---|
| `SIGNAL_INTELLIGENCE_ENABLED` | `true` | Master switch; `false` skips signal generation entirely (job completes as before). |
| `SIGNAL_MIN_GROUP_SIZE` | `2` | Minimum distinct evidence items for a group to become a signal. |
| `SIGNAL_MAX_SIGNALS_PER_JOB` | `100` | Caps persisted signals per job, highest priority/confidence first. |
| `SIGNAL_MAX_EVIDENCE_PER_SIGNAL` | `20` | Caps linked evidence rows per signal (measured counts stay unbounded). |
| `SIGNAL_GROUPING_THRESHOLD` | `0.5` | Jaccard token-overlap threshold for non-duplicate-signature grouping. |
| `SIGNAL_MIN_CONFIDENCE` | `0.35` | Groups scoring below this are not persisted as signals. |
| `SIGNAL_RECOMMENDATIONS_MAX_PER_SIGNAL` | `5` | Caps recommendations per signal. |
| `SIGNAL_PRIORITY_SCORING_VERSION` | `v1` | Persisted on every scored signal for future formula changes. |
| `SIGNAL_ALGORITHM_VERSION` | `v1` | Persisted on every signal for future classification/grouping changes. |
| `SIGNAL_PROVIDER_ENRICHMENT_ENABLED` | `true` | Master switch for optional AI enrichment. |
| `SIGNAL_PROVIDER_BATCH_SIZE` | `5` | Signals per enrichment provider call. |
| `SIGNAL_PRIORITY_WEIGHT_*` | sum to `1.0` | Frequency/severity/recency/impact/confidence weights (validated at startup). |

### Known limitations

- Signals are **decision support, not objective truth** — always review before acting.
- `risk` signals are early **indicators**, never confirmed outcomes.
- AI-suggested contributing factors are **hypotheses**, never verified root causes.
- Recommendations never include an owner, a deadline, or trigger an automatic action.
- Grouping is currently **job-scoped** — the same underlying issue across multiple jobs produces
  separate signals, not one deduplicated across a whole account or channel.
- Historical jobs completed before this sprint have no signals until reprocessed.
- `severity` for `question`/`praise`/`opportunity` is currently always `low` — the underlying
  severity formula is only meaningfully differentiated for `problem`/`risk` today.

## Action Center

Sprint 19 lets a user turn a structured signal -- or a manual idea -- into a trackable
**ActionPlan** made of ordered **ActionTasks**, with a full audit trail. This is pure internal
record-keeping: nothing here ever triggers an external action. No Jira/GitHub issue is created, no
webhook fires, no notification is sent, and no scheduled monitoring runs -- see Known limitations.

### Plans, tasks, and statuses

```
ActionPlan.status:  draft -> open -> in_progress -> blocked/monitoring/completed/cancelled
ActionTask.status:  todo -> in_progress -> blocked/done/cancelled
```

Every transition is explicitly whitelisted in `app/services/actions/transitions.py` -- there is no
implicit "anything goes" fallback, and an unlisted transition returns `409`:

| Plan status | Can move to |
|---|---|
| `draft` | `open`, `cancelled` |
| `open` | `in_progress`, `blocked`, `monitoring`, `completed`, `cancelled` |
| `in_progress` | `blocked`, `monitoring`, `completed`, `cancelled` |
| `blocked` | `open`, `in_progress`, `cancelled` |
| `monitoring` | `in_progress`, `completed`, `cancelled` |
| `completed` | `monitoring` (the *only* reopen path) |
| `cancelled` | `draft` (the *only* restore path) |

| Task status | Can move to |
|---|---|
| `todo` | `in_progress`, `blocked`, `done`, `cancelled` |
| `in_progress` | `blocked`, `done`, `cancelled` |
| `blocked` | `todo`, `in_progress`, `cancelled` |
| `done` | `todo` (reopen) |
| `cancelled` | `todo` (restore) |

Completing a plan sets `completed_at`; leaving `completed` (i.e. `completed -> monitoring`) clears
it. A task reaching `done` sets its own `completed_at`; leaving `done` clears it. By default a plan
can only be marked `completed` once every non-cancelled task under it is `done`
(`ACTION_REQUIRE_TASKS_COMPLETE_FOR_PLAN_COMPLETION`, `409` otherwise) -- configurable per
deployment, not per plan.

### Signal-to-plan flow

```
POST /api/v1/analysis/jobs/{job_id}/signals/{signal_id}/action-plan
  {"generate_tasks": true, "max_tasks": null}
```

This verifies the caller owns both the job and the signal (404 otherwise, same "unowned looks
identical to nonexistent" discipline as every other endpoint), then:

- copies only the signal's **bounded** `title`/`summary`/derived `priority` onto a new
  `ActionPlan` -- never the evidence behind it, never an author identity;
- retains `source_signal_id` and `source_job_id` for traceability, but the plan's own content
  never depends on either still existing -- both are `ON DELETE SET NULL`, and
  `source_signal_type` is denormalized at creation time, so filtering/reading a plan works
  identically before and after its source signal is gone;
- optionally (`generate_tasks`, default `true`) creates one editable `ActionTask` per entry in the
  signal's already-persisted `recommended_actions`, ordered by recommendation urgency
  (`now` before `next` before `later`), each carrying `source_recommendation_index` so it can be
  traced back to which recommendation produced it;
- never modifies the original `AnalysisSignal` row -- verified by an automated test that diffs the
  signal's own fields before and after plan creation;
- is fully transactional: the plan, every generated task, and the `plan_created_from_signal` audit
  event are one database commit, so a crash mid-way never leaves an orphaned plan with no tasks and
  no history.

Generated tasks are fully editable afterward like any other task -- nothing about a task's origin
restricts what can be changed on it later.

### Priority and success-metric mapping

| Signal input | Action Center field |
|---|---|
| `priority_score >= 70` | plan `priority = critical` |
| `50 <= priority_score < 70` | plan `priority = high` |
| `30 <= priority_score < 50` | plan `priority = medium` |
| `priority_score < 30` | plan `priority = low` |
| `priority_score` is `None` (e.g. `praise`/`question`) | falls back to the signal's own `severity` (same 4-value vocabulary) |
| first recommendation's `suggested_success_metric` | plan `success_metric` (a starting suggestion, not an aggregate -- editable afterward) |
| recommendation `urgency` | task ordering (`position`), not a task field itself |

Nothing here ever invents an owner or a due date -- `owner_label` and `due_at` are always `null`
until a human sets them (see Known limitations on what `owner_label` is and isn't).

### Progress

`GET`ting a plan always returns a deterministically computed `progress` block -- plain arithmetic
over already-measured task counts (`app/services/actions/progress.py`), **never** an AI/LLM
estimate:

```json
{
  "total_tasks": 4,
  "completed_tasks": 2,
  "blocked_tasks": 1,
  "active_tasks": 1,
  "completion_percentage": 66.67,
  "overdue_task_count": 0,
  "plan_overdue": false
}
```

`completion_percentage` excludes cancelled tasks from the denominator (`completed / (total -
cancelled)`), and is `0.0` rather than dividing by zero when there are no countable tasks yet.
`plan_overdue` is `true` only when the plan has a `due_at` in the past **and** is not already in a
terminal status (`completed`/`cancelled`). Listing many plans computes every plan's progress in one
grouped aggregate query, never one query per row.

### Audit events (`ActionPlanEvent`)

Every plan and task mutation is recorded to `GET /api/v1/actions/plans/{plan_id}/events`:
`plan_created`, `plan_created_from_signal`, `plan_status_changed`, `plan_priority_changed`,
`plan_due_date_changed`, `plan_completed`, `plan_reopened`, `plan_archived`, `plan_restored`,
`task_created`, `task_updated`, `task_reordered`, `task_deleted`. Each event stores only the
specific bounded fields that changed (`previous_values`/`new_values`, capped at
`ACTION_EVENT_VALUE_MAX_BYTES` -- an oversized payload is replaced with `{"truncated": true}`
rather than persisted) -- never a full snapshot, never raw evidence text, never a secret. An
event whose actor account was later deleted keeps its `event_type` and value diff
(`actor_user_id` is `ON DELETE SET NULL`), so history survives account deletion even though the
identity of who did it does not. Plain detail edits (title/description/owner_label/
success_metric/expected_outcome with no status/priority/due-date change) are persisted but
intentionally do not generate their own event row -- only state-machine-relevant changes and the
explicit lifecycle events above are audited.

### Archive / restore

`POST /{plan_id}/archive` and `POST /{plan_id}/restore` toggle `archived_at` without touching
`status` -- archiving is a visibility concern (excluded from the default list; `?archived=true`
shows only archived plans), completely orthogonal to a plan's lifecycle state. Both are idempotent
(archiving an already-archived plan is a no-op, not an error) and both record an audit event.

### Concurrency and idempotency

- **Optimistic concurrency**: `ActionPlan.version` starts at `1` and increments on every mutating
  update via one atomic `UPDATE ... WHERE id = :id AND version = :expected_version`
  (`ActionPlanRepository.update_with_version`) -- the same single-statement compare-and-swap
  pattern `FileImportRepository.try_claim_for_start` already uses. Every `PATCH
  /actions/plans/{id}` requires `version` in the body; a stale value returns `409` rather than
  silently overwriting or losing a concurrent edit. `ActionTask` has no separate version column --
  task edits are plain atomic updates, and the one genuinely racy task operation (two callers
  adding a task to the same plan at once, both computing the same next `position`) is handled by
  retrying with a freshly re-read position on a unique-constraint conflict, bounded to 5 attempts,
  rather than surfacing a `500` to whichever caller lost the race.
- **Idempotency**: both plan-creation endpoints accept an `Idempotency-Key` header. Unlike
  `AnalysisJob.idempotency_key` (globally unique), `ActionPlan.idempotency_key` is unique per
  `(user_id, idempotency_key)` -- two different users may each safely reuse the same key string
  without colliding with each other. Proven under real concurrent PostgreSQL requests, including
  the from-signal path (plan *and* its generated tasks are never duplicated by a retry).
- **Reordering** (`POST /{plan_id}/tasks/reorder`) reassigns every task's position in two passes
  (every task to a unique negative placeholder, then to its final `0..N-1` position) specifically
  so swapping two tasks' positions never transiently collides with the
  `(action_plan_id, position)` unique constraint -- true on both PostgreSQL and SQLite, verified by
  a dedicated test for the classic "swap two unique values" case.

### API endpoints

```
POST   /api/v1/actions/plans                                   create manually
GET    /api/v1/actions/plans                                   list (filter/sort/paginate)
GET    /api/v1/actions/plans/{plan_id}
PATCH  /api/v1/actions/plans/{plan_id}                          partial update, requires `version`
DELETE /api/v1/actions/plans/{plan_id}                          hard delete (cascades tasks/events)
POST   /api/v1/actions/plans/{plan_id}/archive
POST   /api/v1/actions/plans/{plan_id}/restore
GET    /api/v1/actions/plans/{plan_id}/events

POST   /api/v1/actions/plans/{plan_id}/tasks
PATCH  /api/v1/actions/plans/{plan_id}/tasks/{task_id}
DELETE /api/v1/actions/plans/{plan_id}/tasks/{task_id}
POST   /api/v1/actions/plans/{plan_id}/tasks/reorder

POST   /api/v1/analysis/jobs/{job_id}/signals/{signal_id}/action-plan
```

`GET /actions/plans` filters: `status`, `priority`, `source_signal_type`, `due_before`/`due_after`,
`archived`, `search` (title, case-insensitive substring); sorts by `priority` (semantic rank, not
alphabetical), `due_date`, `updated_date`, or `created_date`, either direction. Every list response
is paginated (`ACTION_DEFAULT_PAGE_SIZE`/`ACTION_MAX_PAGE_SIZE`). `PATCH` request bodies are a
strict allow-list of editable fields -- there is no path by which a client-supplied `user_id` or
`id` is ever honored (mass-assignment is structurally impossible, not just unlisted).

### Settings

```
ACTION_CENTER_ENABLED=true
ACTION_PLAN_MAX_PER_USER=200
ACTION_TASK_MAX_PER_PLAN=100
ACTION_EVENT_MAX_PAGE_SIZE=100
ACTION_REQUIRE_TASKS_COMPLETE_FOR_PLAN_COMPLETION=true
ACTION_DEFAULT_PAGE_SIZE=20
ACTION_MAX_PAGE_SIZE=100
ACTION_EVENT_VALUE_MAX_BYTES=4096
ACTION_WRITE_RATE_LIMIT_REQUESTS=30
ACTION_WRITE_RATE_LIMIT_WINDOW_SECONDS=60
```

`ACTION_CENTER_ENABLED=false` makes every `/actions/*` and the signal `/action-plan` endpoint
refuse with `422` rather than silently no-op. Every write endpoint (create/update/delete/archive/
restore/task mutation/reorder) shares one rate-limit bucket via the existing Redis-backed limiter
(`app/services/rate_limit.py`) -- read endpoints are never rate-limited by this bucket.

### Known limitations

- **`owner_label` is plain free text, not a real team/user assignment** -- there is no
  notification, no permission change, and no linkage to any actual account when it's set.
- **No external task-system sync** -- no Jira, no GitHub issue, no webhook. Nothing in this sprint
  reads or writes anything outside this application's own database.
- **No automatic execution** -- an ActionPlan/ActionTask is a record of intent a human tracks
  manually; nothing here ever performs the action it describes.
- **No scheduled monitoring or reminders** -- `plan_overdue`/`overdue_task_count` are computed only
  when you ask (a `GET`), never pushed, polled, or alerted on in the background.
- **Action success measurement** -- Sprint 20's [Trend Intelligence](#trend-intelligence) closes
  this gap: `POST /actions/plans/{plan_id}/evaluate` measures whether a plan's source signal
  changed between two jobs. It is opt-in (a separate API call, never automatic) and never writes
  back to `ActionPlan.status` -- see that section for the full design and its own limitations.
- Deleting a plan is a genuine hard delete (cascades its tasks and events) -- there is no
  plan-level "recycle bin" beyond archive/restore, which is a visibility toggle, not a delete.
- Recommendation-derived tasks copy only `title`/`description`/urgency-derived ordering from each
  recommendation -- `rationale` and per-recommendation `evidence_ids` are not copied onto the task
  (the plan/task already never touches raw evidence at all).

## Trend Intelligence

Sprint 20 adds longitudinal **comparisons** between two of a user's own completed
`AnalysisJob`s from the same `SourceDataset` -- "did this get better or worse?" -- plus
optional evaluation of one `ActionPlan`'s measurable effect. Everything that determines a
match, a trend direction, or an outcome is **deterministic, code-computed arithmetic**
(`app/services/trends/`); an LLM is never required and never decides a match, a count, or a
direction. This is a set of point-in-time comparisons a user explicitly requests, not
scheduled monitoring -- see Known limitations.

### Comparison types

```
job_to_job         -- baseline job vs. comparison job, in full
before_after_event  -- the same two jobs, but rescaled to only the evidence occurring inside a
                       bounded window before/after a user-supplied event_at timestamp
action_outcome      -- a job_to_job comparison scoped to one ActionPlan's source signal, plus a
                       measured ActionOutcome row
```

All three reuse the exact same deterministic matching and trend-classification engine
(`app/services/trends/matching.py`, `app/services/trends/trend.py`) -- `before_after_event` and
`action_outcome` are different *inputs* to that engine, never a second algorithm.

### Eligibility

A comparison is only computed if, at creation time:

- `baseline_job_id` and `comparison_job_id` are two different jobs the caller owns, both
  `status=completed`, both belonging to the **same** `SourceDataset`;
- the baseline job's `completed_at` is strictly earlier than the comparison job's;
- both jobs analyzed at least `TREND_MIN_RECORDS_PER_JOB` records and have at least one
  generated `AnalysisSignal` each;
- for `before_after_event`: `event_at` is present, and at least one analyzed record with a
  usable timestamp falls inside both the before-window and the after-window (otherwise the
  request is rejected outright rather than silently returning an empty/misleading result);
- for `action_outcome`: the plan belongs to the caller, its `source_signal_id` belongs to the
  baseline job, and the comparison job completed **after** the plan was created (or completed,
  if already completed) -- a plan cannot be "evaluated" against a job that predates it.

Any violation is a `400`. An unowned/unknown job, comparison, or action plan is a `404` --
never a `403` -- so an unauthorized caller cannot distinguish a missing resource from someone
else's (the same discipline as every other Sprint 17-19 endpoint). Reusing an `Idempotency-Key`
with a *different* request body is a `409`, not a silent overwrite.

### Deterministic signal matching

`app/services/trends/matching.py` pairs each baseline signal with at most one comparison
signal, and vice versa -- no signal is ever matched twice. It never uses an LLM, embeddings, or
randomness:

1. Matching never crosses `signal_type` -- a `problem` can never match a `feature_request`.
2. If two signals share the exact same `stable_key` (the same underlying evidence recurred),
   that is treated as a certain match (`match_confidence=1.0`).
3. Otherwise, a bounded score combines title-token Jaccard similarity, `top_keywords` Jaccard
   similarity, and a `dominant_target` bonus. Below `TREND_MATCH_THRESHOLD`, no match.
4. All qualifying candidate pairs are sorted by `(score desc, baseline stable_key, comparison
   stable_key)` -- a total order with no ties left to database/input ordering -- then assigned
   greedily. The result is **independent of input order** and always picks the
   highest-confidence pairing when two candidates compete for the same signal.

An unmatched comparison-side signal is `new`; an unmatched baseline-side signal is
`resolved`/`insufficient_data` (see below).

### Trend calculation

Each `SignalTrend` row's direction is computed from **frequency ratio** (a signal's occurrence
count normalized by its job's total analyzed record count), not raw counts -- so two jobs of
very different sizes are compared fairly:

| `trend` | Meaning |
|---|---|
| `new` | No baseline counterpart; appeared only in the comparison job. |
| `rising` | Frequency ratio increased by at least `TREND_RISING_THRESHOLD`%. |
| `stable` | Frequency ratio changed by no more than `TREND_STABLE_CHANGE_TOLERANCE`%. |
| `falling` | Frequency ratio decreased by at least `TREND_FALLING_THRESHOLD`%. |
| `resolved` | Present in the baseline job, absent from a *sufficiently sampled* comparison job. |
| `insufficient_data` | Baseline occurrence count is below `TREND_MIN_SIGNAL_COUNT`, a job analyzed zero records, or (for a disappeared signal) the comparison job's sample is too small to distinguish "resolved" from "not enough data to tell". |

A ratio-change percentage strictly between the stable tolerance and the rising/falling
threshold is conservatively reported as `stable` rather than guessing a direction the data
doesn't clearly support. `percentage_change` (the raw, unnormalized count-based figure) is
deliberately set to `null` whenever the baseline count is below `TREND_MIN_SIGNAL_COUNT` -- a
percentage computed from 1-2 occurrences is noise, not a trend. Each `SignalTrend` also carries
`measured_metrics`: both sides' frequency ratios, sentiment-distribution shift, rating delta,
priority/confidence change, evidence coverage, and duplicate/contradiction counts -- every
number here is code-computed, never AI-adjusted.

### Release/event impact

For `comparison_type=before_after_event`, each matched/new/disappeared signal's counts are
rescaled to only the linked evidence whose `occurred_at` falls inside
`[event_at - window_before_days, event_at)` (before) or `[event_at, event_at +
window_after_days)` (after) -- windows default to `TREND_DEFAULT_WINDOW_DAYS` and are capped at
`TREND_MAX_WINDOW_DAYS`. Evidence lacking a usable timestamp is excluded and **disclosed**,
never silently dropped, in that row's `limitations`.

**GitHub release metadata, or any other source-provided event timestamp, may suggest that a
change relates to an event -- it never proves causation.** Every caption this system produces
(deterministic or AI-narrated) uses temporal-association wording -- "appeared after", "increased
following", "temporally associated with" -- and never causal wording ("was caused by",
"confirmed regression"), unless the underlying source evidence itself explicitly states it.

### Action outcomes

`POST /actions/plans/{plan_id}/evaluate` computes (or, with a repeated `Idempotency-Key`,
replays) an `action_outcome` comparison scoped to the plan's `source_signal_id`, then returns
the resulting `ActionOutcome`:

| Underlying trend | `outcome` | `suggested_next_status` |
|---|---|---|
| `falling` | `improved` | `consider_completion` |
| `resolved` | `resolved` | `consider_completion` |
| `stable` | `unchanged` | `continue_monitoring` |
| `rising` | `worsened` | `reopen_investigation` |
| `insufficient_data`, or fewer than `TREND_OUTCOME_MIN_POST_ACTION_RECORDS` post-action records | `inconclusive` | `insufficient_evidence` |

`score` is a deterministic `[-1, 1]` figure derived from the same frequency-ratio change (never
an LLM judgment). **`suggested_next_status` is exactly that -- a suggestion.** Nothing in this
sprint ever writes to `ActionPlan.status`; the service layer that computes outcomes never even
imports `ActionPlanRepository`'s write methods. A plan's status remains 100% user-controlled,
regardless of how many times it's evaluated or what the outcome says. Simplification, always
disclosed via `limitations`: a decrease in the target signal's presence is treated as
"improved" and an increase as "worsened" uniformly across all `signal_type`s -- it does not
model type-specific success semantics (e.g. a rising `feature_request` could also mean growing,
justified demand rather than an unaddressed problem).

### Measured vs. inferred vs. AI-narrated

Same three-way distinction as Structured Signal Intelligence (Sprint 17):

- **Measured**: counts, frequency ratios, percentage/absolute change, sentiment/rating deltas,
  evidence coverage -- plain arithmetic over already-persisted rows.
- **Inferred**: `match_confidence` (matching-algorithm confidence) and `confidence` (overall
  trend confidence, folding in match quality and sample size) -- explicitly-labeled estimates,
  never presented as fact.
- **AI-narrated (optional)**: `summary.explanation` (`app/services/trends/enrichment.py`) runs
  strictly *after* all of the above is final. Its Pydantic response schema has no field for a
  count, percentage, confidence, trend direction, or outcome result -- a provider physically
  cannot alter a measured/scored value, there is nowhere in the validated output for one to go.
  A defense-in-depth phrase filter discards the entire AI result (falling back to a local,
  template-generated summary) if it contains banned causal wording despite the system prompt's
  instruction not to. Neither the prompt sent to a provider nor its raw response text is ever
  persisted -- only the validated, bounded structured result.

### Provider fallback

Reuses the existing `INSIGHT_AI_PRIMARY_PROVIDER`/`INSIGHT_AI_FALLBACK_PROVIDER`/Gemini/OpenAI
settings and the same `call_with_retry` helper as Content Intelligence and Signal enrichment.
Any failure -- missing keys, timeout, rate limit, invalid JSON, schema violation, banned-phrase
hit, or any other unexpected exception -- degrades silently to a plain, deterministic,
count-based local summary. **A provider outage can never fail a comparison**;
`TREND_PROVIDER_ENRICHMENT_ENABLED=false` skips the provider call entirely.

### API endpoints

```
POST   /api/v1/comparisons                                     create (or idempotently replay)
GET    /api/v1/comparisons                                     list (filter/sort/paginate)
GET    /api/v1/comparisons/{comparison_id}
GET    /api/v1/comparisons/{comparison_id}/trends               per-signal trend results

POST   /api/v1/actions/plans/{plan_id}/evaluate                 create/replay an action_outcome comparison
GET    /api/v1/actions/plans/{plan_id}/outcomes                 list this plan's measured outcomes
```

`POST /comparisons` accepts `baseline_job_id`, `comparison_job_id`, `comparison_type`, optional
`action_plan_id`/`event_name`/`event_at`/`window_before_days`/`window_after_days`, and an
`Idempotency-Key` header (same user-scoped-NULL-never-collides convention as `ActionPlan`).
`GET /comparisons` filters by `comparison_type`/`source_dataset_id`/`action_plan_id`/`status`;
`GET .../trends` filters by `trend`/`signal_type`/`min_confidence` and sorts by
`change`/`priority`/`confidence`/`title`. List responses are summary-only; nothing in this
sprint ever returns raw evidence text through a trends endpoint -- `measured_metrics` carries
only bounded, already-aggregated numbers.

### Settings

```
TREND_INTELLIGENCE_ENABLED=true
TREND_MATCH_THRESHOLD=0.45
TREND_MIN_RECORDS_PER_JOB=5
TREND_MIN_SIGNAL_COUNT=2
TREND_STABLE_CHANGE_TOLERANCE=15.0
TREND_RISING_THRESHOLD=25.0
TREND_FALLING_THRESHOLD=25.0
TREND_DEFAULT_WINDOW_DAYS=30
TREND_MAX_WINDOW_DAYS=365
TREND_MAX_SIGNALS_PER_COMPARISON=200
TREND_OUTCOME_MIN_POST_ACTION_RECORDS=3
TREND_ALGORITHM_VERSION=v1
TREND_DEFAULT_PAGE_SIZE=20
TREND_MAX_PAGE_SIZE=100
TREND_WRITE_RATE_LIMIT_REQUESTS=20
TREND_WRITE_RATE_LIMIT_WINDOW_SECONDS=60

TREND_PROVIDER_ENRICHMENT_ENABLED=true
TREND_PROVIDER_TIMEOUT_SECONDS=30
TREND_PROVIDER_MAX_RETRIES=1
TREND_PROVIDER_MAX_EVIDENCE_EXCERPTS=5
TREND_PROVIDER_MAX_EXCERPT_CHARS=200
```

`TREND_INTELLIGENCE_ENABLED=false` makes every `/comparisons/*` route, plus `/evaluate` and
`/outcomes`, refuse with `422`. Comparison creation and plan evaluation share one Redis-backed
rate-limit bucket (`app/services/rate_limit.py`) -- read endpoints are never rate-limited by it.
No new secrets are introduced; provider credentials are the existing `GEMINI_API_KEY`/
`OPENAI_API_KEY`.

### Known limitations

- **Comparisons require the same `SourceDataset`** -- there is no cross-dataset comparison, and
  no way to compare a YouTube dataset against a GitHub one.
- **Point-in-time, not scheduled monitoring** -- a comparison is computed once, synchronously,
  when requested. Nothing in this sprint watches for new jobs, polls, or alerts in the
  background; re-comparing later means submitting a new request against a newer job.
- **Association, never causation** -- a `before_after_event` or `action_outcome` result
  describes what changed and when, never why. GitHub release metadata, event timestamps, and
  action-plan timing are all just that -- timing. See Release/event impact and Action outcomes.
- **Action plans are never auto-completed, auto-reopened, or otherwise mutated by an
  evaluation** -- `suggested_next_status` is advisory text in the response body only.
- **Matching is source-agnostic and purely deterministic** -- no connector-specific branches, no
  clustering model, no LLM in the matching/trend/outcome path itself (only the strictly-optional,
  schema-locked narrative layer touches a provider, and only after everything else is final).
- **Bounded, not exhaustive** -- at most `TREND_MAX_SIGNALS_PER_COMPARISON` signals are
  considered per comparison (lowest-priority signals are dropped first, and disclosed via
  `limitations` when this happens; a plan's own target signal is never dropped from its
  `action_outcome` comparison).
- **`before_after_event` windowing is approximate** -- it rescales each signal's already-bounded
  linked-evidence sample (capped by `SIGNAL_MAX_EVIDENCE_PER_SIGNAL`, Sprint 17), not its full
  occurrence count, since re-deriving full windowed occurrence counts would require re-running
  signal grouping from scratch. Always disclosed via `limitations`.

## Ask Your Data and Reports

Sprint 21 adds two features built on the exact same foundation: **grounded question-answering**
over a user's own analyzed data (`POST /api/v1/analysis/query`), and **structured, persisted
reports** (`POST /api/v1/reports`). Both share one deterministic retrieval layer
(`app/services/query/retrieval.py`) -- neither ever re-collects from a source, reruns sentiment/
Text Intelligence, or dumps a whole dataset into a prompt. **Answers are limited to this
project's own indexed data; there is no web search, and unsupported questions are declined
rather than guessed at.**

### Supported questions

```
- top problems or feature requests
- what changed between two analyses / what worsened or improved
- why a signal received its priority
- evidence behind a signal or recommendation
- an action plan's outcome or task progress
- sentiment/topic summaries
- counts and distributions (optionally filtered by record type, language, rating, or time)
```

A question that doesn't match any of these returns a safe `answer_type="unsupported"` response
(HTTP `200`, not an error) rather than a guess -- see Local mode.

### Grounding, retrieval, and citations

`app/services/query/retrieval.py` resolves the request's scope (`job_id`/`dataset_id`/
`comparison_id`/`action_plan_id` -- at least one is required) through the *same* ownership-scoped
repository lookups every other Sprint 17-20 service uses, then pulls only:

- the signals/evidence/trends/outcomes reachable from that resolved scope (never a cross-dataset
  or cross-user read);
- bounded by `ASK_DATA_MAX_CONTEXT_ITEMS`/`ASK_DATA_MAX_EVIDENCE_EXCERPTS` -- never a full-dataset
  dump;
- filtered by explicit, structured request fields (`record_type`, `language`, `sentiment`,
  `min_rating`/`max_rating`, `occurred_after`/`occurred_before`) -- filters are never parsed out
  of the free-text question, so retrieval stays fully deterministic and reproducible.

Every response discloses `record_count_considered` (the true matching count, not just the bounded
sample size), `filters_applied`, and bounded `evidence_references`/`signal_references`/
`trend_references`/`outcome_references` -- these are the **citations**: internal ids plus a short
excerpt/label, resolvable back to the exact underlying rows, never a claim without one. List
responses never include full evidence bodies or an author identity.

### Local mode

Works with **zero configured provider**. `app/services/query/intents.py` classifies a question
into one of the supported intents using deterministic keyword matching (never an LLM, so
classification is 100% reproducible and works identically with or without a provider), and
`app/services/query/local_answers.py` computes the answer directly from already-persisted,
measured rows -- the same `priority_factors`/`confidence_factors` Sprint 17 signals already
carry, the same trend/outcome rows Sprint 20 already computed. A question that classifies as
none of the supported intents returns the safe "insufficient supported data" response.

### Provider mode

Optional, reuses the existing Gemini/OpenAI architecture (same keys/models as Content
Intelligence and Trend Intelligence). Critically, **the provider runs strictly after the local
answer already exists** -- its only job is to rephrase that answer more naturally and select
citations from the already-retrieved context. Its Pydantic response schema has no field for a
confidence score, a count, or any other measured value, so it cannot alter one even if it tried.
Every citation is validated against the actual ids present in the retrieved context; an answer
with even one invented citation, or with banned causal wording ("was caused by", "confirmed
regression", ...), is discarded outright and the caller keeps the local answer. Any provider
failure (missing keys, timeout, rate limit, invalid JSON, schema violation) degrades the same
way -- **a provider outage can never fail a question.**

`mode` in the request body controls this: `"local"` never attempts a provider; `"provider"` and
`"auto"` attempt one and silently fall back to local on any failure.

### Caching

Answers are cached in **Redis only, never Postgres** -- per the "don't store user questions
unless required" principle, no question text (raw or hashed-and-searchable) is ever written to
the database. The cache key (`app/services/query/cache.py`) is a SHA-256 fingerprint of the
user, question, scope, filters, a `data_version` derived from the resolved scope's own
`updated_at`/`completed_at`, mode, and a schema version -- so it invalidates itself the moment
the underlying job/comparison/plan actually changes, and simply expires after
`ASK_DATA_CACHE_TTL_SECONDS` otherwise. **Ownership/eligibility resolution always runs before any
cache lookup** -- a cache hit can never bypass an ownership check, since retrieval always
executes first regardless of cache outcome. If Redis is unreachable, caching is silently skipped
(the answer is still computed, just not cached).

### Reports

`Report` (table `reports`) is a persisted, **structured-JSON-only** record generated once from a
job/dataset/comparison/action-plan scope, reusing the exact same retrieval as Ask Your Data:

```
executive_brief            job or dataset scope -- summary, top problems, feature requests,
                            risks/opportunities, trends (if a comparison exists), recommendations
product_feedback           job or dataset scope -- summary, top problems, feature requests,
                            bounded evidence references
release_impact              requires a comparison_id scope -- summary, trend counts/detail,
                            recommendations
github_repository_health    requires a dataset_id scope for a GitHub-sourced dataset -- repo
                            metadata (stars, open issues, language, topics) already persisted on
                            `SourceDataset.dataset_metadata` at collection time, plus top problems
action_outcome               requires an action_plan_id scope -- progress, measured outcomes
```

`content` is `{"sections": [...], "executive_narrative": "..."}` -- each section has a `type`,
`title`, and a code-computed `content` dict; sections with nothing to show are omitted rather than
persisted empty, bounded to `REPORT_MAX_SECTIONS`. `executive_narrative` is the same optional,
schema-locked, citation-free AI narration pattern as Ask Your Data's provider mode
(`app/services/reports/enrichment.py`), always falling back to a deterministic, template-built
sentence when disabled/unavailable/failed. **A report never changes the scope it was generated
from** -- an `action_outcome` report never touches `ActionPlan.status`, exactly like Sprint 20's
own outcome evaluation. PDF/DOCX generation is out of scope; `content` is JSON only.

`input_fingerprint` (SHA-256 of report type + scope + `data_version` + algorithm version) lets a
caller detect a report may be stale without a second full data snapshot being stored. Creation is
idempotent the same user-scoped-key way as every other Sprint 18-20 write endpoint.

### API endpoints

```
POST   /api/v1/analysis/query                                   ask a grounded question

POST   /api/v1/reports                                          generate (or idempotently replay)
GET    /api/v1/reports                                          list (filter by type/scope/status)
GET    /api/v1/reports/{report_id}
DELETE /api/v1/reports/{report_id}
```

`POST /analysis/query` accepts `question`, optional `job_id`/`dataset_id`/`comparison_id`/
`action_plan_id`, optional `filters`, and `mode` (`local`/`provider`/`auto`, default `auto`).
`POST /reports` accepts `report_type`, the same four optional scope fields, optional `title`, and
an `Idempotency-Key` header. Both share one Redis-backed write-rate-limit bucket per feature
(`ASK_DATA_WRITE_RATE_LIMIT_*`/`REPORT_WRITE_RATE_LIMIT_*`); `REPORT_MAX_PER_USER` bounds total
reports per user the same way `ACTION_PLAN_MAX_PER_USER` bounds action plans. Every unowned or
unknown scope id, comparison, plan, or report returns `404`, never `403`.

### Settings

```
ASK_DATA_ENABLED=true
ASK_DATA_MAX_QUESTION_LENGTH=1000
ASK_DATA_MAX_CONTEXT_ITEMS=50
ASK_DATA_MAX_EVIDENCE_EXCERPTS=20
ASK_DATA_MAX_EXCERPT_CHARS=200
ASK_DATA_CACHE_TTL_SECONDS=900
ASK_DATA_WRITE_RATE_LIMIT_REQUESTS=20
ASK_DATA_WRITE_RATE_LIMIT_WINDOW_SECONDS=60

ASK_DATA_PROVIDER_ENABLED=true
ASK_DATA_PROVIDER_TIMEOUT_SECONDS=30
ASK_DATA_PROVIDER_MAX_RETRIES=1

REPORTS_ENABLED=true
REPORT_MAX_PER_USER=200
REPORT_MAX_SECTIONS=20
REPORT_ALGORITHM_VERSION=v1
REPORT_DEFAULT_PAGE_SIZE=20
REPORT_MAX_PAGE_SIZE=100
REPORT_WRITE_RATE_LIMIT_REQUESTS=10
REPORT_WRITE_RATE_LIMIT_WINDOW_SECONDS=60
```

`ASK_DATA_PROVIDER_ENABLED` covers *both* features' optional AI narration -- no separate
`REPORT_PROVIDER_*` settings exist, since both are the same "narrate already-computed data" shape
reusing the same Gemini/OpenAI keys/models. No new secrets.

### Privacy and prompt-injection safety

The question, every evidence excerpt, and every report section are treated as **untrusted data,
never instructions** -- both provider system prompts state this explicitly, and an embedded
"ignore previous instructions" attempt inside a question is just more text to classify/narrate,
never something the system obeys (`tests/unit/query/test_provider.py` and
`tests/unit/query/test_intents.py` include dedicated prompt-injection-attempt tests). No author
identity, private repository content, raw full evidence body, provider prompt, provider response,
or internal error detail is ever included in a response or a log line. Reference ids in citations
are internal database ids, not URLs or external identifiers.

### Known limitations

- **Answers and reports are limited to this project's own indexed, already-analyzed data** -- no
  web search, no external knowledge, no autonomous action of any kind.
- **A declined ("unsupported") question is not a bug** -- it means no supported intent matched,
  or the resolved scope has no data to answer from; asking a narrower or differently-scoped
  question may succeed.
- **Citations are internal evidence/signal/trend/outcome references**, not proof of anything
  beyond "this is the data the answer was grounded in" -- the same association-not-causation
  rules from Trend Intelligence apply to any trend/outcome-related answer or report section.
- **Reports are JSON only** -- no PDF/DOCX/other export format is generated.
- **No scheduling** -- a report or answer reflects the data at generation time; nothing re-runs
  automatically when new data arrives.
- **`github_repository_health` reflects the dataset's last collection**, not a live GitHub API
  call -- repository metadata is only as fresh as the most recent analysis job for that dataset.

## Text Intelligence

`app/services/text_intelligence/` is a **source-agnostic** rule layer — it imports nothing from
`app/services/youtube.py` or any YouTube-specific model/schema, and operates purely on plain text
plus an optional opaque `source_key`. It is designed to work identically for YouTube comments,
and — in a future sprint — Reddit/GitHub/uploaded/direct text, without any changes to this
package.

### Architecture

```
TextIntelligenceService.analyze(texts, source_keys)
  1. TextProcessingService.process_comments(texts)   # existing Sprint 7 normalization, reused as-is
  2. per-item signal extraction (independent, pure-function modules):
       emoji.py        spam.py        sarcasm.py      arabizi.py
       lexical_polarity.py            negation.py     contrast.py
       target_scope.py                intent.py
  3. duplicates.py groups exact/near-duplicate texts (O(n) canonical signature,
     no pairwise comparison) — the transformer model runs ONCE per duplicate
     group, and results fan out to every member, preserving each item's own
     identity, order, and per-item signals (spam, sarcasm, etc. are still
     computed per-comment; only the expensive model call is shared).
  4. SentimentService.analyze(...) — existing Sprint 8 multi-model routing, unchanged
  5. fusion.py combines the model result with every rule signal into one
     final TextIntelligenceResult per input, in the original order
```

Each of the modules in step 2 is independently unit-tested and (mostly) a pure function taking
text/config in and returning a typed Pydantic result — no framework imports, no I/O, no shared
mutable state. Regexes and lexicon patterns are compiled once at import time.

### Result schema

`app.schemas.text_intelligence.TextIntelligenceResult` is the typed, dedicated result contract —
no generic dictionaries are returned where a schema is practical. It includes the final fused
`sentiment` (`positive` / `negative` / `uncertain` / `unsupported` — the same four business
states used everywhere else in this project), plus every intermediate signal (`emoji_signal`,
`spam`, `sarcasm`, `intent`, `target`, `lexical_matches`, `negation_evidence`, `contrast_spans`,
`escalation_reasons`, etc.) so the reasoning behind the final sentiment is inspectable, not a
black box.

### Business sentiment semantics (unchanged from Sprint 8)

- Only two business sentiment labels exist: **positive** and **negative**.
- **uncertain** and **unsupported** are operational states, not sentiments.
- A model's native "neutral" label is always reported as `uncertain` with
  `uncertainty_reason="native_neutral"` — Text Intelligence never invents a third business
  sentiment, and only overrides `native_neutral` when there is exceptionally strong, explicit,
  logged evidence (see Fusion order below); in practice this is rare.

### Emoji-only behavior

Emoji-only comments are analyzed **without** calling the transformer model:

- ≥`EMOJI_ONLY_MIN_COUNT` (default 3) unambiguous positive emoji, no negative emoji present →
  `positive`, confidence = `EMOJI_ONLY_CONFIDENCE` (default 0.75), `model_sentiment=null`.
- Same for negative.
- Both strong-positive and strong-negative present → `uncertain` (`emoji_conflict`), never
  silently resolved to one side.
- Only ambivalent/unclassified emoji present → `uncertain` (`ambiguous_emoji`).

### Spam aggregation semantics

Spam comments are **never deleted or excluded from persistence**. They are:

- counted explicitly (`spam_count`, `matched_spam_rules` per comment),
- still sentiment-analyzed (so the **raw** summary includes them), and
- excluded from the separate `clean_summary` (see the JSON example above).

Duplicate/templated comments are flagged with the `duplicate_content` spam reason on every
occurrence after the first, but every occurrence is still counted individually in aggregates —
only the (single, shared) model call is deduplicated, not the comment itself.

### Sarcasm limitations

`sarcasm_score` is a small heuristic point total (emoji +2, phrase +2, `!!!`/`???` +1 each,
lexical contradiction +2, repeated laughter +2, ellipsis+negation +2, praise-then-contrast +1) —
**it is not a probability and not a claim of model-level sarcasm-detection accuracy.** Weak
sarcasm evidence never overrides a confident model result; sarcasm without any clear polarity
signal becomes `uncertain` rather than being force-flipped to negative.

### Arabizi limitations

Arabizi (Arabic written in Latin letters/digits, e.g. `3ajabny`, `wa7ashtna`) is detected via a
small curated lexicon plus a conservative digit-substitution pattern that explicitly excludes
version numbers, years, URLs, and alternating-character identifiers (e.g. `a1b2c3`). Detected
Arabizi contributes to `escalation_reasons` and evidence. **Known limitation:** Arabizi detection
does not yet re-route the comment to the mixed-language transformer model internally (doing so
safely would require changes to the existing, tested `SentimentRouter`, which this sprint
deliberately left untouched) — today it mainly enriches evidence/escalation metadata rather than
changing which model analyzes the comment.

### Unsupported reason taxonomy

`empty_text`, `punctuation_only`, `number_only`, `url_only`, `mention_only`, `hashtag_only`,
`emoji_only_ambiguous`, `unsupported_language`, `unknown_language`, `trivial_short_text`,
`processing_failure`, `spam_excluded`, `other`. Positive/negative emoji-only comments are never
classified as unsupported. The video-sentiment report's `unsupported_breakdown` groups comments
by this exact reason with a count, a percentage (of `total_comments`), and up to 5 example texts
per reason (never logged — see Performance below).

### Fusion order (`app/services/text_intelligence/fusion.py`)

1. Trivial text → `unsupported` (specific reason), short-circuits everything else.
2. Emoji-only → resolved per the rules above, bypassing the model.
3. Routing says unsupported language and no Arabizi detected → `unsupported`.
4. Otherwise use the model result. If native-neutral, preserve `uncertain` unchanged. Else, in
   order: strong sarcasm + negative evidence → negative; sarcasm with no clear polarity →
   uncertain; weak sarcasm never overrides a confident model; a protected intent (request/
   question/suggestion) guards a *borderline*-confidence negative result from becoming
   `uncertain`; a strong negative post-contrast clause can outweigh a borderline-confidence
   initial positive read; lexical/model agreement gives a small, capped confidence boost; a
   reinforcing (non-conflicting) emoji gives a small, capped boost; a conflicting emoji is noted
   in evidence but never silently resolves to one side.
5. Escalation metadata (`escalation_recommended`, `escalation_reasons`) is computed independently
   of the above and never blocks a result — it exists purely so a **future** (not implemented
   this sprint) FAST/SMART/HYBRID policy can decide when an LLM call would be worth its cost.

Every threshold above is a named setting (`EMOJI_ONLY_MIN_COUNT`, `SARCASM_SCORE_THRESHOLD`,
`SPAM_LOW_UNIQUE_WORD_RATIO`, `NEGATION_MAX_SCOPE_TOKENS`, `CONTRAST_POST_CLAUSE_WEIGHT`, etc. —
see `app/config/settings.py`), all clearly heuristic and none carried over from any other project
without being re-justified for this one.

### Future LLM escalation boundary

**No LLM is called anywhere in this sprint.** `escalation_recommended`/`escalation_reasons` are
deterministic metadata only, describing *when a future policy might choose to escalate* (low
confidence, model/rule disagreement, sarcasm, mixed language, Arabizi, conflicting emoji, complex
contrast, ambiguous target, native neutral) — no network call, no API key, no cost is incurred by
computing them.

### Performance

Rules are regex/dictionary-based and run in-process on CPU — no model download, no network call.
Regexes and lexicon patterns are compiled once at import time, not per comment. Duplicate
detection is O(n) (a single pass building a signature → indices map), never pairwise. Comment
text is never written to logs anywhere in this package.

## Authentication and Authorization

Every endpoint that triggers paid APIs, expensive ML, or persistence now requires a signed-in
user. Bearer JWT access tokens (short-lived) + opaque, rotating refresh tokens (long-lived,
single-use). No cookies, no sessions in the browser-storage sense, no OAuth providers.

### Architecture at a glance

- **Access tokens** are stateless HS256 JWTs (`app/services/auth/jwt.py`): the API validates them
  without a database round trip except to confirm `token_version` still matches (see below).
- **Refresh tokens** are the opposite: a cryptographically random opaque string
  (`secrets.token_urlsafe`), never itself stored — only its SHA-256 hash (salted with
  `AUTH_REFRESH_TOKEN_PEPPER`) lives in the `refresh_sessions` table. Presenting one rotates it
  into a new one **atomically** (`RefreshSessionRepository.rotate`, a single `SELECT ... FOR
  UPDATE` transaction) and marks the old one used.
- **Replay detection**: presenting an already-used refresh token revokes every token in its
  rotation family in one statement, forcing full re-login. A genuine concurrent double-use (two
  requests racing on the same token) is treated identically to theft — see "Concurrent refresh
  rotation" below for why that's the correct, conservative choice, proven with real threads
  against real PostgreSQL in `tests/integration/auth/test_auth_postgres.py`.
- **Instant global logout**: `token_version` on `User` is bumped by `logout-all` and by an admin
  disabling/changing a user's role. `get_current_user` checks the JWT's `token_version` claim
  against the current DB value on every request — a stale access token stops working immediately,
  without needing a blacklist.
- **Ownership, not just authentication**: analysis jobs and everything derived from them
  (results, evidence, insights) carry a `user_id`. Non-owners get **404**, not 403, so an
  unauthorized caller can't even confirm a `job_id` exists. Enforced in the repository layer
  (`AnalysisJobRepository.get_by_id_for_owner`), not just the router. Admins bypass ownership
  checks entirely; workers never touch HTTP auth at all (they operate on jobs directly via
  `AnalysisJobRepository`, same as before this sprint).

### User model and roles

`User` (table `users`): `email` (normalized — trimmed + lowercased — before every uniqueness
check and lookup), `password_hash` (argon2id, never plaintext, never returned by any endpoint),
`display_name`, `role` (`user` / `admin`), `status` (`active` / `disabled`),
`is_email_verified`, `token_version`, `failed_login_attempts`, `locked_until`, `last_login_at`,
`is_system_user` (see "Legacy data" below).

### Password security

Argon2id via `argon2-cffi` directly (not `passlib`), encapsulated in `PasswordService`
(`app/services/auth/password.py`):

- Policy: `AUTH_PASSWORD_MIN_LENGTH`–`AUTH_PASSWORD_MAX_LENGTH` characters (defaults 10–128),
  rejects whitespace-only, no arbitrary composition rules (no forced digit/symbol/case mix).
  Length is checked **before** hashing so an attacker can't force expensive argon2 work with a
  multi-megabyte string.
- `verify_password` never raises on a malformed/sentinel hash (e.g. the system user's unusable
  marker) — it returns `False`, same as a genuine mismatch.
- `needs_rehash` supports upgrading argon2 cost parameters later without a forced password reset:
  checked on every successful login, and the hash is silently re-computed and stored if the
  configured parameters have changed since the user last logged in.
- Nothing here ever logs a plaintext password. `login()`'s failure path runs a real dummy argon2
  verify even for a nonexistent account, so response timing doesn't leak account existence on top
  of the already-generic error message.

### Access tokens (JWT)

Claims: `sub` (user id), `role`, `type=access`, `iat`, `exp`, `jti`, `token_version`, and
(since Sprint 14.1) an optional `sid` — the id of the refresh session this access token was
issued or rotated alongside. Signed HS256 with `AUTH_ACCESS_TOKEN_SECRET`.
`AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` controls lifetime (default 15).

`JWTService.decode_access_token` explicitly allow-lists the algorithm on decode
(`algorithms=[settings.AUTH_ACCESS_TOKEN_ALGORITHM]`) — it never trusts whatever `alg` the token
header itself claims, which is what closes the classic JWT "alg confusion" / `alg=none` attack.
It also requires every one of the original claims to be present, rejects the wrong `type`, and
rejects an expired `exp` — all via `InvalidAccessTokenError` (401, `WWW-Authenticate: Bearer`).
`sid` is deliberately **not** in that required-claims list — it's optional so a token issued
before Sprint 14.1 (with no `sid` at all) keeps working unchanged, see
[Session-aware access-token validation](#session-aware-access-token-validation) below.

### Refresh tokens and rotation

`RefreshSession` (table `refresh_sessions`): `user_id` (FK, `ON DELETE CASCADE`), `token_hash`
(unique, indexed, SHA-256 hex of `raw_token + AUTH_REFRESH_TOKEN_PEPPER`), `family_id`,
`parent_token_id` / `replaced_by_token_id` (lineage), `issued_at` / `expires_at` / `used_at` /
`revoked_at` / `last_used_at`, and `created_by_ip_hash` / `last_used_ip_hash` / `user_agent_hash`
— HMAC-SHA256 fingerprints, populated on issue and on every rotation (see
[Session fingerprinting](#distributed-rate-limiting-email-verification-and-password-reset) below).
Only bounded hashes are ever stored there, never raw IP/UA strings.

`AUTH_REFRESH_TOKEN_EXPIRE_DAYS` controls lifetime (default 30). A token is single-use: calling
`POST /api/v1/auth/refresh` with it always returns a **new** refresh token in the same family and
invalidates the one you sent.

#### Concurrent refresh rotation (why a race becomes a full revoke)

`RefreshSessionRepository.rotate` locks the target row with `SELECT ... FOR UPDATE` before
touching it. Two requests racing to rotate the *same* token serialize on that lock: the first
succeeds normally; the second unblocks afterward, sees `used_at` already set, and — per the
design — revokes the **entire family**, including the successor the first request just created.
This is deliberate: the server cannot distinguish "a legitimate client's retried request" from
"an attacker who also has this token," so a genuine race is treated exactly like theft. The
practical result is zero-or-one valid successor tokens after a race, never more than one — proven
with 8 real concurrent threads against real PostgreSQL in
`test_concurrent_refresh_rotation_produces_at_most_one_valid_successor`.

An earlier version of `rotate()` had a real bug here, caught only by that real-Postgres test: it
issued the `UPDATE` marking the old token used before flushing the `INSERT` of its replacement,
and real PostgreSQL correctly rejects that as a foreign-key violation (`replaced_by_token_id`
pointing at a row that doesn't exist yet). SQLite doesn't enforce foreign keys by default, so
every SQLite-backed unit test and the TestClient-based smoke tests passed anyway — this is the
same "only a real database catches this" pattern documented elsewhere in this README. Fixed with
an explicit `session.flush()` between the two statements.

### Auth API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Public | Create an account (`role=user`, `status=active`). Returns the user profile, **not** tokens — call `/login` next. 403 if `AUTH_ALLOW_REGISTRATION=false`. |
| POST | `/api/v1/auth/login` | Public | Returns an access+refresh token pair + safe user summary. Generic "invalid email or password" for every failure case — never confirms whether an account exists. |
| POST | `/api/v1/auth/refresh` | Public (requires a valid refresh token) | Rotates a refresh token; see above. |
| POST | `/api/v1/auth/logout` | Public (requires a valid refresh token) | Revokes one session. Idempotent — an unknown/already-revoked token is a silent no-op. |
| POST | `/api/v1/auth/logout-all` | Required | Revokes every refresh session and bumps `token_version`, invalidating all outstanding access tokens too. |
| GET | `/api/v1/auth/me` | Required | Safe profile only — never the password hash. |
| POST | `/api/v1/auth/verify-email` | Public | Consumes a single-use email-verification token. |
| POST | `/api/v1/auth/resend-verification` | Public | Always returns the same generic message — never confirms whether an account exists, is verified, or is disabled. |
| POST | `/api/v1/auth/forgot-password` | Public | Always returns the same generic message. Issues a reset token only for an eligible active account. |
| POST | `/api/v1/auth/reset-password` | Public (requires a valid reset token) | Consumes a single-use token; revokes every session and bumps `token_version` on success. |
| GET | `/api/v1/auth/sessions` | Required | Lists the caller's own active/revoked sessions (safe fields only — no hashes, no raw IP/UA). |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Required | Revokes one of the caller's own sessions. 404 for an unknown or another user's session. |
| DELETE | `/api/v1/auth/sessions` | Required | Revokes every session for the caller — equivalent to `POST /logout-all`. |

See [Distributed rate limiting, email verification, and password reset](#distributed-rate-limiting-email-verification-and-password-reset)
below for the full design behind the last six rows.

### Admin API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/admin/users` | Paginated user list. Excludes the system user. Filter by `role`/`status`. |
| GET | `/api/v1/admin/users/{user_id}` | Single user. 404 for unknown or system users. |
| PATCH | `/api/v1/admin/users/{user_id}/status` | Enable/disable. Disabling revokes all of that user's sessions and bumps `token_version`. |
| PATCH | `/api/v1/admin/users/{user_id}/role` | Change role. Bumps `token_version`. |

Admins cannot change their **own** role or status through these endpoints (403) — there is no
"break glass" self-demotion path; use the CLI or direct DB access if that's ever genuinely needed.
Every admin action (including plain reads of the user list/detail) writes an `audit_events` row
with `actor_user_id` set to the admin.

### Every existing endpoint's auth requirement

| Endpoint | Requirement | Why |
|---|---|---|
| `GET /health` | Public | Trivial liveness check, no cost |
| `GET/POST /api/v1/youtube/...` | Public (unchanged from before this sprint) | Read-mostly, quota-protected at the YouTube-client level already |
| `POST /api/v1/analysis/jobs` | Authenticated | Triggers YouTube collection + ML pipeline + persistence |
| `GET .../jobs`, `.../jobs/{id}`, `.../jobs/{id}/result`, `POST .../cancel` | Authenticated + owner (or admin) | Reads/mutates a specific user's data |
| `GET/POST .../insights*` | Authenticated + owner of the underlying job (or admin) | Triggers local ML and/or paid Gemini/OpenAI calls |
| `/api/v1/auth/*`, `/api/v1/admin/*` | See tables above | |

### Legacy data and the system user

Pre-Sprint-13 `analysis_jobs` rows had no owner. The migration (`a38ecf2dad6f`) does not guess —
it creates one deterministic, fixed-UUID system user
(`00000000-0000-0000-0000-000000000001`, `app/models/user.py:LEGACY_SYSTEM_USER_ID`), assigns
every pre-existing job to it, *then* adds the `NOT NULL`-equivalent ownership expectation going
forward (the column stays nullable at the schema level for flexibility, but application code
always assigns a real owner at creation time). The system user:

- Has an unusable password hash (`!unusable` — not a valid argon2 encoding, so `verify_password`
  always returns `False` against it, never raises).
- Is flagged `is_system_user=True`, which excludes it from `GET /api/v1/admin/users` and from
  `UserRepository.list_users(include_system=False)` (the default) everywhere.
- Is a completely ordinary row otherwise — an admin can still `GET
  /api/v1/admin/users/{that_id}` directly if they already know the id, but it will never appear
  in a listing or be selectable as an "existing user" via search.

### Rate limiting

`app/services/rate_limit.py` now defaults to a **Redis-backed distributed limiter**, coordinating
across every FastAPI process and machine sharing the same Redis instance — see
[Distributed rate limiting, email verification, and password reset](#distributed-rate-limiting-email-verification-and-password-reset)
for the full design, outage policy, and settings. The original bounded in-memory, fixed-window
counter (`InMemoryRateLimiter`) still exists and is used directly when `RATE_LIMIT_BACKEND=memory`
or as the automatic fallback during a Redis outage.

Keys are `(bucket, caller)` where `caller` is the authenticated user's UUID if present, otherwise
an HMAC-SHA256 hash of the client IP keyed by a dedicated pepper (never the raw IP, raw email, or
any JWT/refresh-token material). Returns `429` with a `Retry-After` header.

`AUTH_TRUST_PROXY_HEADERS` (default `false`) controls whether `X-Forwarded-For` is trusted for
the IP-derived key at all; with it `false` (the safe default behind no reverse proxy), the
connecting socket's address is used directly, so a client can't spoof a different rate-limit
bucket by sending a fake header.

Applied to: registration, login, refresh, resend-verification, forgot-password, reset-password,
analysis job creation, insight generation (see the `AUTH_*_RATE_LIMIT_*` /
`ANALYSIS_CREATE_RATE_LIMIT_*` / `INSIGHT_GENERATE_RATE_LIMIT_*` settings below).

### Usage limits (not billing)

Enforced in `AnalysisJobService.create_job`, checked against real persisted state (not the rate
limiter):

- `USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER` (default 3) — counts jobs in a non-terminal status
  (`queued`/`running`/`retrying`) for that user.
- `USAGE_MAX_ANALYSIS_JOBS_PER_DAY` (default 25) — counts jobs created since UTC midnight today.
- `USAGE_MAX_COMMENT_LIMIT_PER_JOB` (default 1000) — a per-user ceiling tighter than or equal to
  the global `ANALYSIS_MAX_COMMENT_LIMIT`; settings validation refuses to start the app if it's
  configured higher than the global limit.

All three raise `UsageLimitExceededError` (429) with a message stating which limit was hit.

### Security headers and CORS

`SecurityHeadersMiddleware` adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, and a conservative `Permissions-Policy`
(denies geolocation/microphone/camera/payment) to every response. `Strict-Transport-Security` is
added **only** when `ENVIRONMENT=production` — sending HSTS over plain-HTTP local development
would be meaningless and potentially confusing on a shared hostname later. No
`Content-Security-Policy` is set: Swagger UI (`/docs`) depends on inline scripts/styles, and a CSP
strict enough to be worth adding would need to be tested against it first — explicitly out of
scope this sprint rather than shipped untested.

CORS (`CORSMiddleware`) is unchanged in behavior but now has a settings-level guard: configuring
`BACKEND_CORS_ORIGINS=["*"]` fails validation at startup, because `main.py` always sets
`allow_credentials=True`, and a wildcard origin combined with credentials is a real browser-level
CORS hole. List explicit origins instead.

No cookie-based auth was added — bearer tokens only, exactly as before this paragraph existed.

### Audit logging

`AuditEvent` (table `audit_events`, JSONB `event_metadata`): `user_id` (nullable — e.g. a failed
login for a nonexistent email has no subject), `actor_user_id` (nullable, set when different from
`user_id` — e.g. an admin acting on someone else), `event_type`, `result`, timestamp. Recorded for:
login success/failure, account lockout, logout, logout-all, refresh-token reuse detection, user
registration, role change, status change, admin cross-user access (including plain reads).
Never contains a password, token, or raw request body — only safe, structured metadata (e.g.
`{"reason": "bad_password"}`, `{"new_role": "admin"}`).

### Secrets

`AUTH_ACCESS_TOKEN_SECRET` and `AUTH_REFRESH_TOKEN_PEPPER` are `SecretStr` — never appear in a
`repr()`, `str()`, log line, or validation error message. Outside `ENVIRONMENT=production`, a
blank value is auto-generated per process start (`secrets.token_urlsafe(64)`) with a startup
warning logged (`auth_secret_auto_generated_development_only`) — convenient for local dev, but it
means **every session is invalidated on restart** since the signing key changes. In production, a
blank value is refused outright at startup. Generate a real one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

A value shorter than 32 characters is rejected regardless of environment.

### Settings reference

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_ACCESS_TOKEN_SECRET` | *(blank — auto-generated outside production)* | HS256 signing key for access tokens |
| `AUTH_ACCESS_TOKEN_ALGORITHM` | `HS256` | Explicit allow-list, not read from the token itself |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `AUTH_REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifetime |
| `AUTH_REFRESH_TOKEN_PEPPER` | *(blank — auto-generated outside production)* | Mixed into the refresh-token hash before storage |
| `AUTH_PASSWORD_MIN_LENGTH` / `AUTH_PASSWORD_MAX_LENGTH` | `10` / `128` | Password policy |
| `AUTH_MAX_FAILED_LOGIN_ATTEMPTS` | `5` | Failures before temporary lockout |
| `AUTH_LOGIN_LOCKOUT_MINUTES` | `15` | Lockout duration |
| `AUTH_REQUIRE_EMAIL_VERIFICATION` | `false` | No email delivery exists this sprint — kept `false` in practice |
| `AUTH_ALLOW_REGISTRATION` | `true` | Kill switch for public signup |
| `AUTH_RATE_LIMIT_ENABLED` | `true` | Global on/off for the rate limiter |
| `AUTH_TRUST_PROXY_HEADERS` | `false` | Only trust `X-Forwarded-For` behind a real reverse proxy |
| `AUTH_LOGIN_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `10` / `60` | Login + refresh attempts |
| `AUTH_REGISTER_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `5` / `3600` | Registration attempts |
| `ANALYSIS_CREATE_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `10` / `60` | Job creation |
| `INSIGHT_GENERATE_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `20` / `60` | Insight generation |
| `USAGE_MAX_ACTIVE_ANALYSIS_JOBS_PER_USER` | `3` | Concurrent non-terminal jobs per user |
| `USAGE_MAX_ANALYSIS_JOBS_PER_DAY` | `25` | Jobs per user per UTC calendar day |
| `USAGE_MAX_COMMENT_LIMIT_PER_JOB` | `1000` | Per-user ceiling, must not exceed `ANALYSIS_MAX_COMMENT_LIMIT` |

Redis, email, verification/reset, session-fingerprint, and notification settings are listed
separately in
[Distributed rate limiting, email verification, and password reset](#distributed-rate-limiting-email-verification-and-password-reset)
below, not repeated in this table.

### First-admin bootstrap

There is no UI for this and no seed data — create the first admin from the CLI:

```powershell
python -m app.cli.create_admin --email admin@example.com
```

Prompts for a password via `getpass` (never echoed, never accepted as a CLI argument — an
argument would land in shell history and process listings). Pass `--promote-existing` to turn an
already-registered account into an admin instead of creating a new one.

### Using Swagger's Authorize button

1. `POST /api/v1/auth/register`, then `POST /api/v1/auth/login` → copy `access_token` from the
   response.
2. Click **Authorize** (top right of `/docs`), paste the token (no `Bearer ` prefix needed —
   Swagger adds it), click **Authorize**, then **Close**.
3. Every subsequent "Try it out" call on a protected endpoint now sends the token automatically.
4. When it expires (15 minutes by default), re-run `/login` (or `/refresh`) and re-Authorize.

### Known limitations

- No OAuth/social login, no organizations/teams, no billing/subscriptions — bearer-token
  username+password auth only, by design.
- Email verification, password reset, distributed rate limiting, session fingerprinting, and the
  session-listing API are covered in
  [Distributed rate limiting, email verification, and password reset](#distributed-rate-limiting-email-verification-and-password-reset)
  below, including their own known limitations.

## Distributed rate limiting, email verification, and password reset

Redis-backed distributed rate limiting, opaque single-use security tokens, email verification,
password recovery, transactional email delivery, session fingerprinting, and a session-management
API — all coordinating across multiple FastAPI processes/machines, which the Sprint 13 in-memory
limiter could not do.

### Redis

`REDIS_ENABLED=true` (default) points at `REDIS_URL` (`redis://localhost:6379/0` locally,
`redis://redis:6379/0` inside Docker Compose). The client (`redis.asyncio`) is created once in
`app/main.py`'s lifespan and stored on `app.state.redis_client` — never a bare module-level
singleton, because `redis.asyncio.Redis` connection pools are bound to the event loop that
created them. A bounded `PING` healthcheck runs at startup and logs `redis_startup_healthcheck`
with the URL's credentials masked (`mask_redis_url`) — never a raw password in a log line.
`REDIS_CONNECT_TIMEOUT_SECONDS` / `REDIS_SOCKET_TIMEOUT_SECONDS` (default 3s each) bound every
Redis round trip. `REDIS_KEY_PREFIX` (default `insightforge`) namespaces every key this
application writes, so a shared Redis instance never collides with another application's keys.

**Redis is never exposed publicly in any deployment**: it has no authentication configured by
default and must stay on a private network/Docker bridge behind the application, exactly like
PostgreSQL.

### Distributed rate limiting

`DistributedRateLimiter` (`app/services/rate_limit.py`) picks a backend per
`RATE_LIMIT_BACKEND` (`redis` default, or `memory`) and applies one of three explicit outage
policies when Redis is configured but a check fails:

1. `RATE_LIMIT_ALLOW_IN_MEMORY_FALLBACK=true` (default) — silently continue enforcing limits
   against the process-local in-memory limiter for the duration of the outage.
2. Otherwise, `RATE_LIMIT_FAIL_OPEN=true` — let the request through unlimited.
3. Otherwise (fail-closed, the strictest option) — reject with `503` (`RateLimitBackendUnavailableError`).

Only known Redis/connection errors (`redis.RedisError`, `TimeoutError`, `OSError`) trigger this
policy — any other exception propagates unchanged, never silently swallowed. Every fallback
triggers a `rate_limit_backend_unavailable` audit event (metadata only: bucket + reason, never a
stack trace or secret).

**Algorithm**: a single atomic Lua script (`register_script`, with redis-py's automatic
EVALSHA/NOSCRIPT retry) does `INCR`, conditionally `EXPIRE` only on the first hit in a window, then
reads `TTL` — one round trip, no race between separate `GET`/`SET`/`EXPIRE` calls, correct under
any number of concurrent callers sharing the same Redis instance across processes or machines
(proven with real concurrent `asyncio.gather` calls against real Docker Redis in
`tests/integration/rate_limit/test_redis_integration.py`).

**Key privacy**: rate-limit keys are never built from a raw IP, email, JWT, or refresh token. An
authenticated caller is keyed by their user UUID; an unauthenticated caller is keyed by an
HMAC-SHA256 hash of the client IP, using a dedicated `RATE_LIMIT_IDENTITY_PEPPER` — a different
secret from the JWT signing key, the refresh-token pepper, and the session-fingerprint pepper.
`AUTH_TRUST_PROXY_HEADERS` still gates whether `X-Forwarded-For` is trusted at all.

Newly rate-limited routes this sprint: `resend-verification`, `forgot-password`, `reset-password`
(settings: `AUTH_RESEND_VERIFICATION_RATE_LIMIT_*`, `AUTH_FORGOT_PASSWORD_RATE_LIMIT_*`,
`AUTH_RESET_PASSWORD_RATE_LIMIT_*`) plus an `ADMIN_MUTATION_RATE_LIMIT_*` bucket reserved for
admin-mutation routes.

### Security tokens (email verification / password reset)

`UserSecurityToken` (table `user_security_tokens`) mirrors the refresh-token design from Sprint
13: the raw token is a `secrets.token_urlsafe(32)` opaque string, **never persisted** — only a
SHA-256 hash of `raw_token + AUTH_SECURITY_TOKEN_PEPPER`. Since Sprint 14.1 this pepper is
**dedicated** — independent from `AUTH_REFRESH_TOKEN_PEPPER` and every other secret in this
project (see [Secret separation](#secret-separation) below); a compromise of one pepper can no
longer be used to forge or brute-force the other class of token. Columns: `user_id` (FK,
`ON DELETE CASCADE`), `purpose` (`email_verification` / `password_reset`), unique/indexed
`token_hash`, `issued_at` / `expires_at` / `used_at` / `revoked_at`, `created_by_ip_hash` /
`user_agent_hash`.

Consumption (`SecurityTokenRepository.consume`) is atomic — `SELECT ... FOR UPDATE`, then a single
transaction validates purpose/revoked/used/expired and marks it used, exactly like
`RefreshSessionRepository.rotate`. A second concurrent attempt with the same raw token blocks on
the row lock, then observes `used_at` already set — proven with 8 real concurrent threads against
real Postgres (`test_concurrent_consume_of_same_token_succeeds_at_most_once`). Issuing a
replacement token for the same user/purpose revokes every prior active one first. Reuse of an
already-consumed token records a `security_token_reuse` audit event with only the purpose and a
safe reason code as metadata — never the raw token, its hash, or any request content.

#### Secret separation

Five independent secrets exist in this project, each used for exactly one purpose:
`AUTH_ACCESS_TOKEN_SECRET` (JWT signing), `AUTH_REFRESH_TOKEN_PEPPER` (refresh-token hashing),
`AUTH_SECURITY_TOKEN_PEPPER` (verification/reset-token hashing), `RATE_LIMIT_IDENTITY_PEPPER`
(anonymous rate-limit identity hashing), and `AUTH_SESSION_FINGERPRINT_PEPPER` (session IP/UA
fingerprinting). `Settings._validate_secret_separation` rejects any two of these five that are
configured to the exact same value, in every environment — not just production. Only *explicitly
configured* values are compared: two independently auto-generated development secrets are never
flagged, since a random collision between two 64-byte `token_urlsafe` values is not a real
misconfiguration.

#### Pre-Sprint-14.1 token cutover

Migration `a4009c4d83f6` bulk-revokes every currently active, unused `user_security_tokens` row at
upgrade time. This is necessary because rehashing existing rows without their original raw tokens
(never persisted, by design) is impossible, and every such row was hashed under the old
`AUTH_REFRESH_TOKEN_PEPPER` — once the pepper switch above lands, `SecurityTokenRepository.consume`
recomputes the lookup hash with the new `AUTH_SECURITY_TOKEN_PEPPER` and will never match those old
rows anyway. The migration makes this explicit (a clean audit trail, not silently-dead rows that
still look active) rather than changing any actual runtime behavior. **Practical consequence: any
verification or password-reset link sent before this migration is applied stops working — affected
users must request a new one** (`POST /resend-verification` or `POST /forgot-password`). Already
-consumed and already-expired rows are left untouched; users, refresh sessions, audit events, and
the email outbox are not touched by this migration at all.

### Email verification

`POST /api/v1/auth/verify-email` / `POST /api/v1/auth/resend-verification`. When
`AUTH_REQUIRE_EMAIL_VERIFICATION=true` (default `false`), registration creates an active-but-
unverified user, issues a verification token, and enqueues an email — login is rejected with
`403` (`EmailNotVerifiedError`) until verified. `resend-verification` always returns the same
generic message regardless of whether the account exists, is already verified, is disabled, or is
the system user, and additionally enforces a per-account cooldown
(`AUTH_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS`, default 300s) on top of the IP rate limit — the
rate limiter stops a burst from one network origin, the cooldown stops the same victim's inbox
being spammed from many different IPs. Token lifetime: `AUTH_EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES`
(default 30).

### Password recovery

`POST /api/v1/auth/forgot-password` / `POST /api/v1/auth/reset-password`. `forgot-password` always
returns the same generic message and only issues a token for an eligible (active, non-system)
account. `reset-password` validates the new password against policy **before** consuming the
token — so a rejected password never burns the caller's single-use link — then atomically consumes
it, hashes the new password, revokes every refresh session, and increments `token_version`
(immediately invalidating every outstanding access token, same guarantee as `logout-all`). Token
lifetime: `AUTH_PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` (default 20).

### Email delivery

`EmailSender` (`app/services/email/sender.py`) is a small abstraction with three implementations:
`FakeEmailSender` (records messages in memory — used by every test), `SMTPEmailSender` (stdlib
`smtplib` wrapped in `asyncio.to_thread` so a blocking library never blocks the event loop), and
`ConsoleEmailSender` (prints instead of sending — explicitly forbidden in production unless
overridden; `EMAIL_BACKEND=console` fails settings validation when `ENVIRONMENT=production`).
Recipient/subject headers are CRLF-sanitized before being placed in a MIME message, closing a
header-injection path.

**Locally, prefer [Mailpit](https://github.com/axllent/mailpit)** — a real SMTP server with a web
UI, no external network call, no risk of sending a real email during development:

```powershell
docker compose -f ..\docker\docker-compose.yml up -d mailpit
```

- SMTP: `localhost:1025` (already the `EMAIL_SMTP_HOST`/`EMAIL_SMTP_PORT` defaults)
- Web UI: `http://localhost:8025` — every verification/reset/notification email sent locally
  appears here, viewable without ever touching a real inbox.

### Email outbox and worker

Rather than a blocking SMTP call inline in a request, emails are enqueued as `EmailOutboxEntry`
rows (table `email_outbox`: `recipient`, `template`, JSONB `payload`, `status`, `attempt_count`/
`max_attempts`, `available_at`, `last_error_code`, `sent_at`) and dispatched by a **dedicated**
worker — never the analysis worker:

```powershell
python -m app.workers.email_worker
```

Claiming (`EmailOutboxRepository.claim_next_pending`) uses the same atomic
`SELECT ... FOR UPDATE SKIP LOCKED` + lease pattern as `AnalysisJobRepository.claim_next_job`: the
row is locked, marked `sending` with `available_at` pushed forward by a lease, and the transaction
commits **immediately** — so the lock is never held across the actual SMTP round trip. A row stuck
in `sending` past its lease (worker crash mid-send) becomes reclaimable once `available_at`
passes. Proven with 10 real concurrent claimers against real Postgres never double-claiming the
same row (`test_concurrent_claim_next_pending_never_double_claims`).

Failed sends retry with exponential backoff (`EMAIL_OUTBOX_RETRY_BASE_DELAY_SECONDS` doubling up
to `EMAIL_OUTBOX_RETRY_MAX_DELAY_SECONDS`) up to `EMAIL_OUTBOX_MAX_ATTEMPTS`, then become
terminally `failed`. On success **or** terminal failure, the payload is scrubbed to
`{"template": ..., "delivered": bool}` — the tokenized link is only ever persisted transiently
until delivery is resolved one way or the other. A delivery failure never undoes an
already-completed token consumption, password reset, or email verification — those already
committed before the email was even enqueued.

**Retention (verified, Sprint 14.1 review)**: a tokenized link exists in `payload` only for the
window between enqueue and resolution (`sent` or terminally `failed`) — confirmed by
`test_dispatch_one_scrubs_payload_after_success` and the outbox integration suite. Resolved rows
are kept indefinitely (no automatic deletion job exists), but their payload no longer contains a
usable link by the time they reach a terminal state, and audit metadata for both
`email_delivery_succeeded`/`email_delivery_failed` events was confirmed to carry only
`template`/`attempt` — never the link or token.

### Frontend links

`FRONTEND_PUBLIC_URL` (default `http://localhost:5173`) + `AUTH_EMAIL_VERIFICATION_PATH` /
`AUTH_PASSWORD_RESET_PATH` build the links embedded in verification/reset emails, always
server-side with the token URL-encoded — clients can never supply an arbitrary redirect target.
Production requires `https://` and rejects `localhost`/`127.0.0.1`.

### Session fingerprinting

`app/utils/fingerprint.py` computes HMAC-SHA256 hashes of the client IP and (length-capped)
User-Agent, keyed by a dedicated `AUTH_SESSION_FINGERPRINT_PEPPER` — never the same secret as JWT
signing, refresh-token hashing, or rate-limit identity. Populated on every login (`created_by_ip_hash`,
`user_agent_hash`) and updated on every refresh rotation (`last_used_ip_hash`, `last_used_at`).
This is informational/anomaly metadata only — it never gates authentication and never triggers an
automatic lockout on IP/UA change.

### Session API

`GET/DELETE /api/v1/auth/sessions[/{id}]` (see the Auth API table above). Listings expose only
safe fields (`id`, `issued_at`, `expires_at`, `last_used_at`, `is_current`, `revoked`) — never a
token hash, fingerprint, or rotation lineage. Since Sprint 14.1, `is_current` is an **exact match**
against the `sid` claim of the access token used to call this endpoint (see below) — not a
heuristic. An access token issued before Sprint 14.1 carries no `sid` at all, so it always reports
`is_current=false` for every session in the list: it remains valid and usable until its normal
expiry, it simply can no longer be matched to one exact session.

#### Session-aware access-token validation

Every access token minted at login or refresh time now carries a `sid` claim: the id of the
refresh session it was issued alongside (`JWTService.create_access_token`'s optional
`session_id` parameter). `get_optional_current_user` (`app/api/deps_auth.py`) checks it on every
authenticated request: if `sid` is present, it looks up that exact refresh session by primary key
(`RefreshSessionRepository.get_by_id_for_user` — a single indexed lookup, not a scan, and not a
blacklist table) and rejects the request (401) if that session is revoked, expired, or no longer
belongs to the caller. **Practical effect: revoking a single session now immediately invalidates
its access token too**, closing the Sprint 14 limitation where a revoked session's already-issued
access token kept working until its own short expiry.

Tokens without `sid` (anything issued before this sprint, or any token a caller might present from
an older client) skip this check entirely and remain governed exactly as before: `token_version`
and normal expiry only. This costs nothing extra for those tokens and never breaks a legitimate
in-flight session — it only tightens revocation for tokens minted after the change. `DELETE
/sessions` (revoke-all) and `logout-all` continue to also bump `token_version`, which invalidates
every outstanding access token immediately regardless of whether it carries a `sid`.

### Security notifications

Optional, best-effort email notifications, each independently toggled and defaulting to the safer
choice: `AUTH_NOTIFY_ON_PASSWORD_CHANGE=true`, `AUTH_NOTIFY_ON_NEW_LOGIN=false`,
`AUTH_NOTIFY_ON_REFRESH_REPLAY=true`. Never include a token or password. Never sent to the system
user. A notification failure is logged and never propagates — it cannot expose account state or
block the security operation (password reset, login, replay revocation) that triggered it.

### Audit additions

New `AuditEventType` values this sprint: `email_verification_requested`, `email_verified`,
`password_reset_requested`, `password_reset_completed`, `security_token_reuse`, `session_listed`,
`session_revoked`, `email_delivery_succeeded`, `email_delivery_failed`,
`rate_limit_backend_unavailable`. Metadata is always safe/structured — never a raw token, hash,
password, email body, `Authorization` header, or raw IP/UA.

### Settings reference (Sprint 14)

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_ENABLED` | `true` | Master switch for the Redis client/backend |
| `REDIS_URL` | `redis://localhost:6379/0` | Connection string (`redis://redis:6379/0` inside Docker) |
| `REDIS_CONNECT_TIMEOUT_SECONDS` / `REDIS_SOCKET_TIMEOUT_SECONDS` | `3` / `3` | Bounded connection/operation timeouts |
| `REDIS_KEY_PREFIX` | `insightforge` | Namespaces every key this app writes |
| `RATE_LIMIT_BACKEND` | `redis` | `redis` or `memory` |
| `RATE_LIMIT_ALLOW_IN_MEMORY_FALLBACK` | `true` | Fall back to in-memory limiting during a Redis outage |
| `RATE_LIMIT_FAIL_OPEN` | `false` | If fallback is off, allow requests through unlimited during an outage instead of `503` |
| `RATE_LIMIT_IDENTITY_PEPPER` | *(blank — auto-generated in development only)* | HMACs the unauthenticated rate-limit IP key. Required outside development whenever `RATE_LIMIT_BACKEND=redis` (see [Multi-instance deployments](#multi-instance-deployments)) |
| `AUTH_SECURITY_TOKEN_PEPPER` | *(blank — auto-generated outside production)* | Hashes email-verification/password-reset tokens (Sprint 14.1) — dedicated, independent from `AUTH_REFRESH_TOKEN_PEPPER` |
| `AUTH_RESEND_VERIFICATION_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `3` / `3600` | Resend-verification attempts |
| `AUTH_FORGOT_PASSWORD_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `3` / `3600` | Forgot-password attempts |
| `AUTH_RESET_PASSWORD_RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `5` / `3600` | Reset-password attempts |
| `AUTH_EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES` | `30` | Verification token lifetime |
| `AUTH_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS` | `300` | Per-account resend cooldown |
| `AUTH_PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` | `20` | Reset token lifetime |
| `AUTH_SESSION_FINGERPRINT_PEPPER` | *(blank — auto-generated outside production)* | HMACs session IP/UA fingerprints |
| `AUTH_SESSION_USER_AGENT_MAX_LENGTH` | `512` | Caps stored User-Agent length before hashing |
| `AUTH_NOTIFY_ON_PASSWORD_CHANGE` / `AUTH_NOTIFY_ON_NEW_LOGIN` / `AUTH_NOTIFY_ON_REFRESH_REPLAY` | `true` / `false` / `true` | Security notification toggles |
| `EMAIL_BACKEND` | `smtp` | `smtp` or `console` (console forbidden in production) |
| `EMAIL_FROM_ADDRESS` / `EMAIL_FROM_NAME` | `no-reply@insightforge.local` / `InsightForge AI` | Sender identity |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` | `localhost` / `1025` | Defaults match local Mailpit |
| `EMAIL_SMTP_USERNAME` / `EMAIL_SMTP_PASSWORD` | blank / blank (`SecretStr`) | SMTP auth, unused against Mailpit |
| `EMAIL_SMTP_USE_TLS` | `false` | STARTTLS toggle |
| `EMAIL_SMTP_TIMEOUT_SECONDS` | `10` | Bounded SMTP round trip |
| `EMAIL_OUTBOX_WORKER_POLL_INTERVAL_SECONDS` | `3` | Idle poll interval |
| `EMAIL_OUTBOX_MAX_ATTEMPTS` | `5` | Attempts before terminal failure |
| `EMAIL_OUTBOX_RETRY_BASE_DELAY_SECONDS` / `_MAX_DELAY_SECONDS` | `30` / `900` | Exponential backoff bounds |
| `FRONTEND_PUBLIC_URL` | `http://localhost:5173` | Base URL for verification/reset links |
| `AUTH_EMAIL_VERIFICATION_PATH` / `AUTH_PASSWORD_RESET_PATH` | `/verify-email` / `/reset-password` | Frontend route paths appended to the base URL |

### Running the email worker locally

Alongside the FastAPI process and the analysis worker (see
[Running the worker locally](#running-the-worker-locally)), start Redis, Mailpit, and the email
worker:

```powershell
docker compose -f ..\docker\docker-compose.yml up -d db redis mailpit
```

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -m app.workers.email_worker
```

Open `http://localhost:8025` to watch verification/reset/notification emails arrive as they're
dispatched.

### Development vs. production

Outside `ENVIRONMENT=production`, `RATE_LIMIT_IDENTITY_PEPPER`, `AUTH_SESSION_FINGERPRINT_PEPPER`,
and `AUTH_SECURITY_TOKEN_PEPPER` auto-generate per process start (with a logged warning) exactly
like the Sprint 13 JWT/refresh-token secrets — convenient locally, but every session's rate-limit
bucket, fingerprint identity, and outstanding verification/reset tokens are invalidated on
restart. In production, all five secrets (`AUTH_ACCESS_TOKEN_SECRET`, `AUTH_REFRESH_TOKEN_PEPPER`,
`AUTH_SECURITY_TOKEN_PEPPER`, `RATE_LIMIT_IDENTITY_PEPPER`, `AUTH_SESSION_FINGERPRINT_PEPPER`) are
required, must be ≥32 characters, and must be pairwise distinct (see
[Secret separation](#secret-separation) above). `EMAIL_BACKEND=console` and a
`localhost`/wildcard `FRONTEND_PUBLIC_URL` are both refused at startup in production.

#### Multi-instance deployments

**Every FastAPI instance in a horizontally-scaled deployment must be configured with the exact
same `RATE_LIMIT_IDENTITY_PEPPER` and `AUTH_SESSION_FINGERPRINT_PEPPER` values.** An
auto-generated pepper is process-local by construction — two processes that both auto-generate
will hash the identical client IP to two different digests, silently splitting what should be one
shared Redis-backed rate-limit bucket into as many buckets as there are processes (each
effectively getting its own private limit). Sprint 14 documented this as a known limitation;
Sprint 14.1 makes it fail loudly instead: outside `ENVIRONMENT=development`, a blank
`RATE_LIMIT_IDENTITY_PEPPER` refuses to start at all whenever `RATE_LIMIT_BACKEND=redis` (the
default) — not only in `ENVIRONMENT=production`. Configure both peppers explicitly, from the same
value, on every instance before deploying more than one process.

### Known limitations (Sprint 14 / 14.1)

- No admin API generates or reissues verification/reset tokens on a user's behalf — only the
  user-facing flows above create them.
- `is_current` in the session list depends on the presented access token carrying a `sid` claim
  (every token minted since Sprint 14.1). A pre-14.1 token still works but always reports
  `is_current=false` for every session — it cannot be exactly matched retroactively.
- Email-address change is out of scope — only verification of the address supplied at
  registration.
- No Celery/Redis task queue was introduced — Redis is used only for rate limiting; the email
  outbox remains a PostgreSQL-backed, worker-polled queue, consistent with the analysis-job
  architecture.
- Sent/failed `email_outbox` rows are retained indefinitely with their payload already scrubbed
  (see below) — there is no automatic deletion job for resolved rows yet; this is a storage/
  housekeeping concern, not a security exposure, since no raw token survives past resolution.

## Running tests

```powershell
python -m pytest --collect-only -q
python -m pytest
```

Tests use mocks, fakes (`FakeEmailSender`, `FakeSourceConnector`, `FakeImportFileStorage`, a
hand-rolled fake async Redis client), and an in-memory SQLite database — no live PostgreSQL,
Redis, SMTP server, network access, YouTube API key, or model download is required to run the
default suite. Connector and multi-source-domain unit tests live in `tests/unit/connectors/`,
`tests/unit/source/`, and `tests/unit/test_architecture_boundaries.py` (the last of these
statically verifies, via AST import parsing and a subprocess-isolated fresh-import check, that
generic modules never import YouTube-specific ones and that importing the app never eagerly loads
torch/transformers). File-import parsing/mapping/storage/service/API tests live in
`tests/unit/imports/` and `tests/unit/connectors/test_file_import_connector.py`. A separate,
opt-in integration suite (`tests/integration/`) proves things SQLite/fakes cannot — real row
locking, real foreign-key enforcement, real concurrent races, real Lua-script atomicity, real TTL
expiry, (`tests/integration/source/test_source_domain_postgres.py`) real dataset/record
uniqueness, JSONB round-trips, checkpoint row-locking, and cascade deletes, and
(`tests/integration/imports/`) real file-import cascades, concurrent idempotent `start()`,
concurrent `SourceRecord` upserts, row-error caps, and real local-filesystem storage (interrupted
writes, path-traversal, retention cleanup), and (`tests/integration/signals/`) real signal/
signal-evidence uniqueness constraints, JSONB round-trips, cascade deletes, and concurrent upsert
races — and skips cleanly (not fails) per-file if its backend isn't reachable:

```powershell
docker compose -f ..\docker\docker-compose.yml up -d db redis
python -m pytest tests/integration/ -v
```

## Ruff and Black

```powershell
python -m ruff check .
python -m black --check .
```

Drop `--check` from the Black command to auto-format.

## Stopping services

Stop `uvicorn` and any workers (`analysis_worker` / `email_worker`) with `Ctrl+C` in their
terminals.

Stop PostgreSQL, Redis, and Mailpit:

```powershell
docker compose -f ..\docker\docker-compose.yml stop db redis mailpit
```

Or remove the containers entirely (PostgreSQL/Redis data is kept in their named volumes; Mailpit's
inbox is not):

```powershell
docker compose -f ..\docker\docker-compose.yml down
```

## Troubleshooting

**Database connection refused**
- Confirm the container is running: `docker ps` (look for a `db` container).
- Check its health: `docker inspect --format "{{.State.Health.Status}}" docker-db-1`.
- Confirm `DATABASE_URL` in `backend/.env` matches your setup (`localhost`, not `db`, if
  PostgreSQL runs in Docker but FastAPI runs on your machine).
- Make sure migrations have been applied: `python -m alembic upgrade head`.

**401 / 403 / YouTube authentication failure**
- Verify `YOUTUBE_API_KEY` in `backend/.env` is correct.
- Confirm the YouTube Data API v3 is enabled for that key in Google Cloud Console.
- Check any API key restrictions (IP, referrer) permit this usage.

**Quota exceeded**
- This is a real YouTube API quota limit, not a bug. Wait for your quota to reset or request a
  higher quota from Google — do not attempt to bypass it.

**Sentiment service unavailable (503)**
- Check your internet connection (needed for the first model download).
- Check Hugging Face's status if downloads are failing.
- Check free disk space and available RAM.
- Restart `uvicorn` after fixing the underlying issue.

**CUDA requested but unavailable**
- Set `SENTIMENT_DEVICE=cpu` or `SENTIMENT_DEVICE=auto` in `backend/.env`. The application does
  not silently fall back from an explicit `cuda` setting — you must change the configuration.

**Model inference feels slow**
- This is expected on CPU inference, especially for the first request per language route (model
  loading). Subsequent requests reusing an already-loaded model are faster while the process
  stays alive.

**Port 8000 already in use**
- Find what's using it, or start on a different port:
  ```powershell
  python -m uvicorn app.main:app --reload --port 8001
  ```

**Redis unavailable / rate-limit-related 503s**
- Confirm the container is running and healthy: `docker ps` / `docker inspect --format
  "{{.State.Health.Status}}" docker-redis-1`.
- Check `REDIS_URL` in `backend/.env` matches your setup (`localhost`, not `redis`, if Redis runs
  in Docker but FastAPI runs on your machine).
- A `503` from an authenticated/rate-limited route with `rate_limit_backend_unavailable` in the
  logs means Redis is down **and** both `RATE_LIMIT_ALLOW_IN_MEMORY_FALLBACK` and
  `RATE_LIMIT_FAIL_OPEN` are `false` (fail-closed) — this is working as configured, not a bug.

**Verification/reset emails never arrive**
- Confirm Mailpit is running: `docker ps` (look for a `mailpit` container), then open
  `http://localhost:8025` — every email sent locally appears there, never in a real inbox.
- Confirm the email worker is running: `python -m app.workers.email_worker`. Nothing dispatches
  outbox rows without it.
- Check `email_outbox.status`/`last_error_code` directly in PostgreSQL if an email is stuck
  `pending`/`sending` past its expected delivery time.

**Migration mismatch / unexpected schema state**
```powershell
python -m alembic current
python -m alembic history
python -m alembic upgrade head
```

### Developer verification: downgrading (not for normal use)

Normal setup only ever needs `alembic upgrade head`. If you're verifying migration correctness:

```powershell
python -m alembic downgrade -1
python -m alembic upgrade head
```
