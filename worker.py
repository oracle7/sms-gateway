import asyncio
import requests
import sqlite3
import logging
from datetime import datetime, timezone
from config import settings

POLL_INTERVAL = 5

# ---------------------------------------------------------
# EXCLUSION LISTS (BLACKLIST)
# ---------------------------------------------------------
BLOCKED_NUMBERS = {
    "7184238545",
    "+17184238545",
    "7187677043",
    "+17187677043"
}
BLOCKED_MESSAGE_IDS = set()

# ---------------------------------------------------------
# SETUP & LOGGING
# ---------------------------------------------------------
logger = logging.getLogger("uvicorn.error")
_INITIAL_SYNC_DONE = False

def get_db_path():
    return settings.DATABASE_URL.replace("sqlite:///", "")

def normalize_utc(iso_string):
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt_utc.isoformat(sep=' ', timespec='seconds')
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=' ', timespec='seconds')

def poll_transceiver(is_initial_sync=False):
    base_url = f"{settings.SMS_API_URL.rstrip('/')}/inbox" if not settings.SMS_API_URL.endswith('/inbox') else settings.SMS_API_URL
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    limit = 500 if is_initial_sync else 50
    offset = 0
    total_inserts_this_cycle = 0

    logger.info(f"[Sync Loop] Fetching from API: {base_url} with limit={limit}, offset={offset}")

    while True:
        try:
            response = requests.get(
                base_url, 
                params={"limit": limit, "offset": offset},
                auth=(settings.SMS_API_LOGIN, settings.SMS_API_PASS),
                timeout=10
            )
            response.raise_for_status()
            
            total_count = int(response.headers.get("X-Total-Count", 0))
            payload = response.json()
            messages = payload.get("data", payload) if isinstance(payload, dict) else payload
            
            if not messages:
                logger.info("[Sync Loop] No messages returned in API payload response.")
                break
                
            logger.info(f"[Sync Loop] Received {len(messages)} messages from API payload (Total Remote: {total_count}).")
            new_inserts_this_page = 0
            reached_known_messages = False

            for msg in messages:
                msg_id_str = str(msg.get("id")) if msg.get("id") is not None else None
                raw_number = msg.get("sender") or msg.get("recipient", "UNKNOWN")
                body = msg.get("contentPreview", msg.get("body", ""))
                
                if not msg_id_str or msg_id_str in BLOCKED_MESSAGE_IDS or raw_number in BLOCKED_NUMBERS:
                    continue

                # Clean duplicate prevention checkpoint
                cursor.execute("SELECT 1 FROM messages WHERE id = ?", (msg_id_str,))
                if cursor.fetchone():
                    reached_known_messages = True
                    continue

                raw_timestamp = msg.get("createdAt", msg.get("timestamp", "")) 
                utc_timestamp = normalize_utc(raw_timestamp)
                is_inbound = True if "sender" in msg else False

                try:
                    cursor.execute('''
                        INSERT INTO messages (id, raw_number, body, timestamp, is_inbound)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (msg_id_str, raw_number, body, utc_timestamp, is_inbound))
                    new_inserts_this_page += 1
                except sqlite3.IntegrityError:
                    # Fallback boundary just in case
                    reached_known_messages = True

            total_inserts_this_cycle += new_inserts_this_page
            
            if new_inserts_this_page > 0:
                conn.commit()
                logger.info(f"[Sync Loop] DB Commit successful. Saved {new_inserts_this_page} items.")

            # --- Pagination State ---
            if is_initial_sync:
                offset += limit
                if offset >= total_count:
                    break 
            else:
                if reached_known_messages or len(messages) < limit:
                    break
                else:
                    offset += limit
                    limit = 500 

        except requests.RequestException as e:
            logger.error(f"[Sync Loop] Network error tracking API endpoint: {e}")
            break
        except Exception as e:
            logger.error(f"[Sync Loop] Processing error during array evaluation: {e}")
            break

    if total_inserts_this_cycle > 0:
        sync_type = "Historical Batch" if is_initial_sync else "Polling"
        logger.info(f"[{sync_type}] Cycle finished. Total new rows committed: {total_inserts_this_cycle}")
        
    conn.close()

async def sync_inbox_loop():
    global _INITIAL_SYNC_DONE
    logger.info("Starting SMS Gateway Async Sync Worker...")
    
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            raw_number TEXT NOT NULL,
            body TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            is_inbound BOOLEAN NOT NULL
        )
    ''')
    conn.commit()
    
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages")
    local_count = cursor.fetchone()[0]
    conn.close()
    
    logger.info(f"Database baseline check complete. Found {local_count} local records.")
    _INITIAL_SYNC_DONE = (local_count > 0)
    
    while True:
        if not _INITIAL_SYNC_DONE:
            logger.info("Local database is clean. Starting full history backfill...")
            await asyncio.to_thread(poll_transceiver, True)
            _INITIAL_SYNC_DONE = True
        else:
            await asyncio.to_thread(poll_transceiver, False)
            
        await asyncio.sleep(POLL_INTERVAL)