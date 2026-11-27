from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Returns timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Attaches UTC tzinfo when SQLite returns a naive datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ensure_sqlite_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw_path = database_url[len("sqlite:///"):]
    if raw_path == ":memory:" or raw_path.startswith("file:"):
        return
    db_path = Path(raw_path)
    if db_path.parent and str(db_path.parent) not in ("", "."):
        db_path.parent.mkdir(parents=True, exist_ok=True)


def create_sqlite_engine(database_url: str) -> Engine:
    """Creates a SQLite SQLAlchemy engine with HIPAA-safe WAL and FK pragmas."""
    _ensure_sqlite_dir(database_url)
    eng = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return eng


engine = create_sqlite_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


AUDIT_IMMUTABILITY_SQL = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
    BEFORE UPDATE ON audit_logs
    BEGIN
        SELECT RAISE(ABORT, 'audit_logs is immutable: UPDATE not permitted');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
    BEFORE DELETE ON audit_logs
    BEGIN
        SELECT RAISE(ABORT, 'audit_logs is immutable: DELETE not permitted');
    END;
    """,
]


def init_db(target_engine: Optional[Engine] = None) -> None:
    """Creates all tables and installs SQLite immutability triggers on audit_logs."""
    import models  # noqa: F401 - ensures ORM models are registered on Base.metadata

    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
    with eng.begin() as conn:
        for stmt in AUDIT_IMMUTABILITY_SQL:
            conn.execute(text(stmt))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
