from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import httpx
import logging
import json

from config import settings
from database import get_db
import models
from services.broadcaster import broadcaster

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

latest_health_state = {
    "status": "unknown",
    "battery_level": "--",
    "is_charging": False,
}


def parse_health_object(health_data: dict) -> dict:
    """Extracts normalized status and battery metrics from a gateway health payload."""
    status = health_data.get("status", "unknown")
    checks = health_data.get("checks", {})

    battery_level = checks.get("battery:level", {}).get("observedValue", "--")
    battery_charging_flags = checks.get("battery:charging", {}).get("observedValue", 0)

    if isinstance(battery_charging_flags, bool):
        is_charging = battery_charging_flags
    else:
        is_charging = isinstance(battery_charging_flags, (int, float)) and battery_charging_flags > 0

    return {
        "status": status,
        "battery_level": battery_level,
        "is_charging": is_charging,
    }


async def fetch_device_health() -> Optional[dict]:
    """Actively polls the Android gateway's local /health endpoint and caches the result."""
    url = f"{settings.SMS_API_URL.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            auth = httpx.BasicAuth(settings.SMS_API_LOGIN, settings.SMS_API_PASS)
            resp = await client.get(url, auth=auth)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("checks" in data or "status" in data):
                    parsed = parse_health_object(data)
                    latest_health_state.update(parsed)
                    return dict(latest_health_state)
    except Exception as e:
        logger.warning(f"Failed to poll Android gateway health at {url}: {e}")
    return None


async def dump_raw_webhook(payload: dict, db: Session):
    """Failsafe: Dumps raw incoming health webhooks to the database."""
    try:
        raw = models.RawWebhookDump(payload=json.dumps(payload))
        db.add(raw)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to dump raw health webhook: {e}")
        db.rollback()


@router.get("/status")
async def get_health_status():
    """Returns live Android gateway health metrics (falling back to cached state)."""
    live = await fetch_device_health()
    if live is not None:
        return live
    return dict(latest_health_state)


@router.post("")
@router.post("/")
async def handle_health_ping(request: Request, db: Session = Depends(get_db)):
    """
    Catches system:ping webhooks from the Android Gateway for device health monitoring.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    await dump_raw_webhook(payload, db)

    event = payload.get("event")
    if event != "system:ping":
        return {"status": "ignored", "reason": f"Unhandled event type: {event}"}

    health_data = payload.get("payload", {}).get("health", {})
    if isinstance(health_data, dict) and health_data.get("checks"):
        latest_health_state.update(parse_health_object(health_data))
    else:
        fetched = await fetch_device_health()
        if fetched is None:
            latest_health_state["status"] = "pass"

    # Broadcast metrics to web UI via SSE
    await broadcaster.publish("health_update", dict(latest_health_state))

    return {"status": "success"}