import asyncio
import requests
import sqlite3
import logging
import re
import os
import uuid
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

MEDIA_DIR = "static/mms"
os.makedirs(MEDIA_DIR, exist_ok=True)

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
    logs_url = f"{settings.SMS_API_URL.rstrip('/')}/logs"
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
                
                # Robust phone number extraction
                raw_number = msg.get("sender") or msg.get("recipient") or msg.get("address") or msg.get("from") or ""
                raw_number = str(raw_number).strip()
                if not raw_number or raw_number == "null":
                    raw_number = "UNKNOWN"
                    logger.warning(f"[{msg_id_str}] Phone number not found! Payload: {msg}")
                
                body = msg.get("contentPreview", msg.get("body", ""))
                msg_type = msg.get("type", "")
                
                if not msg_id_str or msg_id_str in BLOCKED_MESSAGE_IDS or raw_number in BLOCKED_NUMBERS:
                    continue

                # Identify if message is MMS
                is_mms = msg_type in ["MMS", "MMS_DOWNLOADED"] or "MMS" in body
                
                # Transforms notification into image container (clears "MMS notification" text)
                if is_mms:
                    body = ""

                # Duplicate prevention
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
                    
                    # ==========================================
                    # MMS EXTRACTION & MATCHING LOGIC
                    # ==========================================
                    if is_mms and msg_id_str:
                        logger.info(f"[{msg_id_str}] Cross-referencing MMS data for {raw_number} in logs...")
                        try:
                            logs_response = requests.get(
                                logs_url,
                                auth=(settings.SMS_API_LOGIN, settings.SMS_API_PASS),
                                timeout=15.0
                            )
                            logs_text = logs_response.text
                            
                            real_mms_id = None
                            clean_number = raw_number.replace("+", "")
                            
                            # Search for the real download ID associated with the sender's number
                            lines = logs_text.split('\n')
                            for i, line in enumerate(lines):
                                if clean_number in line or raw_number in line:
                                    window = " ".join(lines[max(0, i-10):min(len(lines), i+10)])
                                    match = re.search(r'(?:id["\':\s]*|mms:)(\d{3,8})', window, re.IGNORECASE)
                                    if match:
                                        real_mms_id = match.group(1)
                                        break
                            
                            if not real_mms_id:
                                logger.warning(f"[{msg_id_str}] Real ID not found in logs for {raw_number}. Falling back to original ID.")
                                real_mms_id = msg_id_str.replace("mms:", "").replace("sms:", "")
                            else:
                                logger.info(f"[{msg_id_str}] Real MMS ID found: {real_mms_id}")

                            # Attempt to find partIDs, with fallback to 0, 1, and 2
                            part_ids_found = re.findall(r'(\d+)\s*\{\s*contentType:', logs_text)
                            if not part_ids_found:
                                part_ids_found = ['0', '1', '2']
                            else:
                                part_ids_found = list(set(part_ids_found))
                            
                            # Download using the real ID, but save linked to the original ID
                            for part_id in part_ids_found:
                                download_url = f"{base_url}/{real_mms_id}/attachments/{part_id}"
                                logger.info(f"[{msg_id_str}] Attempting attachment download from: {download_url}")
                                
                                att_resp = requests.get(
                                    download_url, 
                                    auth=(settings.SMS_API_LOGIN, settings.SMS_API_PASS),
                                    timeout=15.0
                                )
                                
                                if att_resp.status_code == 200 and len(att_resp.content) > 0:
                                    content_type = att_resp.headers.get("Content-Type", "application/octet-stream")
                                    ext = content_type.split("/")[-1] if "/" in content_type else "bin"
                                    if ext == "jpeg": 
                                        ext = "jpg"
                                    
                                    unique_filename = f"{uuid.uuid4().hex}_part{part_id}.{ext}"
                                    filepath = os.path.join(MEDIA_DIR, unique_filename)
                                    
                                    with open(filepath, 'wb') as f:
                                        f.write(att_resp.content)
                                        
                                    logger.info(f"[{msg_id_str}] MMS file successfully saved: {filepath}")
                                        
                                    cursor.execute('''
                                        INSERT INTO message_attachments (message_id, media_url, content_type)
                                        VALUES (?, ?, ?)
                                    ''', (msg_id_str, f"/static/mms/{unique_filename}", content_type))
                                    
                        except Exception as e:
                            logger.error(f"[Sync Loop] Error processing MMS (ID: {msg_id_str}): {str(e)}")
                    # ==========================================

                    new_inserts_this_page += 1
                except sqlite3.IntegrityError:
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
            logger.error(f"[Sync Loop] Network error: {e}")
            break
        except Exception as e:
            logger.error(f"[Sync Loop] Processing error: {e}")
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
            gateway_id TEXT,
            raw_number TEXT NOT NULL,
            body TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            is_inbound BOOLEAN NOT NULL,
            status TEXT DEFAULT 'delivered'
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS message_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            media_url TEXT NOT NULL,
            content_type TEXT,
            FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
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