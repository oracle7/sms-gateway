from datetime import timedelta
from unittest.mock import AsyncMock

from database import utc_now
from models import Message, Thread
from routers import messages as messages_router
from services.threads import recompute_thread_summary
from tests.conftest import login_client


def test_threads_pagination_beyond_500_cap(isolated_env):
    SessionLocal = isolated_env["SessionLocal"]
    db = SessionLocal()
    now = utc_now()
    try:
        # Insert 60 threads with 11 messages each = 660 messages (> 500 v2 cap!)
        for i in range(60):
            phone = f"+1929555{i:04d}"
            db.add(Thread(contact_phone=phone, created_at=now, updated_at=now))
        db.flush()
        for i in range(60):
            phone = f"+1929555{i:04d}"
            for j in range(11):
                db.add(
                    Message(
                        contact_phone=phone,
                        direction="inbound",
                        sender=phone,
                        recipient="+19296141937",
                        body=f"Msg {j} for thread {i}",
                        timestamp=now - timedelta(minutes=(60 - i) * 20 + (11 - j)),
                        status="received",
                        is_delivered=True,
                    )
                )
        db.commit()
        for i in range(60):
            recompute_thread_summary(db, f"+1929555{i:04d}")
        db.commit()
    finally:
        db.close()

    staff_client, _ = login_client("lori", "LoriStaffPass1234!")
    page1 = staff_client.get("/api/threads?status=active&limit=50&offset=0").json()
    assert page1["total"] == 60
    assert len(page1["items"]) == 50
    assert page1["has_more"] is True

    page2 = staff_client.get("/api/threads?status=active&limit=50&offset=50").json()
    assert len(page2["items"]) == 10
    assert page2["has_more"] is False


def test_send_sms_records_sender_and_shared_mark_read(isolated_env, monkeypatch):
    monkeypatch.setattr(messages_router, "send_sms_to_gateway", AsyncMock(return_value="gw-out-1"))

    lori_client, lori_csrf = login_client("lori", "LoriStaffPass1234!")
    send_res = lori_client.post(
        "/api/messages/",
        headers={"X-CSRF-Token": lori_csrf},
        json={"recipient": "(929) 555-7777", "body": "Your appointment is confirmed."},
    )
    assert send_res.status_code == 200
    msg = send_res.json()
    assert msg["contact_phone"] == "+19295557777"
    assert msg["direction"] == "outbound"
    assert msg["sent_by_display_name"] == "Lori"

    # Inbound reply arrives
    lori_client.post(
        "/webhook/inbound",
        json={"event": "sms:received", "payload": {"messageId": "gw-in-1", "sender": "+19295557777", "message": "Thank you!"}},
    )

    doc_client, doc_csrf = login_client("doctor", "DoctorPass1234!")
    threads_before = doc_client.get("/api/threads").json()
    assert threads_before["total_unread_active"] == 1

    # Doctor marks read -> shared unread drops to 0 for Lori too
    mr = doc_client.post("/api/threads/+19295557777/mark-read", headers={"X-CSRF-Token": doc_csrf})
    assert mr.status_code == 200
    assert mr.json()["unread_count"] == 0

    threads_after = lori_client.get("/api/threads").json()
    assert threads_after["total_unread_active"] == 0
