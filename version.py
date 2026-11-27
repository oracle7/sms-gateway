import hashlib
import secrets
from pathlib import Path

APP_VERSION = "3.0.0"
_BOOT_TOKEN = secrets.token_hex(3)


def _compute_assets_hash() -> str:
    """Computes a short hash over static/ and templates/ so asset edits rotate BUILD_ID."""
    h = hashlib.sha256()
    base = Path(__file__).resolve().parent
    for folder in ("static", "templates"):
        root = base / folder
        if not root.exists():
            continue
        for file_path in sorted(p for p in root.rglob("*") if p.is_file()):
            if file_path.suffix in {".css", ".js", ".html"}:
                h.update(str(file_path.relative_to(base)).encode("utf-8"))
                h.update(file_path.read_bytes())
    return h.hexdigest()[:8]


BUILD_ID = f"{APP_VERSION}-{_compute_assets_hash()}-{_BOOT_TOKEN}"
