"""Synthetic isolated API fixtures, never production market data."""

from datetime import UTC, date, datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api import main
from backend.app.core.config import load_settings
from backend.app.db.models import Job
from backend.app.db.session import initialize_database


def test_health_jobs_and_input_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "engine", initialize_database(tmp_path / "api.sqlite"))
    client = TestClient(main.app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.post("/api/universe/select", json={"symbols": ["FPT"]}).status_code == 422
    assert client.post("/api/analysis/run", json={"as_of_date": "2099-01-01"}).status_code == 422


def test_analysis_job_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "engine", initialize_database(tmp_path / "api.sqlite"))
    monkeypatch.setattr(
        main,
        "analyze",
        lambda day: {
            "as_of_date": day.isoformat(),
            "main_ranking": [],
            "secondary_ranking": [],
            "stocks": [],
        },
    )
    client = TestClient(main.app)
    response = client.post("/api/analysis/run", json={"as_of_date": "2026-10-09"})
    assert response.status_code == 202
    job = client.get("/api/jobs/" + response.json()["job_id"]).json()
    assert job["status"] == "completed"
    assert client.get("/api/ranking?as_of=2026-10-08").json()["main_ranking"] == []


@pytest.fixture
def isolated_api(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "engine", initialize_database(tmp_path / "api.sqlite"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main, "today", lambda: date(2026, 10, 9))
    (tmp_path / "data").mkdir(exist_ok=True)
    return TestClient(main.app)


def add_job(status="completed", kind="analysis", result=None):
    with Session(main.engine) as session:
        session.add(
            Job(
                id="test-job",
                kind=kind,
                status=status,
                created_at=datetime(2026, 10, 9, tzinfo=UTC),
                timing={"total_seconds": 1},
                result=result,
            )
        )
        session.commit()


def test_health_summaries_do_not_repeat_large_job_results(isolated_api):
    add_job(result={"stocks": [{"prices": [1] * 10000}]})
    response = isolated_api.get("/api/health")
    assert response.status_code == 200
    assert "result" not in response.json()["jobs"][0]
    assert len(response.content) < 2000
    with Session(main.engine) as session:
        assert session.get(Job, "test-job").timing == {"total_seconds": 1}


def test_restart_marks_interrupted_jobs_failed(isolated_api):
    add_job(status="running")
    with isolated_api as client:
        job = client.get("/api/jobs/test-job").json()
        assert job["status"] == "failed"
        assert job["error"] == "INTERRUPTED_ON_RESTART"


def test_duplicate_active_job_does_not_launch_second_worker(isolated_api):
    add_job(status="pending")
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as error:
        main.schedule("analysis", tasks, lambda: {})
    assert error.value.status_code == 409
    assert tasks.tasks == []


def test_ranking_response_excludes_full_stock_histories(isolated_api, monkeypatch):
    monkeypatch.setattr(
        main,
        "latest",
        lambda day=None: {
            "as_of_date": "2026-10-09",
            "scoring_version": "test-only",
            "main_ranking": [],
            "secondary_ranking": [],
            "disclaimer": "Test fixture",
            "stocks": [{"prices": [1] * 10000}],
        },
    )
    response = isolated_api.get("/api/ranking")
    assert response.status_code == 200
    assert "stocks" not in response.json()
    assert len(response.content) < 1000


@pytest.mark.parametrize(
    "body",
    [
        {"sell_fee": 0.7, "sell_tax": 0.4},
        {"end_date": "2026-10-10"},
        {"start_date": "2026-10-09"},
        {"top_n": 31},
        {"rebalance": "daily"},
        {"execution": "same_day"},
    ],
)
def test_invalid_backtest_requests_rejected_before_job(isolated_api, body):
    assert isolated_api.post("/api/backtest/run", json=body).status_code == 422
    assert isolated_api.get("/api/health").json()["jobs"] == []


def test_backtest_uses_config_defaults_and_current_selection(isolated_api, monkeypatch):
    from backend.app.backtest import engine

    captured = {}
    monkeypatch.setattr(main, "selected", lambda: [{"symbol": s} for s in "ABCDE"])

    def run(request, settings):
        captured.update(request)
        return {"status": "TEST_ONLY"}

    monkeypatch.setattr(engine, "run_backtest", run)
    response = isolated_api.post("/api/backtest/run", json={"rebalance": "quarterly"})
    assert response.status_code == 202
    settings = load_settings()
    assert captured["symbols"] == list("ABCDE")
    assert captured["rebalance"] == "quarterly"
    assert captured["top_n"] == settings.backtest["top_n"]
    assert captured["buy_fee"] == settings.backtest["buy_fee"]


def test_backtest_endpoint_rejects_other_job_kind(isolated_api):
    add_job(kind="analysis")
    assert isolated_api.get("/api/backtest/test-job").status_code == 404


def test_universe_cache_retains_real_provider_source(isolated_api, tmp_path):
    import json

    snapshot = {
        "observed_on": "2026-10-09",
        "symbols": ["TEST_ONLY"],
        "source": "TEST_ONLY/VCI",
        "fetched_at": "2026-10-09T00:00:00Z",
    }
    (tmp_path / "data/universe-2026-10-09.json").write_text(json.dumps(snapshot))
    response = isolated_api.get("/api/universe")
    assert response.status_code == 200
    assert response.json()["source"] == "TEST_ONLY/VCI"
    assert response.json()["fetched_at"] == snapshot["fetched_at"]


def test_openapi_has_explicit_response_contracts(isolated_api):
    schemas = isolated_api.get("/openapi.json").json()["components"]["schemas"]
    assert "JobResult" in schemas and "HealthResponse" in schemas
    assert "result" not in schemas["HealthJob"]["properties"]
    assert "main_ranking" in schemas["RankingResponse"]["properties"]


def test_unverified_membership_keeps_scores_and_breakdown_consistent(isolated_api, monkeypatch):
    from backend.app.analysis import service

    def payload(items, day, settings):
        rows = []
        for symbol in ("AAA", "BBB"):
            rows.append(
                {
                    "symbol": symbol,
                    "sector": "technology",
                    "status": "COMPLETE",
                    "fa_score": 60,
                    "ta_score": 60,
                    "news_score": 60,
                    "total_score": 60,
                    "reasons": [],
                    "breakdown": {"status": "COMPLETE", "total_score": 60},
                }
            )
        return {
            "stocks": rows,
            "main_ranking": [dict(row, rank=i + 1) for i, row in enumerate(rows)],
            "secondary_ranking": [],
            "disclaimer": "Test only",
        }

    monkeypatch.setattr(service, "analyze_cached", payload)
    monkeypatch.setattr(main, "universe", lambda day: {"vn30_members": ["BBB"]})
    result = main.analyze(date(2026, 10, 9))
    assert [(row["symbol"], row["rank"]) for row in result["main_ranking"]] == [("BBB", 1)]
    ineligible = result["stocks"][0]
    assert ineligible["status"] == ineligible["breakdown"]["status"] == "PARTIAL_ANALYSIS"
    assert ineligible["total_score"] is ineligible["breakdown"]["total_score"] is None
    assert result["secondary_ranking"][0]["total_score"] is None


def test_analysis_data_hash_does_not_depend_on_run_id(isolated_api, monkeypatch):
    from backend.app.analysis import service

    monkeypatch.setattr(
        service,
        "analyze_cached",
        lambda *args: {
            "stocks": [],
            "main_ranking": [],
            "secondary_ranking": [],
        },
    )
    monkeypatch.setattr(main, "universe", lambda day: {"vn30_members": ["TEST_ONLY"]})
    first = main.analyze(date(2026, 10, 9))
    second = main.analyze(date(2026, 10, 9))
    assert first["run_id"] != second["run_id"]
    assert first["data_hash"] == second["data_hash"]
