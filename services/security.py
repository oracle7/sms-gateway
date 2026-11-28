import hashlib
import hmac
import secrets
import time
from typing import Any, Optional, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain_password: str) -> str:
    """Hashes a plaintext password using Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(password_hash: str, plain_password: str) -> bool:
    """Verifies a plaintext password against an Argon2id hash."""
    if not password_hash or not plain_password:
        return False
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def check_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def validate_password_strength(password: str, min_length: int = 12) -> None:
    """Enforces minimum password length policy."""
    if not password or len(password) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters long.")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_session_token() -> Tuple[str, str]:
    """Returns (raw_cookie_token, sha256_token_hash)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_webhook_signature(
    raw_body: bytes,
    timestamp_header: Optional[str],
    signature_header: Optional[str],
    signing_key: str,
    max_skew_seconds: int = 300,
) -> Tuple[bool, str]:
    """
    Verifies SMS Gateway for Android HMAC-SHA256 webhook signature:
    HMAC-SHA256(signing_key, raw_body + X-Timestamp) == X-Signature.
    """
    if not signing_key:
        return False, "Webhook signing key is not configured"
    if not timestamp_header or not signature_header:
        return False, "Missing X-Timestamp or X-Signature header"

    try:
        ts = int(timestamp_header.strip())
    except ValueError:
        return False, "Invalid X-Timestamp header"

    now_ts = int(time.time())
    if abs(now_ts - ts) > max_skew_seconds:
        return False, "Webhook timestamp outside allowed window"

    message = raw_body + timestamp_header.strip().encode("utf-8")
    expected_hex = hmac.new(
        signing_key.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hex.lower(), signature_header.strip().lower()):
        return False, "Invalid webhook signature"

    return True, "ok"


def sanitize_webhook_payload(payload: Any) -> Any:
    """Strips base64 attachment payloads before storing in raw_webhooks."""
    if isinstance(payload, dict):
        cleaned = {}
        for k, v in payload.items():
            if k in ("data", "base64") and isinstance(v, str) and v:
                cleaned[k] = f"[stripped: {len(v)} chars]"
            else:
                cleaned[k] = sanitize_webhook_payload(v)
        return cleaned
    if isinstance(payload, list):
        return [sanitize_webhook_payload(item) for item in payload]
    return payload
