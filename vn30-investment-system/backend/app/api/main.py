"""Persistent local workflow: refresh SQLite, analyze cached data and export reports."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from threading import Lock
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    HealthResponse,
    JobAccepted,
    JobResult,
    QualityResponse,
    RankingResponse,
    ReportResponse,
    ReportsResponse,
    StockResponse,
    UniverseResponse,
)
from backend.app.core.config import PROJECT_ROOT, load_settings
from backend.app.db.models import AnalysisResult, AnalysisRun, DataQualityIssue, Job, ReportArtifact
from backend.app.db.session import initialize_database

load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] = "1"
os.environ["VNSTOCK_AGENT_TARGETS"] = "none"
engine = initialize_database()
logger = logging.getLogger(__name__)
job_lock = Lock()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """A local process cannot resume closures after restart; expose interrupted jobs."""
    with Session(engine) as session:
        for job in session.scalars(select(Job).where(Job.status.in_(["pending", "running"]))):
            job.status = "failed"
            job.error_code = "INTERRUPTED_ON_RESTART"
            job.finished_at = datetime.now(UTC)
        session.commit()
    yield


app = FastAPI(title="VN30 Research", version="1.0.0", lifespan=lifespan)
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


def serialize(job: Job, include_result: bool = True) -> dict:
    result = {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "timing": dict(job.timing or {}),
        "error": job.error_code,
        "created_at": job.created_at.isoformat(),
    }
    if include_result:
        result["result"] = job.result
    else:
        result["timing"]["stages"] = [
            {"symbol": row.get("symbol"), "timing": row.get("timing", {})}
            for row in (job.result or {}).get("symbols", [])
            if isinstance(row, dict)
        ]
    return result


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
    with job_lock, Session(engine) as session:
        active = session.scalar(
            select(Job).where(Job.kind == kind, Job.status.in_(["pending", "running"]))
        )
        if active is not None:
            raise HTTPException(409, "Tác vụ cùng loại đang chạy. Hãy chờ hoàn thành.")
        session.add(
            Job(id=job_id, kind=kind, status="pending", created_at=datetime.now(UTC), timing={})
        )
        session.commit()
    tasks.add_task(execute, job_id, operation)
    return {"job_id": job_id, "status": "accepted", "message": "Đã nhận tác vụ"}


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=5, max_length=30)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_date: date | None = None


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_date: date | None = None
    end_date: date | None = None
    mode: str | None = None
    top_n: int | None = Field(default=None, ge=1, le=30)
    rebalance: str | None = None
    buy_fee: float | None = Field(default=None, ge=0, lt=1)
    sell_fee: float | None = Field(default=None, ge=0, lt=1)
    sell_tax: float | None = Field(default=None, ge=0, lt=1)
    slippage: float | None = Field(default=None, ge=0, lt=1)


@app.get("/api/health", response_model=HealthResponse)
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
            "jobs": [serialize(j, include_result=False) for j in jobs],
        }


@app.get("/api/universe", response_model=UniverseResponse)
def universe(date_str: Annotated[date | None, Query(alias="date")] = None) -> dict:
    as_of = date_str if isinstance(date_str, date) else today()
    members = []
    origin = None
    fetched_at = None
    warnings = ["Snapshot hiện tại không chứng minh thành phần VN30 trong quá khứ."]
    cache = PROJECT_ROOT / "data" / f"universe-{as_of.isoformat()}.json"
    if cache.exists():
        snapshot = json.loads(cache.read_text(encoding="utf-8"))
        if snapshot.get("observed_on") == as_of.isoformat():
            members = snapshot.get("symbols", [])
            origin = snapshot.get("source")
            fetched_at = snapshot.get("fetched_at")
    path = PROJECT_ROOT / "data/source_health.json"
    if path.exists():
        for check in json.loads(path.read_text(encoding="utf-8")).get("checks", []):
            detail = check.get("details", {})
            if (
                not members
                and check.get("kind") == "universe"
                and detail.get("observed_on") == as_of.isoformat()
            ):
                members = detail.get("symbols", [])
                origin = check.get("source") or "source-health/current-observation"
                fetched_at = check.get("checked_at")
    if not members and as_of == today():
        try:
            from backend.app.data.providers import VnstockUniverseProvider

            result = VnstockUniverseProvider().members()
            members = result if isinstance(result, list) else [r["symbol"] for r in result.records]
            origin = "vnstock/" + load_settings().sources["provider_source"].upper()
            fetched_at = datetime.now(UTC).isoformat()
        except Exception as exc:
            warnings.append(type(exc).__name__)
    if members and not cache.exists():
        cache.write_text(
            json.dumps(
                {
                    "observed_on": as_of.isoformat(),
                    "symbols": members,
                    "fetched_at": fetched_at,
                    "source": origin,
                    "coverage": "observed_current_only",
                    "historical_verified": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return {
        "date": as_of.isoformat(),
        "vn30_members": members,
        "selected": selected(),
        "min_symbols": load_settings().universe.min_symbols,
        "max_symbols": load_settings().universe.max_symbols,
        "warnings": warnings,
        "source": origin,
        "fetched_at": fetched_at,
    }


@app.post("/api/universe/select", response_model=UniverseResponse)
def select_universe(request: Selection) -> dict:
    snapshot = universe()
    symbols = [s.strip().upper() for s in request.symbols]
    limits = load_settings().universe
    if not limits.min_symbols <= len(symbols) <= limits.max_symbols:
        raise HTTPException(422, "Số mã nằm ngoài giới hạn danh mục đã cấu hình")
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


@app.post("/api/data/refresh", status_code=202, response_model=JobAccepted)
def refresh(background_tasks: BackgroundTasks) -> dict:
    from backend.app.data.updater import DataUpdater

    symbols = [s["symbol"] for s in selected()]
    return schedule(
        "refresh", background_tasks, lambda: DataUpdater().refresh_all(symbols, today())
    )


@app.get("/api/jobs/{job_id}", response_model=JobResult)
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
    snapshot = universe(as_of)
    members = set(snapshot["vn30_members"])
    eligible = []
    for row in result.get("main_ranking", []):
        if row["symbol"] in members:
            eligible.append(row)
        else:
            reason = (
                "Chưa xác minh thành viên VN30 tại ngày phân tích"
                if not members
                else "Mã không thuộc VN30 tại ngày phân tích"
            )
            row.update(status="PARTIAL_ANALYSIS", total_score=None)
            row.setdefault("reasons", []).append(reason)
            result["secondary_ranking"].append(row)
    result["main_ranking"] = eligible
    for index, row in enumerate(eligible, start=1):
        row["rank"] = index
    for row in result.get("stocks", []):
        if row["symbol"] not in members:
            if row["status"] == "COMPLETE":
                row["status"] = "PARTIAL_ANALYSIS"
            row["total_score"] = None
            row.setdefault("reasons", []).append(
                "Chưa xác minh thành viên VN30 tại ngày phân tích"
                if not members
                else "Mã không thuộc VN30 tại ngày phân tích"
            )
            row["breakdown"]["status"] = row["status"]
            row["breakdown"]["total_score"] = None
    for row in result.get("secondary_ranking", []):
        details = next(
            (stock for stock in result["stocks"] if stock["symbol"] == row["symbol"]), None
        )
        if details is not None:
            row.update(
                status=details["status"],
                total_score=details["total_score"],
                reasons=details["reasons"],
            )
    result["universe"] = snapshot
    result["input_record_ids"] = {
        row["symbol"]: {
            key: row.get("provenance", {}).get(key, [])
            for key in ("price_ids", "fundamental_ids", "news_ids")
        }
        for row in result.get("stocks", [])
    }
    digest_input = {
        "as_of_date": as_of.isoformat(),
        "config_hash": settings.config_hash,
        "input_record_ids": result["input_record_ids"],
        "universe_members": sorted(members),
    }
    digest = hashlib.sha256(json.dumps(digest_input, sort_keys=True).encode()).hexdigest()
    run_id = str(uuid.uuid4())
    result.update(
        run_id=run_id,
        as_of_date=as_of.isoformat(),
        scoring_version=settings.scoring["version"],
        config_hash=settings.config_hash,
        data_hash=digest,
    )
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
        session.flush()
        for row in result.get("stocks", []):
            session.add(
                AnalysisResult(
                    run_id=run_id,
                    symbol=row["symbol"],
                    fa=row.get("fa_score"),
                    ta=row.get("ta_score"),
                    news=row.get("news_score"),
                    total_score=row.get("total_score"),
                    status=row["status"],
                    reasons=row.get("reasons", []),
                    breakdown=row.get("breakdown", {}),
                )
            )
        session.commit()
    return result


@app.post("/api/analysis/run", status_code=202, response_model=JobAccepted)
def run_analysis(
    background_tasks: BackgroundTasks,
    request: AnalysisRequest | None = None,
    as_of_date: date | None = None,
) -> dict:
    day = (request.as_of_date if request else None) or as_of_date or today()
    if day > today():
        raise HTTPException(422, "Ngày phân tích ở tương lai")
    return schedule("analysis", background_tasks, lambda: analyze(day))


@app.get("/api/ranking", response_model=RankingResponse)
def ranking(as_of: date | None = None) -> dict:
    return latest(as_of) or {
        "as_of_date": (as_of or today()).isoformat(),
        "scoring_version": load_settings().scoring["version"],
        "main_ranking": [],
        "secondary_ranking": [],
        "disclaimer": load_settings().scoring["disclaimer"],
    }


@app.get("/api/stocks/{symbol}", response_model=StockResponse)
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
    try:
        path = create_report(payload, kind, symbol)
    except (ImportError, RuntimeError) as exc:
        logger.error("PDF unavailable error_type=%s", type(exc).__name__)
        raise HTTPException(503, "Chưa đủ thư viện hoặc font để tạo PDF") from None
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


@app.post("/api/reports/summary", response_model=ReportResponse)
def summary_report() -> dict:
    return make_report("summary")


@app.post("/api/reports/stock/{symbol}", response_model=ReportResponse)
def stock_report(symbol: str) -> dict:
    return make_report("stock", symbol.upper())


@app.get("/api/reports", response_model=ReportsResponse)
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


@app.get("/api/config/backtest")
def backtest_config() -> dict:
    return load_settings().backtest


@app.get("/api/data/quality", response_model=QualityResponse)
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


@app.post("/api/backtest/run", status_code=202, response_model=JobAccepted)
def backtest(request: BacktestRequest, background_tasks: BackgroundTasks) -> dict:
    from backend.app.backtest.engine import run_backtest

    settings = load_settings()
    params = request.model_dump(mode="json", exclude_none=True)
    params.setdefault("mode", settings.backtest["default_mode"])
    params.setdefault("top_n", settings.backtest["top_n"])
    params.setdefault("rebalance", settings.backtest["rebalance"])
    for key in ("buy_fee", "sell_fee", "sell_tax", "slippage"):
        params.setdefault(key, settings.backtest[key])
    params["symbols"] = [stock["symbol"] for stock in selected()]
    if params["top_n"] > len(params["symbols"]):
        raise HTTPException(422, "Số mã nắm giữ vượt danh mục đã chọn")
    if params["sell_fee"] + params["sell_tax"] >= 1:
        raise HTTPException(422, "Tổng phí và thuế bán phải nhỏ hơn 100%")
    if params["mode"] not in settings.backtest["modes"] or params["rebalance"] not in {
        "monthly",
        "quarterly",
    }:
        raise HTTPException(422, "Chế độ không hợp lệ")
    if request.start_date and request.end_date and request.start_date >= request.end_date:
        raise HTTPException(422, "Ngày không hợp lệ")
    if (request.end_date and request.end_date > today()) or (
        request.start_date and request.start_date >= (request.end_date or today())
    ):
        raise HTTPException(422, "Khoảng backtest phải kết thúc trước hoặc tại ngày hiện tại")
    return schedule(
        "backtest",
        background_tasks,
        lambda: run_backtest(params, settings),
    )


@app.get("/api/backtest/{backtest_id}", response_model=JobResult)
def backtest_result(backtest_id: str) -> dict:
    job = get_job(backtest_id)
    if job["kind"] != "backtest":
        raise HTTPException(404, "Không tìm thấy tác vụ backtest")
    return job


# Built dashboard supports a single backend process for local presentation.
frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="dashboard")
