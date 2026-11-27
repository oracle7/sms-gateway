import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database
from config import settings
from main import app
from models import User
from services.security import hash_password


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    db_file = tmp_path / "test_v3.db"
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    db_url = f"sqlite:///{db_file}"
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "MEDIA_DIR", str(media_dir))
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "WEBHOOK_VERIFY_SIGNATURE", False)
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_IPS", "")
    monkeypatch.setattr(settings, "SMS_DID", "+19296141937")

    test_engine = database.create_sqlite_engine(db_url)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine, future=True)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)

    database.init_db(test_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_get_db

    # Seed doctor (admin) and Lori (staff)
    db = TestSessionLocal()
    try:
        admin = User(
            username="doctor",
            display_name="Dr. Smith",
            role="admin",
            password_hash=hash_password("DoctorPass1234!"),
            is_active=True,
        )
        staff = User(
            username="lori",
            display_name="Lori",
            role="staff",
            password_hash=hash_password("LoriStaffPass1234!"),
            is_active=True,
        )
        db.add_all([admin, staff])
        db.commit()
    finally:
        db.close()

    yield {
        "db_file": db_file,
        "media_dir": media_dir,
        "engine": test_engine,
        "SessionLocal": TestSessionLocal,
    }

    app.dependency_overrides.clear()
    test_engine.dispose()


def login_client(username: str, password: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    csrf = res.json()["csrf_token"]
    return client, csrf
