from tests.conftest import login_client


def test_archive_auto_reopen_and_message_soft_delete(isolated_env):
    lori_client, lori_csrf = login_client("lori", "LoriStaffPass1234!")
    doc_client, doc_csrf = login_client("doctor", "DoctorPass1234!")

    # Two inbound messages arrive
    r1 = lori_client.post(
        "/webhook/inbound",
        json={"event": "sms:received", "payload": {"messageId": "sd-1", "sender": "+19295558888", "message": "First"}},
    )
    r2 = lori_client.post(
        "/webhook/inbound",
        json={"event": "sms:received", "payload": {"messageId": "sd-2", "sender": "+19295558888", "message": "Second"}},
    )
    msg1_id = r1.json()["id"]

    # Lori hides msg1
    hide_res = lori_client.post(f"/api/messages/{msg1_id}/hide", headers={"X-CSRF-Token": lori_csrf})
    assert hide_res.status_code == 200

    # Lori archives the thread
    arch_res = lori_client.post("/api/threads/+19295558888/archive", headers={"X-CSRF-Token": lori_csrf})
    assert arch_res.status_code == 200
    assert doc_client.get("/api/threads?status=active").json()["total"] == 0
    assert doc_client.get("/api/threads?status=archived").json()["total"] == 1

    # New inbound message arrives -> thread automatically reopens to active inbox,
    # while msg1 remains hidden from normal view
    lori_client.post(
        "/webhook/inbound",
        json={"event": "sms:received", "payload": {"messageId": "sd-3", "sender": "+19295558888", "message": "Third"}},
    )
    assert lori_client.get("/api/threads?status=active").json()["total"] == 1

    msgs_staff = lori_client.get("/api/threads/+19295558888/messages").json()["items"]
    assert [m["body"] for m in msgs_staff] == ["Second", "Third"]

    # Staff cannot restore hidden message; admin can
    assert lori_client.post(f"/api/messages/{msg1_id}/restore", headers={"X-CSRF-Token": lori_csrf}).status_code == 403
    assert doc_client.post(f"/api/messages/{msg1_id}/restore", headers={"X-CSRF-Token": doc_csrf}).status_code == 200

    msgs_after = lori_client.get("/api/threads/+19295558888/messages").json()["items"]
    assert [m["body"] for m in msgs_after] == ["First", "Second", "Third"]


def test_contact_soft_delete_and_restore(isolated_env):
    lori_client, lori_csrf = login_client("lori", "LoriStaffPass1234!")
    created = lori_client.post(
        "/api/contacts/",
        headers={"X-CSRF-Token": lori_csrf},
        json={"phone_number": "9295554444", "name": "Mary"},
    ).json()

    del_res = lori_client.delete(f"/api/contacts/{created['id']}", headers={"X-CSRF-Token": lori_csrf})
    assert del_res.status_code == 200
    assert lori_client.get("/api/contacts/").json() == []
    assert len(lori_client.get("/api/contacts/?include_deleted=true").json()) == 1

    rest_res = lori_client.post(f"/api/contacts/{created['id']}/restore", headers={"X-CSRF-Token": lori_csrf})
    assert rest_res.status_code == 200
    assert len(lori_client.get("/api/contacts/").json()) == 1
