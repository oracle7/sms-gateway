import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from config import settings
from database import utc_now

logger = logging.getLogger("uvicorn.error")

latest_health_state: Dict[str, Any] = {
    "status": "unknown",
    "battery_level": "--",
    "is_charging": False,
    "last_updated_at": None,
}


def parse_health_object(health_data: dict) -> dict:
    """Extracts normalized status and battery metrics from a gateway health payload."""
    status = health_data.get("status", "unknown")
    checks = health_data.get("checks", {})

    battery_level = checks.get("battery:level", {}).get("observedValue", "--")
    charging_val = checks.get("battery:charging", {}).get("observedValue", 0)

    if isinstance(charging_val, bool):
        is_charging = charging_val
    else:
        is_charging = isinstance(charging_val, (int, float)) and charging_val > 0

    return {
        "status": status,
        "battery_level": battery_level,
        "is_charging": is_charging,
        "last_updated_at": utc_now().isoformat(),
    }


def update_cached_health(parsed: dict) -> dict:
    latest_health_state.update(parsed)
    return dict(latest_health_state)


async def fetch_gateway_health() -> Optional[dict]:
    """Actively polls the Pixel 6 SMS Gateway /health endpoint."""
    url = f"{settings.SMS_API_URL.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            auth = httpx.BasicAuth(settings.SMS_API_LOGIN, settings.SMS_API_PASS)
            resp = await client.get(url, auth=auth)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("checks" in data or "status" in data):
                    return update_cached_health(parse_health_object(data))
    except Exception as exc:
        logger.warning(f"Failed to poll Android gateway health at {url}: {exc}")
    return None


async def send_sms_to_gateway(recipient_e164: str, body: str) -> Optional[str]:
    """
    Sends an outbound SMS via the Pixel 6 Android SMS Gateway API.
    Returns the gateway's native message ID when present, or raises httpx / RuntimeError.
    """
    url = f"{settings.SMS_API_URL.rstrip('/')}/messages"
    payload = {
        "phoneNumbers": [recipient_e164],
        "message": body,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        auth = httpx.BasicAuth(settings.SMS_API_LOGIN, settings.SMS_API_PASS)
        response = await client.post(url, auth=auth, json=payload)
        if response.status_code not in (200, 201, 202, 204):
            logger.error(f"Gateway rejected SMS ({response.status_code}): {response.text}")
            raise RuntimeError(f"Android gateway rejected request ({response.status_code})")
        try:
            data = response.json()
            msg_id = data.get("id")
            return str(msg_id) if msg_id else None
        except Exception:
            return None
