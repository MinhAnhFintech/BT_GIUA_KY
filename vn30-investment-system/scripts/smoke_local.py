"""Exercise the local API against real cached data; never generate market fixtures."""

from fastapi.testclient import TestClient

from backend.app.api.main import app


def main() -> None:
    """Persist an actual analysis and its PDFs, and audit backtest availability."""
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        response = client.post("/api/analysis/run", json={})
        assert response.status_code == 202, response.status_code
        job = client.get("/api/jobs/" + response.json()["job_id"]).json()
        assert job["status"] == "completed", job.get("error")
        result = job["result"]
        assert result["stocks"], "No selected stocks"
        print("Analysis completed; stock count:", len(result["stocks"]))
        paths = ["/api/reports/summary", "/api/reports/stock/" + result["stocks"][0]["symbol"]]
        for path in paths:
            report = client.post(path)
            assert report.status_code == 200, report.status_code
            pdf = client.get(report.json()["download_url"])
            assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
            print("PDF generated and downloaded:", path, "bytes:", len(pdf.content))
        response = client.post("/api/backtest/run", json={"mode": "S_ex_news"})
        assert response.status_code == 202
        job = client.get("/api/jobs/" + response.json()["job_id"]).json()
        assert job["status"] == "completed", job.get("error")
        backtest = job["result"]
        print("Historical backtest data status:", backtest["status"])
        if backtest["status"] == "UNAVAILABLE":
            assert backtest["metrics"] is None and backtest["reasons"]
            print("Missing evidence count:", len(backtest["reasons"]))
        dashboard = client.get("/")
        assert dashboard.status_code == 200 and "<html" in dashboard.text
        print("Built dashboard served successfully")


if __name__ == "__main__":
    main()
