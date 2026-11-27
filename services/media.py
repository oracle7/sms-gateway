import base64
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings

MIME_EXT_MAP = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "video/mp4": "mp4",
    "video/3gpp": "3gp",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/amr": "amr",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "application/pdf": "pdf",
    "text/vcard": "vcf",
    "text/x-vcard": "vcf",
    "text/plain": "txt",
}

INLINE_SAFE_PREFIXES = ("image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp", "audio/", "video/")


@dataclass
class SavedMedia:
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str


def ensure_media_dir(media_dir: Optional[Path] = None) -> Path:
    target = media_dir or settings.media_path
    target.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
    return target


def is_inline_safe(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    ct = content_type.split(";")[0].strip().lower()
    if ct == "application/pdf":
        return True
    return any(ct.startswith(p) for p in INLINE_SAFE_PREFIXES)


def save_base64_attachment(
    b64_data: str,
    content_type: Optional[str] = None,
    original_name: Optional[str] = None,
    media_dir: Optional[Path] = None,
) -> SavedMedia:
    """Decodes base64 media and saves it into a private directory outside /static."""
    root = ensure_media_dir(media_dir)
    clean_ct = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    ext = MIME_EXT_MAP.get(clean_ct, "bin")

    raw_bytes = base64.b64decode(b64_data, validate=False)
    digest = hashlib.sha256(raw_bytes).hexdigest()

    now = datetime.now(timezone.utc)
    rel_dir = Path(now.strftime("%Y")) / now.strftime("%m")
    abs_dir = root / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{ext}"
    abs_file = abs_dir / filename
    abs_file.write_bytes(raw_bytes)

    storage_key = f"{rel_dir.as_posix()}/{filename}"
    return SavedMedia(
        storage_key=storage_key,
        content_type=clean_ct,
        size_bytes=len(raw_bytes),
        sha256=digest,
    )


def resolve_media_path(storage_key: str, media_dir: Optional[Path] = None) -> Path:
    """Safely resolves a storage_key strictly within MEDIA_DIR."""
    root = (media_dir or settings.media_path).resolve()
    candidate = (root / storage_key).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("Invalid media storage path")
    return candidate
