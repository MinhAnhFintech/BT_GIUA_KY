"""Initialize schema without inserting fake or unverified market data."""

from sqlalchemy import inspect

from backend.app.core.config import load_settings
from backend.app.db.session import initialize_database


def main() -> None:
    """Validate configuration first, then create the initial empty database."""
    settings = load_settings()
    engine = initialize_database()
    print(f"Schema ready: {len(inspect(engine).get_table_names())} tables")
    print(f"Scoring version: {settings.scoring['version']}")
    print(f"Config SHA256: {settings.config_hash}")
    engine.dispose()


if __name__ == "__main__":
    main()
