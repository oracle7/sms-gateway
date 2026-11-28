from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from config import settings
from database import get_db, utc_now
from models import AuditLog, User, UserSession
from schemas import (
    AdminResetPasswordRequest,
    AdminSessionPublic,
    AdminUserCreate,
    AdminUserUpdate,
    AuditChainVerifyResponse,
    AuditLogPageResponse,
    AuditLogResponse,
    UserPublic,
)
from services.audit import (
    export_audit_logs_csv,
    export_audit_logs_json,
    record_audit,
    verify_audit_chain,
)
from services.auth import (
    AuthContext,
    extract_client_ip,
    require_admin,
    require_admin_csrf,
)
from services.broadcaster import broadcaster
from services.security import hash_password, validate_password_strength

router = APIRouter()


def _revoke_user_sessions(db: Session, user_id: int, reason: str) -> List[str]:
    now = utc_now()
    active = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .all()
    )
    revoked_ids = []
    for sess in active:
        sess.revoked_at = now
        sess.revoked_reason = reason
        revoked_ids.append(sess.id)
    return revoked_ids


@router.get("/users", response_model=List[UserPublic])
def list_users(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(User).order_by(User.id.asc()).all()
    return [UserPublic.model_validate(u) for u in rows]


@router.post("/users", response_model=UserPublic)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    username = payload.username.strip().lower()
    if not username or " " in username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username cannot contain spaces.")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists.")

    try:
        validate_password_strength(payload.password, settings.MIN_PASSWORD_LENGTH)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user = User(
        username=username,
        display_name=payload.display_name.strip(),
        role=payload.role,
        password_hash=hash_password(payload.password),
        must_change_password=payload.must_change_password,
        is_active=True,
    )
    db.add(user)
    db.flush()

    record_audit(
        db,
        action="admin.user_created",
        resource_type="user",
        resource_id=str(user.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"target_username": user.username, "role": user.role},
        commit=False,
    )
    db.commit()
    db.refresh(user)
    return UserPublic.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    active_admins_count = (
        db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
    )
    is_target_last_admin = target.role == "admin" and target.is_active and active_admins_count <= 1
    if is_target_last_admin and (payload.is_active is False or payload.role == "staff"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable or demote the last active administrator.",
        )

    changes = {}
    if payload.display_name is not None:
        target.display_name = payload.display_name.strip()
        changes["display_name"] = target.display_name
    if payload.role is not None and payload.role != target.role:
        target.role = payload.role
        changes["role"] = target.role
    if payload.is_active is not None and payload.is_active != target.is_active:
        target.is_active = payload.is_active
        changes["is_active"] = target.is_active

    revoked_ids: List[str] = []
    if target.is_active is False:
        revoked_ids = _revoke_user_sessions(db, target.id, "account_disabled")

    record_audit(
        db,
        action="admin.user_updated",
        resource_type="user",
        resource_id=str(target.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"target_username": target.username, "changes": changes},
        commit=False,
    )
    db.commit()
    db.refresh(target)

    for sid in revoked_ids:
        await broadcaster.disconnect_session(sid, reason="account_disabled")

    return UserPublic.model_validate(target)


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    payload: AdminResetPasswordRequest,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    try:
        validate_password_strength(payload.new_password, settings.MIN_PASSWORD_LENGTH)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    target.password_hash = hash_password(payload.new_password)
    target.must_change_password = payload.must_change_password
    target.failed_login_attempts = 0
    target.locked_until = None
    revoked_ids = _revoke_user_sessions(db, target.id, "admin_password_reset")

    record_audit(
        db,
        action="admin.user_password_reset",
        resource_type="user",
        resource_id=str(target.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"target_username": target.username, "revoked_sessions": len(revoked_ids)},
        commit=False,
    )
    db.commit()

    for sid in revoked_ids:
        await broadcaster.disconnect_session(sid, reason="admin_password_reset")

    return {"status": "password_reset", "revoked_sessions": len(revoked_ids)}


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: int,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    target.failed_login_attempts = 0
    target.locked_until = None

    record_audit(
        db,
        action="admin.user_unlocked",
        resource_type="user",
        resource_id=str(target.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"target_username": target.username},
        commit=False,
    )
    db.commit()
    return {"status": "unlocked", "username": target.username}


@router.post("/users/{user_id}/sign-out")
async def sign_out_user(
    user_id: int,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    """Revokes all active sessions for the specified user."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    revoked_ids = _revoke_user_sessions(db, target.id, "admin_revoked")
    record_audit(
        db,
        action="admin.session_revoked",
        resource_type="user",
        resource_id=str(target.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"target_username": target.username, "revoked_sessions": len(revoked_ids)},
        commit=False,
    )
    db.commit()

    for sid in revoked_ids:
        await broadcaster.disconnect_session(sid, reason="admin_revoked")

    return {"status": "signed_out", "revoked_sessions": len(revoked_ids)}


@router.get("/sessions", response_model=List[AdminSessionPublic])
def list_active_sessions(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Lists all non-revoked, non-expired sessions across all users."""
    now = utc_now()
    rows = (
        db.query(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .filter(UserSession.revoked_at.is_(None), UserSession.expires_at > now)
        .order_by(UserSession.last_activity_at.desc())
        .all()
    )
    return [
        AdminSessionPublic(
            id=sess.id,
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            ip_address=sess.ip_address,
            user_agent=sess.user_agent,
            created_at=sess.created_at,
            last_activity_at=sess.last_activity_at,
            expires_at=sess.expires_at,
            is_current=(sess.id == auth.session.id),
        )
        for sess, user in rows
    ]


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: str,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    """Revokes a single active session by ID."""
    sess = (
        db.query(UserSession)
        .filter(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .first()
    )
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active session not found.")

    sess.revoked_at = utc_now()
    sess.revoked_reason = "admin_revoked"
    record_audit(
        db,
        action="admin.session_revoked",
        resource_type="session",
        resource_id=sess.id,
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"target_user_id": sess.user_id},
        commit=False,
    )
    db.commit()

    await broadcaster.disconnect_session(sess.id, reason="admin_revoked")
    return {"status": "revoked", "session_id": sess.id}


def _build_audit_query(
    db: Session,
    action: Optional[str],
    actor_username: Optional[str],
    outcome: Optional[str],
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
):
    query = db.query(AuditLog)
    if action and action.strip():
        query = query.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if actor_username and actor_username.strip():
        query = query.filter(AuditLog.actor_username.ilike(f"%{actor_username.strip()}%"))
    if outcome and outcome.strip():
        query = query.filter(AuditLog.outcome == outcome.strip())
    if from_dt:
        query = query.filter(AuditLog.created_at >= from_dt)
    if to_dt:
        query = query.filter(AuditLog.created_at <= to_dt)
    return query


@router.get("/audit-logs", response_model=AuditLogPageResponse)
def get_audit_logs(
    action: Optional[str] = None,
    actor_username: Optional[str] = None,
    outcome: Optional[Literal["success", "failure"]] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _build_audit_query(db, action, actor_username, outcome, from_dt, to_dt)
    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    return AuditLogPageResponse(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/audit-logs/export")
def export_audit_logs(
    request: Request,
    fmt: Literal["csv", "json"] = Query("csv", alias="format"),
    action: Optional[str] = None,
    actor_username: Optional[str] = None,
    outcome: Optional[Literal["success", "failure"]] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = _build_audit_query(db, action, actor_username, outcome, from_dt, to_dt)
    rows = query.order_by(AuditLog.id.asc()).limit(50000).all()

    record_audit(
        db,
        action="admin.audit_exported",
        resource_type="audit_logs",
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"format": fmt, "exported_count": len(rows)},
    )

    if fmt == "json":
        content = export_audit_logs_json(rows)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="audit_logs.json"'},
        )

    content = export_audit_logs_csv(rows)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )


@router.get("/audit-logs/verify-chain", response_model=AuditChainVerifyResponse)
def verify_chain_endpoint(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = verify_audit_chain(db)
    return AuditChainVerifyResponse(**result)
