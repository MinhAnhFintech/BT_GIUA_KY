"""Synthetic isolated API fixtures, never production market data."""

from fastapi.testclient import TestClient

from backend.app.api import main
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
