import json
import logging
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from routers.webhooks import _dump_raw_webhook
from services.auth import AuthContext, require_auth_no_refresh, verify_webhook_access
from services.broadcaster import broadcaster
from services.gateway_client import (
    fetch_gateway_health,
    latest_health_state,
    parse_health_object,
    update_cached_health,
)
from version import APP_VERSION, BUILD_ID

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


@router.get("/health/live")
def liveness_probe():
    """Minimal unauthenticated liveness check for Nginx/systemd."""
    return {"status": "ok"}


@router.get("/health/status")
async def get_health_status(auth: AuthContext = Depends(require_auth_no_refresh)):
    """Authenticated endpoint returning live Pixel 6 gateway health or cached state."""
    live = await fetch_gateway_health()
    if live is not None:
        return live
    return dict(latest_health_state)


@router.post("/health")
@router.post("/health/")
async def handle_health_ping(
    request: Request,
    verified: Tuple[bytes, bool] = Depends(verify_webhook_access),
    db: Session = Depends(get_db),
):
    """Receives system:ping webhooks from the Pixel 6 Android SMS Gateway."""
    raw_body, sig_valid = verified
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.")

    event = payload.get("event")
    if event != "system:ping":
        _dump_raw_webhook(
            db,
            endpoint="/health",
            event_type=str(event or ""),
            signature_valid=sig_valid,
            processing_status="ignored_non_ping",
            payload=payload,
        )
        return {"status": "ignored", "reason": f"Unhandled event: {event}"}

    health_data = payload.get("payload", {}).get("health", {})
    if isinstance(health_data, dict) and health_data.get("checks"):
        state = update_cached_health(parse_health_object(health_data))
    else:
        fetched = await fetch_gateway_health()
        state = fetched if fetched is not None else update_cached_health({"status": "pass"})

    await broadcaster.publish("health_update", state)
    return {"status": "success"}


@router.get("/api/system/version")
def get_system_version(auth: AuthContext = Depends(require_auth_no_refresh)):
    return {"app_version": APP_VERSION, "build_id": BUILD_ID}
