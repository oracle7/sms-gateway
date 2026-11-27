import asyncio
import hmac
import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import settings
from database import ensure_utc, get_db, utc_now
from models import User, UserSession
from services.audit import record_audit
from services.security import hash_token, verify_webhook_signature

logger = logging.getLogger("uvicorn.error")


@dataclass
class AuthContext:
    user: User
    session: UserSession


def extract_client_ip(request: Request) -> str:
    """
    Returns the client IP address. Trusts X-Forwarded-For / X-Real-IP ONLY when
    the immediate socket peer is in TRUSTED_PROXY_IPS.
    """
    peer_ip = request.client.host if request.client else ""
    if peer_ip in settings.trusted_proxy_list:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            candidate = xff.split(",")[0].strip()
            if candidate:
                return candidate
        x_real_ip = request.headers.get("x-real-ip", "").strip()
        if x_real_ip:
            return x_real_ip
    return peer_ip or "unknown"


def _resolve_session(
    request: Request,
    db: Session,
    *,
    refresh_activity: bool,
) -> Optional[AuthContext]:
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        return None

    token_hash = hash_token(raw_token)
    session = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not session or session.revoked_at is not None:
        return None

    now = utc_now()
    expires_at = ensure_utc(session.expires_at)
    last_activity = ensure_utc(session.last_activity_at)
    idle_delta = timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        session.revoked_at = now
        session.revoked_reason = "user_inactive"
        db.commit()
        return None

    if expires_at and now > expires_at:
        session.revoked_at = now
        session.revoked_reason = "absolute_timeout"
        record_audit(
            db,
            action="auth.session_timeout",
            resource_type="session",
            resource_id=session.id,
            actor_user=user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "absolute_timeout"},
            commit=False,
        )
        db.commit()
        return None

    if last_activity and (now - last_activity) > idle_delta:
        session.revoked_at = now
        session.revoked_reason = "idle_timeout"
        record_audit(
            db,
            action="auth.session_timeout",
            resource_type="session",
            resource_id=session.id,
            actor_user=user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            metadata={"reason": "idle_timeout"},
            commit=False,
        )
        db.commit()
        return None

    is_background_sync = request.headers.get("x-background-sync") == "1"
    if refresh_activity and not is_background_sync:
        session.last_activity_at = now
        db.commit()

    return AuthContext(user=user, session=session)


def get_optional_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[AuthContext]:
    return _resolve_session(request, db, refresh_activity=False)


def require_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthContext:
    ctx = _resolve_session(request, db, refresh_activity=True)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required or session expired.",
        )
    return ctx


def require_auth_no_refresh(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthContext:
    ctx = _resolve_session(request, db, refresh_activity=False)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required or session expired.",
        )
    return ctx


def require_csrf(
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Requires a valid X-CSRF-Token header matching the active session."""
    provided = request.headers.get("x-csrf-token", "")
    if not provided or not hmac.compare_digest(provided, auth.session.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token.",
        )
    return auth


def require_admin(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    if auth.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required.",
        )
    return auth


def require_admin_csrf(
    auth: AuthContext = Depends(require_csrf),
) -> AuthContext:
    if auth.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required.",
        )
    return auth


async def verify_webhook_access(request: Request) -> Tuple[bytes, bool]:
    """
    Validates incoming Pixel 6 webhook requests via optional IP allowlist and
    HMAC-SHA256 signature verification (when WEBHOOK_VERIFY_SIGNATURE=true).
    """
    allowed_nets = settings.webhook_allowed_networks
    if allowed_nets:
        client_ip_str = extract_client_ip(request)
        try:
            client_ip = ipaddress.ip_address(client_ip_str)
            if not any(client_ip in net for net in allowed_nets):
                logger.warning(f"Rejected webhook from unauthorized IP: {client_ip_str}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden webhook source")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden webhook source")

    raw_body = await request.body()
    if settings.WEBHOOK_VERIFY_SIGNATURE:
        valid, reason = verify_webhook_signature(
            raw_body=raw_body,
            timestamp_header=request.headers.get("x-timestamp"),
            signature_header=request.headers.get("x-signature"),
            signing_key=settings.WEBHOOK_SIGNING_KEY,
            max_skew_seconds=settings.WEBHOOK_MAX_CLOCK_SKEW_SECONDS,
        )
        if not valid:
            logger.warning(f"Webhook HMAC verification failed: {reason}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=reason)
        return raw_body, True

    return raw_body, False


async def reap_expired_sessions_once(db: Session, broadcaster) -> int:
    """Revokes expired active sessions, records audit events, and closes their SSE streams."""
    now = utc_now()
    idle_cutoff = now - timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
    active_sessions = (
        db.query(UserSession)
        .filter(UserSession.revoked_at.is_(None))
        .all()
    )

    expired_ids = []
    for sess in active_sessions:
        exp = ensure_utc(sess.expires_at)
        last_act = ensure_utc(sess.last_activity_at)
        reason = None
        if exp and now > exp:
            reason = "absolute_timeout"
        elif last_act and last_act < idle_cutoff:
            reason = "idle_timeout"

        if reason:
            sess.revoked_at = now
            sess.revoked_reason = reason
            user = db.query(User).filter(User.id == sess.user_id).first()
            record_audit(
                db,
                action="auth.session_timeout",
                resource_type="session",
                resource_id=sess.id,
                actor_user=user,
                ip_address=sess.ip_address,
                user_agent=sess.user_agent,
                metadata={"reason": reason},
                commit=False,
            )
            expired_ids.append((sess.id, reason))

    if expired_ids:
        db.commit()
        for sess_id, reason in expired_ids:
            await broadcaster.disconnect_session(sess_id, reason=reason)
    return len(expired_ids)


async def session_reaper_loop(session_factory, broadcaster) -> None:
    """Periodic background task to expire idle/max-age sessions and prune old raw_webhooks."""
    from models import RawWebhook

    tick = 0
    while True:
        try:
            await asyncio.sleep(30)
            tick += 1
            db = session_factory()
            try:
                await reap_expired_sessions_once(db, broadcaster)
                if tick % 120 == 0 and settings.RAW_WEBHOOK_RETENTION_DAYS > 0:
                    cutoff = utc_now() - timedelta(days=settings.RAW_WEBHOOK_RETENTION_DAYS)
                    db.query(RawWebhook).filter(RawWebhook.received_at < cutoff).delete(synchronize_session=False)
                    db.commit()
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"Error in session reaper loop: {exc}")
