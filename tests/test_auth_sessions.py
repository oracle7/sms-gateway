from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from config import settings
from database import ensure_utc, utc_now
from main import app
from models import UserSession
from services.auth import compute_next_daily_cutoff_utc
from tests.conftest import login_client


def test_compute_next_daily_cutoff_utc():
    # 10:00 AM EST (15:00 UTC in winter) -> next cutoff is tomorrow 00:05 EST (05:05 UTC)
    morning_utc = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)
    cutoff1 = compute_next_daily_cutoff_utc(morning_utc, "America/New_York", "00:05")
    assert cutoff1 == datetime(2026, 1, 16, 5, 5, tzinfo=timezone.utc)

    # 12:01 AM EST (05:01 UTC) -> next cutoff is same day 00:05 EST (05:05 UTC)
    just_after_midnight_utc = datetime(2026, 1, 15, 5, 1, tzinfo=timezone.utc)
    cutoff2 = compute_next_daily_cutoff_utc(just_after_midnight_utc, "America/New_York", "00:05")
    assert cutoff2 == datetime(2026, 1, 15, 5, 5, tzinfo=timezone.utc)

    # Summer EDT (UTC-4): 10:00 AM EDT -> next cutoff is tomorrow 00:05 EDT (04:05 UTC)
    summer_utc = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    cutoff3 = compute_next_daily_cutoff_utc(summer_utc, "America/New_York", "00:05")
    assert cutoff3 == datetime(2026, 7, 16, 4, 5, tzinfo=timezone.utc)


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
    staff_client, _staff_csrf = login_client("lori", "LoriStaffPass1234!")

    # Missing CSRF on mutating route
    no_csrf = staff_client.post("/api/contacts/", json={"phone_number": "9295551111", "name": "Alice"})
    assert no_csrf.status_code == 403

    # Staff blocked from admin routes
    admin_res = staff_client.get("/api/admin/users")
    assert admin_res.status_code == 403

    # Staff blocked from include_hidden=true
    hidden_res = staff_client.get("/api/threads/+19295551111/messages?include_hidden=true")
    assert hidden_res.status_code == 403


def test_default_overnight_cutoff_without_idle_timeout(isolated_env):
    assert settings.SESSION_IDLE_TIMEOUT_MINUTES == 0
    lori_client, _ = login_client("lori", "LoriStaffPass1234!")

    # Even if last_activity_at is 6 hours old, Lori stays signed in during the workday
    SessionLocal = isolated_env["SessionLocal"]
    db = SessionLocal()
    try:
        sess = db.query(UserSession).order_by(UserSession.created_at.desc()).first()
        sess.last_activity_at = utc_now() - timedelta(hours=6)
        db.commit()
    finally:
        db.close()

    assert lori_client.get("/api/threads").status_code == 200

    # Once daily midnight cutoff (expires_at) passes, session is revoked
    db = SessionLocal()
    try:
        sess = db.query(UserSession).order_by(UserSession.created_at.desc()).first()
        sess.expires_at = utc_now() - timedelta(seconds=10)
        db.commit()
    finally:
        db.close()

    assert lori_client.get("/api/threads").status_code == 401


def test_concurrent_sessions_and_optional_idle_timeout(isolated_env, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_IDLE_TIMEOUT_MINUTES", 30)
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
        assert abs((ensure_utc(sess1_after.last_activity_at) - stale_ts).total_seconds()) < 2
    finally:
        db.close()

    # Heartbeat DOES refresh activity
    hb = c1.post("/api/auth/heartbeat", headers={"X-CSRF-Token": csrf1})
    assert hb.status_code == 200

    # Simulate expiry past optional idle timeout
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


def test_admin_edit_user_and_revoke_sessions(isolated_env):
    admin_client, admin_csrf = login_client("doctor", "DoctorPass1234!")
    users = admin_client.get("/api/admin/users").json()
    doc_id = next(u["id"] for u in users if u["username"] == "doctor")
    lori_id = next(u["id"] for u in users if u["username"] == "lori")

    # Edit Lori's display name
    edit_res = admin_client.patch(
        f"/api/admin/users/{lori_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"display_name": "Lori M."},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["display_name"] == "Lori M."

    # Cannot demote the last active admin
    demote_res = admin_client.patch(
        f"/api/admin/users/{doc_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"role": "staff"},
    )
    assert demote_res.status_code == 400

    # Lori signs in on 2 separate browsers
    lori1, _ = login_client("lori", "LoriStaffPass1234!")
    lori2, _ = login_client("lori", "LoriStaffPass1234!")

    all_sessions = admin_client.get("/api/admin/sessions").json()
    lori_sessions = [s for s in all_sessions if s["user_id"] == lori_id]
    assert len(lori_sessions) == 2

    # Revoke one specific session
    revoke_one = admin_client.post(
        f"/api/admin/sessions/{lori_sessions[0]['id']}/revoke",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert revoke_one.status_code == 200

    statuses_after_one = sorted([lori1.get("/api/threads").status_code, lori2.get("/api/threads").status_code])
    assert statuses_after_one == [200, 401]

    # Sign out all remaining sessions for Lori
    sign_out_all = admin_client.post(
        f"/api/admin/users/{lori_id}/sign-out",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert sign_out_all.status_code == 200
    assert sign_out_all.json()["revoked_sessions"] == 1
    assert lori1.get("/api/threads").status_code == 401
    assert lori2.get("/api/threads").status_code == 401

    # Audit chain remains valid
    verify = admin_client.get("/api/admin/audit-logs/verify-chain")
    assert verify.status_code == 200
    assert verify.json()["valid"] is True
