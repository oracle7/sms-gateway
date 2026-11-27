import csv
import hashlib
import io
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import ensure_utc, utc_now
from models import AuditLog, User

_audit_lock = threading.Lock()


def _format_ts(dt: datetime) -> str:
    return ensure_utc(dt).isoformat()


def compute_audit_hash(prev_hash: str, fields: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash over prev_hash and audit row fields."""
    canonical = json.dumps(
        {"prev_hash": prev_hash, "fields": fields},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    outcome: str = "success",
    actor_user: Optional[User] = None,
    actor_username: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    commit: bool = True,
) -> AuditLog:
    """
    Appends an immutable, hash-chained audit record.
    Never pass message body, contact notes, or binary PHI in metadata/resource_id.
    """
    created_at = utc_now().replace(microsecond=0)
    resolved_user_id = actor_user.id if actor_user else None
    resolved_username = actor_user.username if actor_user else actor_username
    metadata_str = (
        json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if metadata
        else None
    )
    ua_trimmed = user_agent[:256] if user_agent else None

    with _audit_lock:
        last_row = db.query(AuditLog.row_hash).order_by(AuditLog.id.desc()).first()
        prev_hash = last_row[0] if last_row else "GENESIS"

        fields = {
            "created_at": _format_ts(created_at),
            "actor_user_id": resolved_user_id,
            "actor_username": resolved_username,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome": outcome,
            "ip_address": ip_address,
            "user_agent": ua_trimmed,
            "metadata_json": metadata_str,
        }
        row_hash = compute_audit_hash(prev_hash, fields)

        entry = AuditLog(
            created_at=created_at,
            actor_user_id=resolved_user_id,
            actor_username=resolved_username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            ip_address=ip_address,
            user_agent=ua_trimmed,
            metadata_json=metadata_str,
            prev_hash=prev_hash,
            row_hash=row_hash,
        )
        db.add(entry)
        if commit:
            db.commit()
            db.refresh(entry)
        else:
            db.flush()
        return entry


def verify_audit_chain(db: Session) -> Dict[str, Any]:
    """Verifies the entire SHA-256 hash chain from GENESIS to the latest audit row."""
    rows = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    expected_prev = "GENESIS"

    for row in rows:
        if row.prev_hash != expected_prev:
            return {
                "valid": False,
                "total_rows": len(rows),
                "first_broken_id": row.id,
                "error": f"Broken prev_hash link at audit_logs.id={row.id}",
            }

        fields = {
            "created_at": _format_ts(row.created_at),
            "actor_user_id": row.actor_user_id,
            "actor_username": row.actor_username,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "outcome": row.outcome,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "metadata_json": row.metadata_json,
        }
        expected_hash = compute_audit_hash(row.prev_hash, fields)
        if row.row_hash != expected_hash:
            return {
                "valid": False,
                "total_rows": len(rows),
                "first_broken_id": row.id,
                "error": f"Hash mismatch at audit_logs.id={row.id}",
            }
        expected_prev = row.row_hash

    return {
        "valid": True,
        "total_rows": len(rows),
        "first_broken_id": None,
        "error": None,
    }


def export_audit_logs_csv(rows: List[AuditLog]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "actor_user_id",
            "actor_username",
            "action",
            "resource_type",
            "resource_id",
            "outcome",
            "ip_address",
            "user_agent",
            "metadata_json",
            "prev_hash",
            "row_hash",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                _format_ts(r.created_at),
                r.actor_user_id if r.actor_user_id is not None else "",
                r.actor_username or "",
                r.action,
                r.resource_type,
                r.resource_id or "",
                r.outcome,
                r.ip_address or "",
                r.user_agent or "",
                r.metadata_json or "",
                r.prev_hash,
                r.row_hash,
            ]
        )
    return buf.getvalue()


def export_audit_logs_json(rows: List[AuditLog]) -> str:
    payload = [
        {
            "id": r.id,
            "created_at": _format_ts(r.created_at),
            "actor_user_id": r.actor_user_id,
            "actor_username": r.actor_username,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "outcome": r.outcome,
            "ip_address": r.ip_address,
            "user_agent": r.user_agent,
            "metadata_json": r.metadata_json,
            "prev_hash": r.prev_hash,
            "row_hash": r.row_hash,
        }
        for r in rows
    ]
    return json.dumps(payload, indent=2, ensure_ascii=True)
