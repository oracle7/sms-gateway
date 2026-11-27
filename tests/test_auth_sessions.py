from datetime import timedelta

from fastapi.testclient import TestClient

from config import settings
from database import ensure_utc, utc_now
from main import app
from models import UserSession
from tests.conftest import login_client


def test_login_lockout_and_unlock(isolated_env):
    client = TestClient(app)
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "lori", "password": "wrong-password"})
        assert r.status_code in (401, 423)

    locked = client.post("/api/auth/login", json={"username": "lori", "password": "LoriStaffPass1234!"})
    assert locked.status_code == 423

    admin_client, admin_csrf = login_client("doctor", "DoctorPass1234!")
    users = admin_client.get("/api/admin/users").json()
    lori_id = next(u["id"] for u in users if u["username"] == "lori")

    unlock = admin_client.post(f"/api/admin/users/{lori_id}/unlock", headers={"X-CSRF-Token": admin_csrf})
    assert unlock.status_code == 200

    ok = client.post("/api/auth/login", json={"username": "lori", "password": "LoriStaffPass1234!"})
    assert ok.status_code == 200


def test_csrf_and_rbac_enforcement(isolated_env):
    staff_client, staff_csrf = login_client("lori", "LoriStaffPass1234!")

    # Missing CSRF on mutating route
    no_csrf = staff_client.post("/api/contacts/", json={"phone_number": "9295551111", "name": "Alice"})
    assert no_csrf.status_code == 403

    # Staff blocked from admin routes
    admin_res = staff_client.get("/api/admin/users")
    assert admin_res.status_code == 403

    # Staff blocked from include_hidden=true
    hidden_res = staff_client.get("/api/threads/+19295551111/messages?include_hidden=true")
    assert hidden_res.status_code == 403


def test_concurrent_sessions_and_idle_timeout(isolated_env, monkeypatch):
    c1, csrf1 = login_client("doctor", "DoctorPass1234!")
    c2, _csrf2 = login_client("doctor", "DoctorPass1234!")

    sessions = c1.get("/api/auth/sessions").json()
    assert len(sessions) == 2

    # Background sync & /health/status & /api/auth/me must NOT refresh last_activity_at
    SessionLocal = isolated_env["SessionLocal"]
    db = SessionLocal()
    try:
        sess1 = db.query(UserSession).order_by(UserSession.created_at.asc()).first()
        stale_ts = utc_now() - timedelta(minutes=25)
        sess1.last_activity_at = stale_ts
        db.commit()
    finally:
        db.close()

    assert c1.get("/api/auth/me").status_code == 200
    assert c1.get("/health/status").status_code == 200
    assert c1.get("/api/threads", headers={"X-Background-Sync": "1"}).status_code == 200

    db = SessionLocal()
    try:
        sess1_after = db.query(UserSession).order_by(UserSession.created_at.asc()).first()
        assert ensure_utc(sess1_after.last_activity_at) == stale_ts.replace(tzinfo=ensure_utc(sess1_after.last_activity_at).tzinfo) or abs((ensure_utc(sess1_after.last_activity_at) - stale_ts).total_seconds()) < 2
    finally:
        db.close()

    # Heartbeat DOES refresh activity
    hb = c1.post("/api/auth/heartbeat", headers={"X-CSRF-Token": csrf1})
    assert hb.status_code == 200

    # Simulate expiry past 30 min
    monkeypatch.setattr(settings, "SESSION_IDLE_TIMEOUT_MINUTES", 1)
    db = SessionLocal()
    try:
        sess2 = db.query(UserSession).order_by(UserSession.created_at.desc()).first()
        sess2.last_activity_at = utc_now() - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    expired_resp = c2.get("/api/threads")
    assert expired_resp.status_code == 401
