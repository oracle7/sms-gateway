import sqlite3
import pytest
from sqlalchemy import text

from models import AuditLog
from services.audit import verify_audit_chain
from tests.conftest import login_client


def test_audit_immutability_triggers_and_chain(isolated_env):
    admin_client, admin_csrf = login_client("doctor", "DoctorPass1234!")
    res = admin_client.post(
        "/api/contacts/",
        headers={"X-CSRF-Token": admin_csrf},
        json={"phone_number": "9295552222", "name": "Bob Patient"},
    )
    assert res.status_code == 200

    verify = admin_client.get("/api/admin/audit-logs/verify-chain")
    assert verify.status_code == 200
    assert verify.json()["valid"] is True
    assert verify.json()["total_rows"] >= 2

    # Direct SQLite UPDATE/DELETE must be aborted by triggers
    conn = sqlite3.connect(str(isolated_env["db_file"]))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE audit_logs SET action = 'tampered' WHERE id = 1")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM audit_logs WHERE id = 1")
    finally:
        conn.close()


def test_audit_export_csv_and_json_without_phi(isolated_env):
    admin_client, admin_csrf = login_client("doctor", "DoctorPass1234!")
    # Send an inbound webhook with sensitive text; verify body is NOT in audit_logs
    secret_phi = "Patient has severe plantar fasciitis on left heel"
    admin_client.post(
        "/webhook/inbound",
        json={"event": "sms:received", "payload": {"messageId": "m-phi-1", "sender": "+19295553333", "message": secret_phi}},
    )
    admin_client.post("/api/threads/+19295553333/mark-read", headers={"X-CSRF-Token": admin_csrf})

    csv_res = admin_client.get("/api/admin/audit-logs/export?format=csv")
    assert csv_res.status_code == 200
    assert secret_phi not in csv_res.text

    json_res = admin_client.get("/api/admin/audit-logs/export?format=json")
    assert json_res.status_code == 200
    assert "admin.audit_exported" in json_res.text

    db = isolated_env["SessionLocal"]()
    try:
        assert verify_audit_chain(db)["valid"] is True
        all_rows = db.query(AuditLog).all()
        assert all(secret_phi not in (r.metadata_json or "") for r in all_rows)
    finally:
        db.close()
