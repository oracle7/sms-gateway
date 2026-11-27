import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import sessionmaker

from config import settings
from database import create_sqlite_engine
from services.audit import verify_audit_chain


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SHA-256 hash chain integrity of audit_logs.")
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to SQLite DB file (defaults to DATABASE_URL from .env).",
    )
    args = parser.parse_args()

    db_url = f"sqlite:///{Path(args.db).resolve()}" if args.db else settings.DATABASE_URL
    eng = create_sqlite_engine(db_url)
    Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True)

    db = Session()
    try:
        result = verify_audit_chain(db)
    finally:
        db.close()
        eng.dispose()

    if result["valid"]:
        print(f"OK: audit_logs hash chain is valid ({result['total_rows']} row(s) verified).")
        return 0

    print(
        f"FAILED: {result['error']} (first_broken_id={result['first_broken_id']}, total_rows={result['total_rows']})",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
