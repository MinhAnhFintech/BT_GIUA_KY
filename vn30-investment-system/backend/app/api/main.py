"""Persistent local workflow: refresh SQLite, analyze cached data and export reports."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import PROJECT_ROOT, load_settings
from backend.app.db.models import AnalysisRun, DataQualityIssue, Job, ReportArtifact
from backend.app.db.session import initialize_database

load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] = "1"
os.environ["VNSTOCK_AGENT_TARGETS"] = "none"
engine = initialize_database()
logger = logging.getLogger(__name__)
app = FastAPI(title="VN30 Research", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()


def clean(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def selected() -> list[dict[str, str]]:
    path = PROJECT_ROOT / "data/selection.json"
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else [s.model_dump() for s in load_settings().universe.selected]
    )


def latest(as_of: date | None = None) -> dict | None:
    with Session(engine) as session:
        for job in session.scalars(
            select(Job)
            .where(Job.kind == "analysis", Job.status == "completed")
            .order_by(Job.created_at.desc())
        ):
            if job.result and (as_of is None or job.result.get("as_of_date") == as_of.isoformat()):
                return job.result
    return None


def serialize(job: Job) -> dict:
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "result": job.result,
        "timing": job.timing,
        "error": job.error_code,
        "created_at": job.created_at.isoformat(),
    }


def execute(job_id: str, operation: Any) -> None:
    from time import perf_counter

    start = perf_counter()
    with Session(engine) as session:
        job = session.get(Job, job_id)
        job.status = "running"
        session.commit()
    try:
        result = clean(operation())
        status = "completed"
        error = None
    except Exception as exc:
        result = None
        status = "failed"
        error = type(exc).__name__
        logger.error("job=%s error_type=%s", job_id, error)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        job.status = status
        job.result = result
        job.error_code = error
        job.finished_at = datetime.now(UTC)
        job.timing = {"total_seconds": perf_counter() - start}
        session.commit()


def schedule(kind: str, tasks: BackgroundTasks, operation: Any) -> dict:
    job_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            Job(id=job_id, kind=kind, status="pending", created_at=datetime.now(UTC), timing={})
        )
        session.commit()
    tasks.add_task(execute, job_id, operation)
    return {"job_id": job_id, "status": "accepted", "message": "Đã nhận tác vụ"}


class Selection(BaseModel):
    symbols: list[str] = Field(min_length=5, max_length=10)


class AnalysisRequest(BaseModel):
    as_of_date: date | None = None


class BacktestRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    mode: str = "S_ex_news"
    top_n: int = Field(default=3, ge=1, le=10)
    rebalance: str = "monthly"


@app.get("/api/health")
def health() -> dict:
    path = PROJECT_ROOT / "data/source_health_authenticated.json"
    if not path.exists():
        path = PROJECT_ROOT / "data/source_health.json"
    settings = load_settings()
    with Session(engine) as session:
        jobs = session.scalars(select(Job).order_by(Job.created_at.desc()).limit(20)).all()
        return {
            "status": "OK",
            "scoring_version": settings.scoring["version"],
            "config_hash": settings.config_hash,
            "timestamp": datetime.now(UTC).isoformat(),
            "api_key_present": bool(os.getenv("VNSTOCK_API_KEY")),
            "data_sources": json.loads(path.read_text(encoding="utf-8")) if path.exists() else {},
            "jobs": [serialize(j) for j in jobs],
        }


@app.get("/api/universe")
def universe(date_str: date | None = Query(default=None, alias="date")) -> dict:
    as_of = date_str if isinstance(date_str, date) else today()
    members = []
    warnings = ["Snapshot hiện tại không chứng minh thành phần VN30 trong quá khứ."]
    path = PROJECT_ROOT / "data/source_health.json"
    if path.exists():
        for check in json.loads(path.read_text(encoding="utf-8")).get("checks", []):
            detail = check.get("details", {})
            if check.get("kind") == "universe" and detail.get("observed_on") == as_of.isoformat():
                members = detail.get("symbols", [])
    if not members and as_of == today():
        try:
            from backend.app.data.providers import VnstockUniverseProvider

            result = VnstockUniverseProvider().members()
            members = result if isinstance(result, list) else [r["symbol"] for r in result.records]
        except Exception as exc:
            warnings.append(type(exc).__name__)
    return {
        "date": as_of.isoformat(),
        "vn30_members": members,
        "selected": selected(),
        "warnings": warnings,
    }


@app.post("/api/universe/select")
def select_universe(request: Selection) -> dict:
    snapshot = universe()
    symbols = [s.strip().upper() for s in request.symbols]
    if len(set(symbols)) != len(symbols):
        raise HTTPException(422, "Có mã trùng")
    if not snapshot["vn30_members"]:
        raise HTTPException(409, "Chưa có snapshot VN30 hợp lệ")
    if set(symbols) - set(snapshot["vn30_members"]):
        raise HTTPException(422, "Có mã ngoài VN30")
    sectors = {s.symbol: s.sector for s in load_settings().universe.selected}
    selection = [{"symbol": s, "sector": sectors.get(s, "unknown")} for s in symbols]
    (PROJECT_ROOT / "data/selection.json").write_text(json.dumps(selection), encoding="utf-8")
    snapshot["selected"] = selection
    return snapshot


@app.post("/api/data/refresh", status_code=202)
def refresh(background_tasks: BackgroundTasks) -> dict:
    from backend.app.data.updater import DataUpdater

    symbols = [s["symbol"] for s in selected()]
    return schedule(
        "refresh", background_tasks, lambda: DataUpdater().refresh_all(symbols, today())
    )


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Không tìm thấy tác vụ")
        return serialize(job)


def analyze(as_of: date) -> dict:
    from backend.app.analysis.service import analyze_cached

    settings = load_settings()
    result = clean(analyze_cached(selected(), as_of, settings))
    run_id = str(uuid.uuid4())
    result.update(
        run_id=run_id,
        as_of_date=as_of.isoformat(),
        scoring_version=settings.scoring["version"],
        config_hash=settings.config_hash,
    )
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    with Session(engine) as session:
        session.add(
            AnalysisRun(
                id=run_id,
                as_of_date=as_of,
                created_at=datetime.now(UTC),
                scoring_version=settings.scoring["version"],
                config_hash=settings.config_hash,
                data_hash=digest,
                input_record_ids=result.get("input_record_ids", {}),
                config_snapshot=settings.model_dump(mode="json"),
            )
        )
        session.commit()
    return result


@app.post("/api/analysis/run", status_code=202)
def run_analysis(
    background_tasks: BackgroundTasks,
    request: AnalysisRequest | None = None,
    as_of_date: date | None = None,
) -> dict:
    day = (request.as_of_date if request else None) or as_of_date or today()
    if day > today():
        raise HTTPException(422, "Ngày phân tích ở tương lai")
    return schedule("analysis", background_tasks, lambda: analyze(day))


@app.get("/api/ranking")
def ranking(as_of: date | None = None) -> dict:
    return latest(as_of) or {
        "as_of_date": (as_of or today()).isoformat(),
        "scoring_version": load_settings().scoring["version"],
        "main_ranking": [],
        "secondary_ranking": [],
        "disclaimer": load_settings().scoring["disclaimer"],
    }


@app.get("/api/stocks/{symbol}")
def stock(symbol: str) -> dict:
    details = (latest() or {}).get("stocks", [])
    if isinstance(details, list):
        details = {s["symbol"]: s for s in details}
    if symbol.upper() not in details:
        raise HTTPException(404, "Hãy chạy phân tích mã này trước")
    return details[symbol.upper()]


def make_report(kind: str, symbol: str | None = None) -> dict:
    from backend.app.reports.pdf import create_report

    payload = latest()
    if not payload:
        raise HTTPException(409, "Hãy chạy phân tích trước")
    if symbol:
        stock(symbol)
    path = create_report(payload, kind, symbol)
    report_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            ReportArtifact(
                id=report_id,
                analysis_run_id=payload["run_id"],
                kind=kind,
                symbol=symbol,
                created_at=datetime.now(UTC),
                relative_path=path.name,
                file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
        session.commit()
    return {
        "report_id": report_id,
        "kind": kind,
        "status": "completed",
        "download_url": f"/api/reports/{report_id}/download",
    }


@app.post("/api/reports/summary")
def summary_report() -> dict:
    return make_report("summary")


@app.post("/api/reports/stock/{symbol}")
def stock_report(symbol: str) -> dict:
    return make_report("stock", symbol.upper())


@app.get("/api/reports")
def reports() -> dict:
    with Session(engine) as session:
        return {
            "reports": [
                {
                    "report_id": r.id,
                    "kind": r.kind,
                    "symbol": r.symbol,
                    "status": "completed",
                    "created_at": r.created_at.isoformat(),
                    "download_url": f"/api/reports/{r.id}/download",
                }
                for r in session.scalars(
                    select(ReportArtifact).order_by(ReportArtifact.created_at.desc())
                )
            ]
        }


@app.get("/api/reports/{report_id}/download")
def download(report_id: str) -> FileResponse:
    with Session(engine) as session:
        r = session.get(ReportArtifact, report_id)
        if r is None:
            raise HTTPException(404, "Không có báo cáo")
        root = (PROJECT_ROOT / "reports_out").resolve()
        path = (root / r.relative_path).resolve()
        if path.parent != root or not path.is_file():
            raise HTTPException(404, "File không hợp lệ")
        return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/config/scoring")
def scoring_config() -> dict:
    return load_settings().scoring


@app.get("/api/data/quality")
def quality() -> dict:
    with Session(engine) as session:
        return {
            "issues": [
                {
                    "symbol": i.symbol,
                    "code": i.code,
                    "detail": i.detail,
                    "severity": i.severity,
                    "as_of_date": i.as_of_date.isoformat(),
                }
                for i in session.scalars(
                    select(DataQualityIssue).order_by(DataQualityIssue.id.desc()).limit(200)
                )
            ],
            "checks": health()["data_sources"].get("checks", []),
        }


@app.post("/api/backtest/run", status_code=202)
def backtest(request: BacktestRequest, background_tasks: BackgroundTasks) -> dict:
    from backend.app.backtest.engine import run_backtest

    settings = load_settings()
    if request.mode not in settings.backtest["modes"] or request.rebalance not in {
        "monthly",
        "quarterly",
    }:
        raise HTTPException(422, "Chế độ không hợp lệ")
    if request.start_date and request.end_date and request.start_date >= request.end_date:
        raise HTTPException(422, "Ngày không hợp lệ")
    return schedule(
        "backtest",
        background_tasks,
        lambda: run_backtest(request.model_dump(mode="json"), settings),
    )


@app.get("/api/backtest/{backtest_id}")
def backtest_result(backtest_id: str) -> dict:
    return get_job(backtest_id)
