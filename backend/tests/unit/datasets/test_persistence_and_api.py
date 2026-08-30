"""Persistence, job integration and the read API, over a real (SQLite)
database and a real FastAPI client.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import StaticPool

from app.api.deps import get_import_storage
from app.api.deps_auth import get_current_active_user
from app.database.base import Base
from app.database.session import get_db
from app.datasets.engine import analyze_dataset
from app.datasets.serialization import analysis_to_persisted_fields
from app.imports.storage import FakeImportFileStorage
from app.main import app
from app.models.analysis_job import AnalysisJob
from app.models.enums import (
    CollectionMode,
    JobStatus,
    SourceType,
    UserRole,
    UserStatus,
)
from app.models.source import SourceDataset
from app.models.user import User
from app.repositories.dataset_analysis import DatasetAnalysisRepository
from app.services.analysis_job.dataset_runner import is_dataset_intelligence_dataset

from .conftest import csv_source, dates, keyword_analyzer, write_csv

TEST_USER_ID = uuid.uuid4()
_TEST_USER = User(
    id=TEST_USER_ID,
    email="dataset-test@example.com",
    password_hash="!unusable",
    role=UserRole.user,
    status=UserStatus.active,
)
_OTHER_USER = User(
    id=uuid.uuid4(),
    email="dataset-other@example.com",
    password_hash="!unusable",
    role=UserRole.user,
    status=UserStatus.active,
)

CSV_CONTENT = b"customer_id,age,country,plan,monthly_spend,feedback,created_at\n" + b"".join(
    (
        f"{1000 + index},{20 + index % 40},"
        f"{['US', 'UK', 'DE'][index % 3]},"
        f"{['free', 'pro', 'enterprise'][index % 3]},"
        f"{[0, 49, 240][index % 3]},"
        f"\"{['The dashboard is genuinely useful to me every day', 'Terrible support, nobody replied for days', 'Please add a dark mode and CSV export soon'][index % 3]}\","
        f"2024-{(index % 12) + 1:02d}-01\n"
    ).encode()
    for index in range(60)
)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine, session_factory):
    storage = FakeImportFileStorage()

    def _override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: _TEST_USER
    app.dependency_overrides[get_import_storage] = lambda: storage
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_user(db, user: User) -> User:
    existing = db.get(User, user.id)
    if existing is not None:
        return existing
    clone = User(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        role=user.role,
        status=user.status,
    )
    db.add(clone)
    db.commit()
    return clone


def _seed_analysis(db, tmp_path, settings, config, owner: User = _TEST_USER) -> AnalysisJob:
    """A completed dataset job with a real, engine-produced analysis behind
    it -- not a hand-written fixture, so what the API serves is exactly what
    the engine persists."""
    _seed_user(db, owner)

    dataset = SourceDataset(
        user_id=owner.id,
        source_type=SourceType.file_import,
        external_id=str(uuid.uuid4()),
        dataset_type="custom_feedback",
        display_name="customers.csv",
        dataset_metadata={"analysis_mode": "dataset"},
    )
    db.add(dataset)
    db.commit()

    job = AnalysisJob(
        user_id=owner.id,
        source_type=SourceType.file_import,
        source_reference=str(dataset.external_id),
        source_dataset_id=dataset.id,
        collection_mode=CollectionMode.bounded,
        requested_comment_limit=1000,
        max_attempts=3,
        status=JobStatus.completed,
    )
    db.add(job)
    db.commit()

    rows = []
    for index, day in enumerate(dates(60)):
        plan = ["free", "pro", "enterprise"][index % 3]
        rows.append(
            [
                1000 + index,
                20 + index % 40,
                ["US", "UK", "DE"][index % 3],
                plan,
                {"free": 0, "pro": 49, "enterprise": 240}[plan],
                [
                    "The dashboard is genuinely useful to me every single day",
                    "Terrible support experience, nobody replied for three days",
                    "Please add a dark mode and a CSV export to the reports page",
                ][index % 3],
                day,
            ]
        )
    path = write_csv(
        tmp_path / "seed.csv",
        ["customer_id", "age", "country", "plan", "monthly_spend", "feedback", "created_at"],
        rows,
    )
    analysis = analyze_dataset(csv_source(path, settings), config, text_analyzer=keyword_analyzer)
    fields = analysis_to_persisted_fields(analysis)
    fields["dataset_id"] = dataset.id
    DatasetAnalysisRepository(db).upsert(job.id, fields)
    return job


# --------------------------------------------------------- persistence


def test_analysis_persists_and_reloads_without_recomputation(db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    repository = DatasetAnalysisRepository(db)

    stored = repository.get(job.id)
    assert stored is not None
    assert stored.row_count == 60
    assert stored.column_count == 7
    assert stored.health_score > 0
    assert stored.overview_json["file_name"] == "seed.csv"
    assert stored.columns_json["columns"]
    assert stored.charts_json["charts"]
    assert stored.insights_json["insights"]


def test_summary_read_omits_the_large_sections(db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    summary = DatasetAnalysisRepository(db).get_summary(job.id)
    assert summary is not None
    assert summary.row_count == 60
    assert summary.health_score > 0


def test_upsert_is_idempotent_for_a_retried_job(db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    repository = DatasetAnalysisRepository(db)
    repository.upsert(job.id, {"row_count": 99, "health_score": 42})
    stored = repository.get(job.id)
    assert stored.row_count == 99
    assert stored.health_score == 42
    assert repository.get_summaries_for_jobs([job.id])[job.id].row_count == 99


def test_dataset_mode_marker_is_read_from_the_dataset(db):
    _seed_user(db, _TEST_USER)
    plain = SourceDataset(
        user_id=_TEST_USER.id,
        source_type=SourceType.file_import,
        external_id="a",
        dataset_type="custom_feedback",
        display_name="a",
        dataset_metadata={},
    )
    marked = SourceDataset(
        user_id=_TEST_USER.id,
        source_type=SourceType.file_import,
        external_id="b",
        dataset_type="custom_feedback",
        display_name="b",
        dataset_metadata={"analysis_mode": "dataset"},
    )
    assert is_dataset_intelligence_dataset(plain) is False
    assert is_dataset_intelligence_dataset(marked) is True
    assert is_dataset_intelligence_dataset(None) is False


# ----------------------------------------------------------------- API


def test_overview_endpoint_returns_a_complete_summary(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    response = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset")
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["row_count"] == 60
    assert body["summary"]["column_count"] == 7
    assert body["overview"]["file_name"] == "seed.csv"
    assert body["coverage"]["total_rows"] == 60
    assert body["quality_summary"]["health_score"] == body["summary"]["health_score"]
    assert body["executive_summary"]["scope"]
    assert len(body["strongest_findings"]) <= 3
    assert set(body["capabilities"]) == {
        "has_quality_issues",
        "has_numeric_columns",
        "has_relationships",
        "has_temporal",
        "has_text",
        "has_ai_insights",
    }
    # The Overview payload must not carry the sections that have their own
    # endpoints.
    assert "columns" not in body
    assert all(chart["section"] in ("overview", "quality") for chart in body["charts"])


def test_columns_endpoint_paginates_and_searches(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)

    page = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/columns?limit=3&offset=0").json()
    assert page["total"] == 7
    assert len(page["columns"]) == 3
    assert page["columns"][0]["name"] == "customer_id"
    assert page["columns"][0]["semantic_role"]
    assert page["columns"][0]["role_reason"]

    second = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/columns?limit=3&offset=3").json()
    assert second["columns"][0]["name"] != page["columns"][0]["name"]

    search = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/columns?search=feedback").json()
    assert [column["name"] for column in search["columns"]] == ["feedback"]


def test_quality_endpoint_returns_issues_and_recommendations(
    client, db, tmp_path, settings, config
):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/quality").json()
    assert "health_score" in body["quality"]
    assert "scoring_rules" in body["quality"]
    assert isinstance(body["cleaning"], list)
    for issue in body["quality"]["issues"]:
        assert issue["explanation"]
        assert issue["recommendation"]


def test_relationships_endpoint_carries_the_disclaimer(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/relationships").json()
    assert "does not show that one causes the other" in body["relationships"]["disclaimer"]


def test_trends_endpoint(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/trends").json()
    assert body["temporal"]["analyzable"] is True
    assert body["temporal"]["series"]


def test_text_endpoint(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/text").json()
    assert body["text"]["analyzable"] is True
    assert body["text"]["columns"][0]["column"] == "feedback"


def test_insights_endpoint_returns_grounded_insights(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/insights").json()
    fact_ids = {fact["fact_id"] for fact in body["facts"]}
    assert body["insights"]
    for insight in body["insights"]:
        assert insight["evidence_fact_ids"]
        assert set(insight["evidence_fact_ids"]) <= fact_ids
        assert insight["title"]
        assert insight["explanation"]
        assert insight["impact"]


def test_preview_endpoint_is_bounded(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/preview").json()
    assert len(body["rows"]) <= config.preview_rows
    assert body["columns"]
    assert body["note"]


def test_missing_analysis_is_a_404(client, db, tmp_path, settings, config):
    _seed_user(db, _TEST_USER)
    job = AnalysisJob(
        user_id=_TEST_USER.id,
        source_type=SourceType.youtube,
        source_reference="abc",
        collection_mode=CollectionMode.bounded,
        requested_comment_limit=100,
        max_attempts=3,
        status=JobStatus.completed,
    )
    db.add(job)
    db.commit()
    assert client.get(f"/api/v1/analysis/jobs/{job.id}/dataset").status_code == 404


def test_unknown_job_is_a_404(client):
    assert client.get(f"/api/v1/analysis/jobs/{uuid.uuid4()}/dataset").status_code == 404


def test_another_users_analysis_is_a_404(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config, owner=_OTHER_USER)
    assert client.get(f"/api/v1/analysis/jobs/{job.id}/dataset").status_code == 404


# ------------------------------------------------- upload + configure


def _upload(client, content: bytes = CSV_CONTENT, filename: str = "customers.csv"):
    return client.post(
        "/api/v1/sources/imports",
        files={"file": (filename, io.BytesIO(content), "text/csv")},
    )


def test_upload_reports_dataset_analysis_support(client):
    body = _upload(client).json()
    assert body["dataset_analysis_supported"] is True


def test_json_upload_is_not_offered_dataset_analysis(client):
    body = client.post(
        "/api/v1/sources/imports",
        files={"file": ("data.json", io.BytesIO(b'[{"a": 1}]'), "application/json")},
    ).json()
    assert body["dataset_analysis_supported"] is False


def test_configure_for_dataset_mode_needs_no_column_mapping(client):
    import_id = _upload(client).json()["import_id"]
    response = client.post(
        f"/api/v1/sources/imports/{import_id}/configure",
        json={
            "dataset_title": "Customers",
            "dataset_type": "custom_feedback",
            "analysis_mode": "dataset",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_mode"] == "dataset"
    assert body["status"] == "ready"
    assert body["mapping"] is None


def test_configure_for_record_mode_still_requires_a_mapping(client):
    import_id = _upload(client).json()["import_id"]
    response = client.post(
        f"/api/v1/sources/imports/{import_id}/configure",
        json={
            "dataset_title": "Customers",
            "dataset_type": "custom_feedback",
            "analysis_mode": "records",
        },
    )
    assert response.status_code == 409

    ok = client.post(
        f"/api/v1/sources/imports/{import_id}/configure",
        json={
            "dataset_title": "Customers",
            "dataset_type": "custom_feedback",
            "analysis_mode": "records",
            "mapping": {"text_column": "feedback"},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["analysis_mode"] == "records"


def test_dataset_mode_is_refused_for_json(client):
    import_id = client.post(
        "/api/v1/sources/imports",
        files={"file": ("data.json", io.BytesIO(b'[{"a": 1, "b": "x"}]'), "application/json")},
    ).json()["import_id"]
    response = client.post(
        f"/api/v1/sources/imports/{import_id}/configure",
        json={
            "dataset_title": "Data",
            "dataset_type": "custom_feedback",
            "analysis_mode": "dataset",
        },
    )
    assert response.status_code == 400
    assert "CSV, XLSX" in response.json()["error"]["message"]


def test_dataset_mode_is_refused_when_the_feature_is_disabled(db_engine, session_factory):
    """DATASET_INTELLIGENCE_ENABLED is a real switch, not a documented
    constant: with it off the upload stops advertising dataset analysis and
    the configure endpoint refuses the mode."""
    from app.api.deps import get_settings
    from app.config.settings import Settings

    disabled = Settings(DATASET_INTELLIGENCE_ENABLED=False)
    storage = FakeImportFileStorage()

    def _override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: _TEST_USER
    app.dependency_overrides[get_import_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: disabled
    try:
        client = TestClient(app)
        upload = client.post(
            "/api/v1/sources/imports",
            files={"file": ("customers.csv", io.BytesIO(CSV_CONTENT), "text/csv")},
        ).json()
        assert upload["dataset_analysis_supported"] is False

        response = client.post(
            f"/api/v1/sources/imports/{upload['import_id']}/configure",
            json={
                "dataset_title": "Customers",
                "dataset_type": "custom_feedback",
                "analysis_mode": "dataset",
            },
        )
        assert response.status_code == 403
        assert "disabled" in response.json()["error"]["message"].lower()
    finally:
        app.dependency_overrides.clear()


def test_start_marks_the_dataset_for_the_engine(client, db):
    import_id = _upload(client).json()["import_id"]
    client.post(
        f"/api/v1/sources/imports/{import_id}/configure",
        json={
            "dataset_title": "Customers",
            "dataset_type": "custom_feedback",
            "analysis_mode": "dataset",
        },
    )
    started = client.post(f"/api/v1/sources/imports/{import_id}/start", json={})
    assert started.status_code == 202

    detail = client.get(f"/api/v1/sources/imports/{import_id}").json()
    dataset = db.get(SourceDataset, uuid.UUID(detail["source_dataset_id"]))
    assert dataset.dataset_metadata["analysis_mode"] == "dataset"
    assert is_dataset_intelligence_dataset(dataset) is True

    status = client.get(f"/api/v1/analysis/jobs/{started.json()['job_id']}").json()
    assert status["is_dataset_analysis"] is True


def test_record_mode_start_does_not_mark_the_dataset(client, db):
    import_id = _upload(client).json()["import_id"]
    client.post(
        f"/api/v1/sources/imports/{import_id}/configure",
        json={
            "dataset_title": "Customers",
            "dataset_type": "custom_feedback",
            "analysis_mode": "records",
            "mapping": {"text_column": "feedback"},
        },
    )
    started = client.post(f"/api/v1/sources/imports/{import_id}/start", json={})
    status = client.get(f"/api/v1/analysis/jobs/{started.json()['job_id']}").json()
    assert status["is_dataset_analysis"] is False


def test_history_reports_dataset_facts(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)
    body = client.get("/api/v1/analysis/jobs").json()
    row = next(item for item in body["jobs"] if item["job_id"] == str(job.id))

    assert row["is_dataset_analysis"] is True
    assert row["dataset_file_name"] == "seed.csv"
    assert row["dataset_file_type"] == "csv"
    assert row["dataset_row_count"] == 60
    assert row["dataset_column_count"] == 7
    assert row["dataset_health_score"] is not None


def test_history_leaves_non_dataset_jobs_unchanged(client, db):
    _seed_user(db, _TEST_USER)
    job = AnalysisJob(
        user_id=_TEST_USER.id,
        source_type=SourceType.youtube,
        source_reference="abc",
        collection_mode=CollectionMode.bounded,
        requested_comment_limit=100,
        max_attempts=3,
        status=JobStatus.completed,
    )
    db.add(job)
    db.commit()

    body = client.get("/api/v1/analysis/jobs").json()
    row = next(item for item in body["jobs"] if item["job_id"] == str(job.id))
    assert row["is_dataset_analysis"] is False
    assert row["dataset_row_count"] is None


# ------------------------------------- stale stored prose, corrected on read


def _rewrite_stored_insights(db, job, mutate) -> None:
    stored = DatasetAnalysisRepository(db).get(job.id)
    payload = dict(stored.insights_json)
    mutate(payload)
    stored.insights_json = payload
    flag_modified(stored, "insights_json")
    db.commit()


def test_a_stale_health_band_in_a_stored_summary_is_corrected_on_read(
    client, db, tmp_path, settings, config
):
    job = _seed_analysis(db, tmp_path, settings, config)

    def stale(payload):
        payload["executive_summary"] = dict(payload["executive_summary"])
        payload["executive_summary"][
            "data_health"
        ] = "The dataset has a health score of 76/100 (good), indicating it is usable."

    _rewrite_stored_insights(db, job, stale)

    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset").json()
    health = body["executive_summary"]["data_health"]
    assert "76/100 (fair)" in health
    assert "good" not in health.lower()


def test_a_stored_unmeasured_claim_is_dropped_on_read(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)

    def stale(payload):
        payload["insights"] = [dict(insight) for insight in payload["insights"]]
        payload["insights"][0][
            "impact"
        ] = "Most responses are neutral. This indicates a lack of engagement from the audience."
        payload["executive_summary"] = dict(payload["executive_summary"])
        payload["executive_summary"]["strongest_findings"] = [
            "Two columns are completely empty.",
            "Readers appear disengaged.",
        ]

    _rewrite_stored_insights(db, job, stale)

    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset").json()
    assert body["strongest_findings"][0]["impact"] == "Most responses are neutral."
    assert body["executive_summary"]["strongest_findings"] == ["Two columns are completely empty."]

    insights = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset/insights").json()
    assert "disengaged" not in str(insights).lower()
    assert "lack of engagement" not in str(insights).lower()


def test_correcting_stored_prose_never_rewrites_what_is_already_right(
    client, db, tmp_path, settings, config
):
    job = _seed_analysis(db, tmp_path, settings, config)
    stored = DatasetAnalysisRepository(db).get(job.id)
    original = dict(stored.insights_json["executive_summary"])

    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset").json()
    for field in ("scope", "data_health"):
        assert body["executive_summary"][field] == original[field]


def test_a_dataset_that_measures_a_guarded_concept_keeps_it(client, db, tmp_path, settings, config):
    job = _seed_analysis(db, tmp_path, settings, config)

    def stale(payload):
        payload["facts"] = [
            *payload["facts"],
            {
                "fact_id": "fz",
                "scope": "key_finding",
                "statement": "'engagement_score' averages 41.2 across 60 rows.",
                "weight": 50.0,
                "columns": ["engagement_score"],
                "measures": {},
                "context_only": False,
            },
        ]
        payload["executive_summary"] = dict(payload["executive_summary"])
        payload["executive_summary"]["strongest_findings"] = [
            "engagement_score averages 41.2 across 60 rows."
        ]

    _rewrite_stored_insights(db, job, stale)

    body = client.get(f"/api/v1/analysis/jobs/{job.id}/dataset").json()
    assert body["executive_summary"]["strongest_findings"] == [
        "engagement_score averages 41.2 across 60 rows."
    ]
