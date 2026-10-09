"""Check license safely, optionally run source probes with the key in process memory."""

import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from backend.app.core.auth import verify_access
from backend.app.core.config import PROJECT_ROOT, load_settings


def main() -> None:
    """No registration helpers: SDK setup_api_key writes the key to disk."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", action="store_true", help="Read key with hidden input")
    parser.add_argument("--check-sources", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/access_status.json")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    api_key = (
        getpass.getpass("VNSTOCK_API_KEY (hidden): ")
        if args.prompt
        else os.getenv("VNSTOCK_API_KEY")
    )
    result = verify_access(api_key, load_settings().sources["timeout_seconds"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json())
    if result.status != "VERIFIED":
        sys.exit(1)
    if args.check_sources:
        os.environ["VNSTOCK_API_KEY"] = api_key.strip()
        os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] = "1"
        os.environ["VNSTOCK_AGENT_TARGETS"] = "none"
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from scripts.data_source_check import run_checks

        report = run_checks(
            datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date(),
            PROJECT_ROOT / "data/source_health_authenticated.json",
        )
        for health in report["checks"]:
            print(f"{health['status']:12} {health['name']:25} {health['reason'] or ''}")
        if any(h["required"] and h["status"] != "OK" for h in report["checks"]):
            sys.exit(2)


if __name__ == "__main__":
    main()
