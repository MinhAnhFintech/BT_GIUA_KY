"""SQLite connection setup with enforced foreign keys and durable WAL mode."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event

from backend.app.core.config import PROJECT_ROOT
from backend.app.db.models import Base


def create_sqlite_engine(path: Path | None = None) -> Engine:
    """Prepare a project-local database; never writes outside the project."""
    database = path or PROJECT_ROOT / "data" / "vn30.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection: object, _: object) -> None:
        """Foreign keys are off by default in SQLite and must be explicitly enabled."""
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def initialize_database(path: Path | None = None) -> Engine:
    """Initialize stage-1 schema; Alembic upgrade migrations arrive with data ingestion."""
    engine = create_sqlite_engine(path)
    Base.metadata.create_all(engine)
    return engine
