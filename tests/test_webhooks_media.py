import base64
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from config import settings
from main import app
from models import RawWebhook
from tests.conftest import login_client


def test_webhook_hmac_verification(isolated_env, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_VERIFY_SIGNATURE", True)
    monkeypatch.setattr(settings, "WEBHOOK_SIGNING_KEY", "super-secret-pixel6-key")

    client = TestClient(app)
    body_bytes = json.dumps({"event": "sms:received", "payload": {"messageId": "h1", "sender": "+19295550001", "message": "Hi"}}).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(b"super-secret-pixel6-key", body_bytes + ts.encode("utf-8"), hashlib.sha256).hexdigest()

    # Invalid signature
    bad = client.post(
        "/webhook/inbound",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": "deadbeef"},
    )
    assert bad.status_code == 401

    # Stale timestamp
    old_ts = str(int(time.time()) - 1000)
    old_sig = hmac.new(b"super-secret-pixel6-key", body_bytes + old_ts.encode("utf-8"), hashlib.sha256).hexdigest()
    stale = client.post(
        "/webhook/inbound",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Timestamp": old_ts, "X-Signature": old_sig},
    )
    assert stale.status_code == 401

    # Valid signature
    ok = client.post(
        "/webhook/inbound",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": sig},
    )
    assert ok.status_code == 200


def test_mms_two_phase_unknown_sender_and_private_attachment(isolated_env):
    anon_client = TestClient(app)

    # Phase 1: mms:received
    r1 = anon_client.post(
        "/webhook/inbound",
        json={"event": "mms:received", "payload": {"messageId": "mms-1", "sender": "+19295556666"}},
    )
    assert r1.status_code == 200

    # Phase 2: mms:downloaded arrives with sender="unknown", text/plain part, smil part, and image
    img_bytes = b"\x89PNG\r\n\x1a\nfake-png-content-for-test"
    b64_img = base64.b64encode(img_bytes).decode("ascii")
    b64_txt = base64.b64encode(b"Foot photo attached").decode("ascii")
    b64_smil = base64.b64encode(b"<smil></smil>").decode("ascii")

    r2 = anon_client.post(
        "/webhook/inbound",
        json={
            "event": "mms:downloaded",
            "payload": {
                "messageId": "mms-1",
                "sender": "unknown",
                "attachments": [
                    {"contentType": "application/smil", "data": b64_smil},
                    {"contentType": "text/plain", "data": b64_txt},
                    {"contentType": "image/png", "name": "foot.png", "data": b64_img},
                ],
            },
        },
    )
    assert r2.status_code == 200

    # Verify raw_webhooks stripped base64 and healthy system:ping is not dumped
    anon_client.post("/health", json={"event": "system:ping", "payload": {"health": {"status": "pass", "checks": {"battery:level": {"observedValue": 92}}}}})
    db = isolated_env["SessionLocal"]()
    try:
        raws = db.query(RawWebhook).all()
        assert all(r.event_type != "system:ping" for r in raws)
        assert all(b64_img not in r.payload_sanitized for r in raws)
    finally:
        db.close()

    # Unauthenticated attachment access must fail with 401
    lori_client, _ = login_client("lori", "LoriStaffPass1234!")
    msgs = lori_client.get("/api/threads/+19295556666/messages").json()["items"]
    assert len(msgs) == 1
    assert msgs[0]["body"] == "Foot photo attached"
    assert len(msgs[0]["attachments"]) == 1
    att_url = msgs[0]["attachments"][0]["url"]

    assert anon_client.get(att_url).status_code == 401

    auth_att = lori_client.get(att_url)
    assert auth_att.status_code == 200
    assert auth_att.content == img_bytes
    assert auth_att.headers.get("x-content-type-options") == "nosniff"
    assert "no-store" in auth_att.headers.get("cache-control", "")
