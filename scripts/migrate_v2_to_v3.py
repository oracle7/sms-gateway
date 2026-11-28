import argparse
import hashlib
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import sessionmaker

from config import settings
from database import create_sqlite_engine, init_db, utc_now
from models import Contact, Message, MessageAttachment, Thread
from services.audit import record_audit, verify_audit_chain
from services.media import ensure_media_dir
from services.phone import normalize_contact_phone
from services.threads import recompute_thread_summary


@dataclass
class MigrationReport:
    dry_run: bool
    source_db: str
    target_db: str
    backup_path: Optional[str] = None
    v2_contacts: int = 0
    v3_contacts: int = 0
    merged_duplicate_contacts: List[str] = field(default_factory=list)
    v2_messages: int = 0
    v3_messages: int = 0
    v2_attachments: int = 0
    v3_attachments: int = 0
    copied_media_files: int = 0
    missing_media_files: List[str] = field(default_factory=list)
    threads_created: int = 0
    integrity_check: str = "not_run"
    foreign_key_errors: int = 0
    audit_chain_valid: bool = False


def _parse_v2_timestamp(raw_ts: Optional[str]) -> datetime:
    if not raw_ts:
        return utc_now()
    text = str(raw_ts).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for fmt in (None, "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return utc_now()


def _create_sqlite_backup(source_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{source_path.name}.bak.{stamp}"
    src_conn = sqlite3.connect(str(source_path))
    dst_conn = sqlite3.connect(str(backup_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return backup_path


def _extract_media_basename(v2_filename: str) -> str:
    cleaned = v2_filename.strip().replace("\\", "/")
    if cleaned.startswith("/static/media/"):
        cleaned = cleaned[len("/static/media/"):]
    elif cleaned.startswith("static/media/"):
        cleaned = cleaned[len("static/media/"):]
    return Path(cleaned).name


def run_migration(
    *,
    source_db: Path,
    target_db: Path,
    source_media: Path,
    target_media: Path,
    did: str,
    backup_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> MigrationReport:
    if not source_db.is_file():
        raise FileNotFoundError(f"Source database not found: {source_db}")

    if not dry_run and target_db.exists() and not force:
        raise FileExistsError(
            f"Target database already exists: {target_db}. Use --force to overwrite or choose a new path."
        )

    report = MigrationReport(
        dry_run=dry_run,
        source_db=str(source_db),
        target_db=str(target_db),
    )

    canonical_did = normalize_contact_phone(did)
    src_conn = sqlite3.connect(f"file:{source_db.resolve()}?mode=ro", uri=True)
    src_conn.row_factory = sqlite3.Row

    try:
        v2_contacts_rows = src_conn.execute("SELECT phone_number, name, notes FROM contacts").fetchall()
        v2_messages_rows = src_conn.execute(
            """
            SELECT id, message_id, sender, recipient, body, timestamp,
                   is_sent, is_delivered, is_read, is_failed, is_cancelled,
                   web_viewed, error_reason
            FROM messages
            ORDER BY timestamp ASC, id ASC
            """
        ).fetchall()
        v2_att_rows = src_conn.execute(
            "SELECT id, message_id, filename, content_type FROM message_attachments ORDER BY id ASC"
        ).fetchall()
    finally:
        src_conn.close()

    report.v2_contacts = len(v2_contacts_rows)
    report.v2_messages = len(v2_messages_rows)
    report.v2_attachments = len(v2_att_rows)

    # Deduplicate contacts by canonical phone_number
    merged_contacts: Dict[str, Tuple[str, Optional[str]]] = {}
    for row in v2_contacts_rows:
        canonical = normalize_contact_phone(row["phone_number"])
        name = (row["name"] or "").strip() or canonical
        notes = (row["notes"] or "").strip() or None
        if canonical not in merged_contacts:
            merged_contacts[canonical] = (name, notes)
        else:
            report.merged_duplicate_contacts.append(f"{row['phone_number']} -> {canonical}")
            prev_name, prev_notes = merged_contacts[canonical]
            best_name = prev_name if len(prev_name) >= len(name) else name
            if prev_notes and notes and notes not in prev_notes:
                best_notes = f"{prev_notes}\n---\n{notes}"
            else:
                best_notes = prev_notes or notes
            merged_contacts[canonical] = (best_name, best_notes)

    report.v3_contacts = len(merged_contacts)

    # Check attachments on disk
    for att in v2_att_rows:
        basename = _extract_media_basename(att["filename"])
        src_file = source_media / basename
        if src_file.is_file():
            report.copied_media_files += 1
        else:
            report.missing_media_files.append(str(att["filename"]))

    if dry_run:
        distinct_phones = set()
        for m in v2_messages_rows:
            s_norm = normalize_contact_phone(m["sender"])
            r_norm = normalize_contact_phone(m["recipient"])
            is_outbound = s_norm == canonical_did
            c_phone = r_norm if is_outbound else s_norm
            distinct_phones.add(c_phone)
        report.v3_messages = report.v2_messages
        report.v3_attachments = report.v2_attachments
        report.threads_created = len(distinct_phones)
        return report

    # Real migration
    report.backup_path = str(_create_sqlite_backup(source_db, backup_dir))
    if target_db.exists() and force:
        target_db.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(target_db) + suffix)
            if sidecar.exists():
                sidecar.unlink()

    ensure_media_dir(target_media)
    migrated_media_dir = target_media / "migrated"
    migrated_media_dir.mkdir(parents=True, exist_ok=True)

    target_url = f"sqlite:///{target_db.resolve()}"
    eng = create_sqlite_engine(target_url)
    init_db(eng)
    Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True)

    db = Session()
    try:
        # 1. Insert Contacts
        now = utc_now()
        for canonical, (name, notes) in merged_contacts.items():
            db.add(
                Contact(
                    phone_number=canonical,
                    name=name,
                    notes=notes,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.flush()

        # 2. Insert Threads & Messages
        created_threads: set[str] = set()
        seen_gateway_ids: set[str] = set()

        for m in v2_messages_rows:
            s_norm = normalize_contact_phone(m["sender"])
            r_norm = normalize_contact_phone(m["recipient"])

            if s_norm == canonical_did:
                direction = "outbound"
                contact_phone = r_norm
            elif r_norm == canonical_did or s_norm != "unknown":
                direction = "inbound"
                contact_phone = s_norm
            else:
                direction = "inbound"
                contact_phone = "unknown"

            if contact_phone not in created_threads:
                db.add(Thread(contact_phone=contact_phone, created_at=now, updated_at=now))
                db.flush()
                created_threads.add(contact_phone)

            msg_ts = _parse_v2_timestamp(m["timestamp"])
            is_sent = bool(m["is_sent"])
            is_delivered = bool(m["is_delivered"])
            is_failed = bool(m["is_failed"])
            is_cancelled = bool(m["is_cancelled"])

            if direction == "inbound":
                status_val = "received"
                read_at = msg_ts if bool(m["web_viewed"]) else None
            else:
                if is_failed:
                    status_val = "failed"
                elif is_cancelled:
                    status_val = "cancelled"
                elif is_delivered:
                    status_val = "delivered"
                elif is_sent:
                    status_val = "sent"
                else:
                    status_val = "queued"
                read_at = msg_ts

            gw_id = str(m["message_id"]).strip() if m["message_id"] else None
            if gw_id and gw_id in seen_gateway_ids:
                gw_id = None
            if gw_id:
                seen_gateway_ids.add(gw_id)

            msg_id = str(m["id"]) if m["id"] else str(uuid.uuid4())
            db.add(
                Message(
                    id=msg_id,
                    gateway_message_id=gw_id,
                    contact_phone=contact_phone,
                    direction=direction,
                    sender=s_norm,
                    recipient=r_norm,
                    body=m["body"] or "",
                    timestamp=msg_ts,
                    sent_by_user_id=None,
                    status=status_val,
                    is_sent=is_sent,
                    is_delivered=is_delivered,
                    is_failed=is_failed,
                    is_cancelled=is_cancelled,
                    error_reason=m["error_reason"],
                    read_at=read_at,
                )
            )
        db.flush()

        # 3. Insert Attachments & Copy Media Files
        for att in v2_att_rows:
            basename = _extract_media_basename(att["filename"])
            src_file = source_media / basename
            storage_key = f"migrated/{basename}"
            size_bytes = None
            sha256_hex = None
            if src_file.is_file():
                dst_file = migrated_media_dir / basename
                shutil.copy2(src_file, dst_file)
                raw = dst_file.read_bytes()
                size_bytes = len(raw)
                sha256_hex = hashlib.sha256(raw).hexdigest()

            db.add(
                MessageAttachment(
                    message_id=str(att["message_id"]),
                    storage_key=storage_key,
                    original_filename=basename,
                    content_type=(att["content_type"] or "application/octet-stream").strip(),
                    size_bytes=size_bytes,
                    sha256=sha256_hex,
                    created_at=now,
                )
            )
        db.flush()

        # 4. Recompute Thread Summaries
        for phone in created_threads:
            recompute_thread_summary(db, phone)

        # 5. Record Genesis Audit Entry
        record_audit(
            db,
            action="system.migration_v2_to_v3",
            resource_type="database",
            resource_id=target_db.name,
            actor_username="migration_cli",
            metadata={
                "v2_contacts": report.v2_contacts,
                "v3_contacts": report.v3_contacts,
                "v2_messages": report.v2_messages,
                "v2_attachments": report.v2_attachments,
                "missing_media_count": len(report.missing_media_files),
            },
            commit=False,
        )
        db.commit()

        # 6. Reconciliation & Integrity Assertions
        report.v3_messages = db.query(Message).count()
        report.v3_attachments = db.query(MessageAttachment).count()
        report.threads_created = db.query(Thread).count()
        chain_check = verify_audit_chain(db)
        report.audit_chain_valid = bool(chain_check["valid"])
    finally:
        db.close()
        eng.dispose()

    check_conn = sqlite3.connect(str(target_db))
    try:
        report.integrity_check = check_conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_rows = check_conn.execute("PRAGMA foreign_key_check").fetchall()
        report.foreign_key_errors = len(fk_rows)
    finally:
        check_conn.close()

    assert report.v3_messages == report.v2_messages, (
        f"Message count mismatch: v2={report.v2_messages}, v3={report.v3_messages}"
    )
    assert report.v3_attachments == report.v2_attachments, (
        f"Attachment count mismatch: v2={report.v2_attachments}, v3={report.v3_attachments}"
    )
    assert report.v3_contacts + len(report.merged_duplicate_contacts) == report.v2_contacts, (
        "Contact reconciliation mismatch"
    )
    assert report.integrity_check == "ok", f"SQLite integrity_check failed: {report.integrity_check}"
    assert report.foreign_key_errors == 0, f"Foreign key errors: {report.foreign_key_errors}"
    assert report.audit_chain_valid, "Audit hash chain verification failed"

    return report


def print_report(report: MigrationReport) -> None:
    mode = "DRY-RUN PREVIEW" if report.dry_run else "COMPLETED"
    print(f"=== SMS Gateway v2 -> v3 Migration ({mode}) ===")
    print(f"Source DB:          {report.source_db}")
    print(f"Target DB:          {report.target_db}")
    if report.backup_path:
        print(f"Backup created:     {report.backup_path}")
    print(f"Contacts:           {report.v2_contacts} (v2) -> {report.v3_contacts} (v3), merged={len(report.merged_duplicate_contacts)}")
    for merged in report.merged_duplicate_contacts:
        print(f"  - merged duplicate contact: {merged}")
    print(f"Messages:           {report.v2_messages} (v2) -> {report.v3_messages} (v3)")
    print(f"Threads created:    {report.threads_created}")
    print(f"Attachments:        {report.v2_attachments} (v2) -> {report.v3_attachments} (v3)")
    print(f"Media files found:  {report.copied_media_files}")
    if report.missing_media_files:
        print(f"Missing media ({len(report.missing_media_files)}):")
        for item in report.missing_media_files:
            print(f"  - {item}")
    if not report.dry_run:
        print(f"SQLite integrity:   {report.integrity_check}")
        print(f"Foreign key errors: {report.foreign_key_errors}")
        print(f"Audit chain valid:  {report.audit_chain_valid}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate production v2 SQLite DB to v3.0 schema losslessly.")
    parser.add_argument("--source", required=True, help="Path to existing v2 SQLite DB (e.g. sms_gateway_1937.db)")
    parser.add_argument("--target", required=True, help="Path to new v3 SQLite DB (e.g. ./data/sms_gateway_v3.db)")
    parser.add_argument("--source-media", default="static/media", help="Path to v2 media directory")
    parser.add_argument("--target-media", default=settings.MEDIA_DIR, help="Path to private v3 media directory")
    parser.add_argument("--did", default=settings.SMS_DID, help="Clinic DID phone number")
    parser.add_argument("--backup-dir", default="./backups", help="Directory for pre-migration SQLite backups")
    parser.add_argument("--dry-run", action="store_true", help="Analyze v2 DB without writing files")
    parser.add_argument("--force", action="store_true", help="Overwrite target DB if it already exists")
    args = parser.parse_args()

    try:
        report = run_migration(
            source_db=Path(args.source),
            target_db=Path(args.target),
            source_media=Path(args.source_media),
            target_media=Path(args.target_media),
            did=args.did,
            backup_dir=Path(args.backup_dir),
            dry_run=args.dry_run,
            force=args.force,
        )
        print_report(report)
        return 0
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
