from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from config import settings
from database import ensure_utc, get_db, utc_now
from models import User, UserSession
from schemas import (
    ChangePasswordRequest,
    HeartbeatResponse,
    LoginRequest,
    MeResponse,
    SessionPublic,
    UserPublic,
)
from services.audit import record_audit
from services.auth import (
    AuthContext,
    extract_client_ip,
    require_auth,
    require_auth_no_refresh,
    require_csrf,
)
from services.broadcaster import broadcaster
from services.security import (
    check_needs_rehash,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from version import APP_VERSION, BUILD_ID

router = APIRouter()


@router.post("/login", response_model=MeResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    username = payload.username.strip().lower()
    ip_addr = extract_client_ip(request)
    user_agent = request.headers.get("user-agent")
    now = utc_now()

    user = db.query(User).filter(User.username == username).first()
    if not user:
        record_audit(
            db,
            action="auth.login_failed",
            resource_type="user",
            resource_id=username,
            outcome="failure",
            actor_username=username,
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"reason": "unknown_username"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    if not user.is_active:
        record_audit(
            db,
            action="auth.login_failed",
            resource_type="user",
            resource_id=str(user.id),
            outcome="failure",
            actor_user=user,
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"reason": "account_disabled"},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been disabled.")

    locked_until = ensure_utc(user.locked_until)
    if locked_until and locked_until > now:
        record_audit(
            db,
            action="auth.login_failed",
            resource_type="user",
            resource_id=str(user.id),
            outcome="failure",
            actor_user=user,
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"reason": "account_locked"},
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account temporarily locked due to too many failed attempts. Please try again later.",
        )

    if not verify_password(user.password_hash, payload.password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            record_audit(
                db,
                action="auth.account_locked",
                resource_type="user",
                resource_id=str(user.id),
                outcome="failure",
                actor_user=user,
                ip_address=ip_addr,
                user_agent=user_agent,
                metadata={"failed_attempts": user.failed_login_attempts},
                commit=False,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account temporarily locked due to too many failed attempts. Please try again later.",
            )

        record_audit(
            db,
            action="auth.login_failed",
            resource_type="user",
            resource_id=str(user.id),
            outcome="failure",
            actor_user=user,
            ip_address=ip_addr,
            user_agent=user_agent,
            metadata={"reason": "bad_password", "failed_attempts": user.failed_login_attempts},
            commit=False,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    if check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now

    raw_token, token_hash = generate_session_token()
    csrf_token = generate_csrf_token()
    expires_at = now + timedelta(hours=settings.SESSION_MAX_AGE_HOURS)
    session = UserSession(
        user_id=user.id,
        token_hash=token_hash,
        csrf_token=csrf_token,
        ip_address=ip_addr,
        user_agent=user_agent[:256] if user_agent else None,
        created_at=now,
        last_activity_at=now,
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()

    record_audit(
        db,
        action="auth.login_success",
        resource_type="session",
        resource_id=session.id,
        actor_user=user,
        ip_address=ip_addr,
        user_agent=user_agent,
        commit=False,
    )
    db.commit()
    db.refresh(user)

    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
        max_age=settings.SESSION_MAX_AGE_HOURS * 3600,
    )

    idle_expires = now + timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
    return MeResponse(
        user=UserPublic.model_validate(user),
        csrf_token=csrf_token,
        idle_expires_at=idle_expires,
        idle_timeout_seconds=settings.SESSION_IDLE_TIMEOUT_MINUTES * 60,
        build_id=BUILD_ID,
        app_version=APP_VERSION,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    now = utc_now()
    auth.session.revoked_at = now
    auth.session.revoked_reason = "logout"
    record_audit(
        db,
        action="auth.logout",
        resource_type="session",
        resource_id=auth.session.id,
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        commit=False,
    )
    db.commit()

    await broadcaster.disconnect_session(auth.session.id, reason="logout")
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
def get_me(auth: AuthContext = Depends(require_auth_no_refresh)):
    last_act = ensure_utc(auth.session.last_activity_at) or utc_now()
    idle_expires = last_act + timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
    return MeResponse(
        user=UserPublic.model_validate(auth.user),
        csrf_token=auth.session.csrf_token,
        idle_expires_at=idle_expires,
        idle_timeout_seconds=settings.SESSION_IDLE_TIMEOUT_MINUTES * 60,
        build_id=BUILD_ID,
        app_version=APP_VERSION,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    now = utc_now()
    auth.session.last_activity_at = now
    db.commit()
    return HeartbeatResponse(
        idle_expires_at=now + timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES),
        idle_timeout_seconds=settings.SESSION_IDLE_TIMEOUT_MINUTES * 60,
    )


@router.get("/sessions", response_model=List[SessionPublic])
def list_my_sessions(
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == auth.user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_activity_at.desc())
        .all()
    )
    return [
        SessionPublic(
            id=r.id,
            ip_address=r.ip_address,
            user_agent=r.user_agent,
            created_at=r.created_at,
            last_activity_at=r.last_activity_at,
            expires_at=r.expires_at,
            is_current=(r.id == auth.session.id),
        )
        for r in rows
    ]


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if not verify_password(auth.user.password_hash, payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")

    try:
        validate_password_strength(payload.new_password, settings.MIN_PASSWORD_LENGTH)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    now = utc_now()
    auth.user.password_hash = hash_password(payload.new_password)
    auth.user.must_change_password = False

    revoked_ids = []
    if payload.revoke_other_sessions:
        others = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == auth.user.id,
                UserSession.revoked_at.is_(None),
                UserSession.id != auth.session.id,
            )
            .all()
        )
        for sess in others:
            sess.revoked_at = now
            sess.revoked_reason = "password_changed"
            revoked_ids.append(sess.id)

    record_audit(
        db,
        action="auth.password_changed",
        resource_type="user",
        resource_id=str(auth.user.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"revoked_other_sessions": len(revoked_ids)},
        commit=False,
    )
    db.commit()

    for sid in revoked_ids:
        await broadcaster.disconnect_session(sid, reason="password_changed")

    return {"status": "password_updated"}
