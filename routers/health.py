from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
import json

from database import get_db
import models
from services.broadcaster import broadcaster

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

async def dump_raw_webhook(payload: dict, db: Session):
    """Failsafe: Dumps raw incoming health webhooks to the database."""
    try:
        raw = models.RawWebhookDump(payload=json.dumps(payload))
        db.add(raw)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to dump raw health webhook: {e}")
        db.rollback()

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

    # Extract health structure from gateway payload
    health_data = payload.get("payload", {}).get("health", {})
    status = health_data.get("status", "unknown")
    checks = health_data.get("checks", {})

    # Extract battery percentage and charging flags
    battery_level = checks.get("battery:level", {}).get("observedValue", "--")
    battery_charging_flags = checks.get("battery:charging", {}).get("observedValue", 0)

    # 0 = Not charging. Any flag > 0 means the device is plugged in.
    is_charging = isinstance(battery_charging_flags, int) and battery_charging_flags > 0

    # Broadcast metrics to web UI via SSE
    await broadcaster.publish("health_update", {
        "status": status,
        "battery_level": battery_level,
        "is_charging": is_charging
    })

    return {"status": "success"}