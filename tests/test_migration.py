import sqlite3
import uuid

from scripts.migrate_v2_to_v3 import run_migration


def _build_synthetic_v2_db(db_path, media_dir):
    media_dir.mkdir(parents=True, exist_ok=True)
    img_path = media_dir / "19295551234_20260101_0.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE contacts (
            phone_number TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            notes TEXT
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            message_id TEXT UNIQUE,
            sender TEXT,
            recipient TEXT,
            body TEXT NOT NULL DEFAULT '',
            timestamp TEXT NOT NULL,
            is_sent INTEGER DEFAULT 0,
            is_delivered INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 0,
            is_failed INTEGER DEFAULT 0,
            is_cancelled INTEGER DEFAULT 0,
            web_viewed INTEGER DEFAULT 0,
            error_reason TEXT
        );
        CREATE TABLE message_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT
        );
        CREATE TABLE raw_webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT,
            payload TEXT NOT NULL
        );
        """
    )

    # Duplicate contact formats to test merge
    conn.execute("INSERT INTO contacts VALUES ('9295551234', 'Jane', 'Note A')")
    conn.execute("INSERT INTO contacts VALUES ('+19295551234', 'Jane Doe', 'Note B')")
    conn.execute("INSERT INTO contacts VALUES ('+22660', 'Pharmacy', NULL)")

    m1_id = str(uuid.uuid4())
    m2_id = str(uuid.uuid4())
    m3_id = str(uuid.uuid4())
    m4_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO messages VALUES (?, 'gw-1', '9295551234', '+19296141937', 'Hello doc', '2026-01-01 10:00:00', 0, 1, 0, 0, 0, 0, NULL)",
        (m1_id,),
    )
    conn.execute(
        "INSERT INTO messages VALUES (?, 'gw-2', '+19296141937', '+19295551234', 'See you at 2pm', '2026-01-01 10:05:00', 1, 1, 0, 0, 0, 1, NULL)",
        (m2_id,),
    )
    conn.execute(
        "INSERT INTO messages VALUES (?, NULL, '+22660', '+19296141937', 'Rx ready', '2026-01-01 10:10:00', 0, 1, 0, 0, 0, 1, NULL)",
        (m3_id,),
    )
    conn.execute(
        "INSERT INTO messages VALUES (?, NULL, 'unknown', '+19296141937', '', '2026-01-01 10:15:00', 0, 1, 0, 0, 0, 0, NULL)",
        (m4_id,),
    )

    conn.execute(
        "INSERT INTO message_attachments (message_id, filename, content_type) VALUES (?, ?, ?)",
        (m1_id, "/static/media/19295551234_20260101_0.jpg", "image/jpeg"),
    )
    conn.execute(
        "INSERT INTO message_attachments (message_id, filename, content_type) VALUES (?, ?, ?)",
        (m4_id, "/static/media/missing_file.png", "image/png"),
    )
    conn.commit()
    conn.close()


def test_v2_to_v3_migration_dry_run_and_lossless_cutover(tmp_path):
    v2_db = tmp_path / "sms_gateway_1937.db"
    v2_media = tmp_path / "v2_media"
    _build_synthetic_v2_db(v2_db, v2_media)

    v3_db = tmp_path / "data" / "sms_gateway_v3.db"
    v3_media = tmp_path / "data" / "media"
    backup_dir = tmp_path / "backups"

    dry = run_migration(
        source_db=v2_db,
        target_db=v3_db,
        source_media=v2_media,
        target_media=v3_media,
        did="+19296141937",
        backup_dir=backup_dir,
        dry_run=True,
    )
    assert dry.dry_run is True
    assert not v3_db.exists()
    assert dry.v2_contacts == 3
    assert dry.v3_contacts == 2
    assert len(dry.merged_duplicate_contacts) == 1
    assert dry.v2_messages == 4
    assert dry.copied_media_files == 1
    assert len(dry.missing_media_files) == 1

    real = run_migration(
        source_db=v2_db,
        target_db=v3_db,
        source_media=v2_media,
        target_media=v3_media,
        did="+19296141937",
        backup_dir=backup_dir,
        dry_run=False,
    )
    assert real.v3_messages == 4
    assert real.v3_attachments == 2
    assert real.threads_created == 3
    assert real.integrity_check == "ok"
    assert real.foreign_key_errors == 0
    assert real.audit_chain_valid is True
    assert (v3_media / "migrated" / "19295551234_20260101_0.jpg").is_file()
