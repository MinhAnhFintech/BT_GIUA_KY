"""Probe public sources with isolated, timeout-bounded SDK workers and no raw logs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.app.core.auth import verify_access
from backend.app.core.config import PROJECT_ROOT, load_settings
from backend.app.data.health import SourceHealth, inspect_frame, probe_rss

logger = logging.getLogger(__name__)
RESULT_MARKER = "VN30_PROBE_RESULT="


def sdk_probe(kind: str, as_of: date, sources: dict[str, Any]) -> SourceHealth:
    """Use verified SDK call signatures; no register_user/setup_agent/skill disk writes."""
    os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] = "1"
    os.environ["VNSTOCK_AGENT_TARGETS"] = "none"
    health = SourceHealth(
        name=f"vnstock_{kind}",
        kind=kind,
        status="NOT_VERIFIED",
        source=f"vnstock/{sources['provider_source'].upper()}",
        source_url=sources["provider_base_url"],
        requested_as_of=as_of,
    )
    start = time.perf_counter()
    try:
        from vnstock import Fundamental, Market, Reference

        provider_source = sources["provider_source"]
        symbol = sources["probe_symbol"]
        # Standard SDK adapter uses its own provider routing and rate limiter.
        if kind == "universe":
            frame = Reference().equity.list_by_group("VN30", source=provider_source)
        elif kind == "prices":
            frame = (
                Market()
                .equity(symbol)
                .ohlcv(
                    start=(
                        as_of - timedelta(days=sources["price_probe_lookback_days"])
                    ).isoformat(),
                    end=as_of.isoformat(),
                    source=provider_source,
                )
            )
        elif kind == "financials":
            frame = (
                Fundamental().equity(symbol).balance_sheet(period="quarter", source=provider_source)
            )
        elif kind == "company":
            frame = Reference().company(symbol).info(source=provider_source)
        elif kind == "news":
            frame = Reference().company(symbol).news(source=provider_source)
        else:
            raise ValueError("UNKNOWN_PROBE")
        fields = inspect_frame(frame, kind, as_of)
        health = health.model_copy(update={"status": "OK", **fields})
    except Exception as error:
        health.status = "FAIL"
        safe_codes = {
            "EMPTY_OR_UNEXPECTED_SCHEMA",
            "MISSING_SYMBOL_COLUMN",
            "INVALID_VN30_MEMBERSHIP_SCHEMA",
            "MISSING_OHLCV_COLUMNS",
            "INVALID_OR_DUPLICATE_PRICE_DATE",
            "FUTURE_PRICE_RETURNED",
            "INVALID_PRICE_VALUES",
            "INVALID_VOLUME_VALUES",
            "INVALID_OHLC_RANGE",
            "MISSING_FINANCIAL_METADATA_COLUMNS",
            "MISSING_REPORT_PERIODS",
            "MISSING_NEWS_TITLE_COLUMN",
            "MISSING_COMPANY_METADATA_COLUMNS",
            "UNKNOWN_PROBE",
        }
        health.reason = str(error) if str(error) in safe_codes else type(error).__name__
    health.duration_seconds = time.perf_counter() - start
    return health


def run_checks(as_of: date, output: Path) -> dict[str, Any]:
    """Record real checks and limitations; source OK never implies backtest readiness."""
    settings = load_settings()
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    access = verify_access(os.environ.get("VNSTOCK_API_KEY"), settings.sources["timeout_seconds"])
    environment = os.environ.copy()
    environment.update(
        {
            "VNSTOCK_DISABLE_AGENT_SETUP": "1",
            "VNSTOCK_AGENT_TARGETS": "none",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    results: list[SourceHealth] = []
    for spec in settings.sources["probes"]:
        start = time.perf_counter()
        health = SourceHealth(
            name=spec["name"],
            kind=spec["kind"],
            status="FAIL",
            required=spec["required"],
            source=f"vnstock/{settings.sources['provider_source'].upper()}",
            source_url=settings.sources["provider_base_url"],
            requested_as_of=as_of,
        )
        try:
            worker = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.data_source_check",
                    "--probe",
                    spec["kind"],
                    "--as-of",
                    as_of.isoformat(),
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.sources["max_probe_seconds"],
                check=False,
            )
            lines = [line for line in worker.stdout.splitlines() if line.startswith(RESULT_MARKER)]
            if worker.returncode == 0 and lines:
                health = SourceHealth.model_validate_json(lines[-1][len(RESULT_MARKER) :])
                health.name = spec["name"]
                health.required = spec["required"]
            else:
                health.reason = "WORKER_FAILED_OR_NO_RESULT"
        except subprocess.TimeoutExpired:
            health.reason = "PROVIDER_TIMEOUT"
        health.duration_seconds = time.perf_counter() - start
        results.append(health)
        logger.info(
            "source=%s status=%s reason=%s duration=%.2fs",
            health.name,
            health.status,
            health.reason,
            health.duration_seconds,
        )
        time.sleep(settings.sources["request_interval_seconds"])
    for spec in settings.sources["rss"]:
        start = time.perf_counter()
        health = probe_rss(spec, settings.sources, as_of)
        health.duration_seconds = time.perf_counter() - start
        results.append(health)
    packages = {}
    for package in ("vnstock", "vnai", "SQLAlchemy", "pydantic", "pytest", "ruff", "PyYAML"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "requested_as_of": as_of.isoformat(),
        "config_hash": settings.config_hash,
        "python": sys.version.split()[0],
        "package_versions": packages,
        "api_key_present": bool(os.environ.get("VNSTOCK_API_KEY")),
        "tier": access.tier.upper() if access.status == "VERIFIED" else "NOT_AUTHENTICATED",
        "access_status": access.model_dump(mode="json"),
        "checks": [h.model_dump(mode="json") for h in results],
        "backtest_ready": False,
        "limitations": [
            "Historical membership, publication vintages, corporate actions and "
            "exchange calendar still require verification at stages 2 and 7."
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    """Exit nonzero for failed required sources; optional failures remain visible."""
    # PowerShell's default legacy code page cannot print Vietnamese directory names.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=datetime.now(timezone(timedelta(hours=7))).date(),
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/source_health.json")
    parser.add_argument("--probe", choices=["universe", "prices", "financials", "company", "news"])
    args = parser.parse_args()
    if args.probe:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        result = sdk_probe(args.probe, args.as_of, load_settings().sources)
        print(RESULT_MARKER + result.model_dump_json())
        return
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = run_checks(args.as_of, args.output)
    for health in report["checks"]:
        print(f"{health['status']:12} {health['name']:25} {health['reason'] or ''}")
    print(f"Report: {args.output}")
    if any(h["required"] and h["status"] != "OK" for h in report["checks"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
