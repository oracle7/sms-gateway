# SMS & MMS Gateway v3.0 (HIPAA-Ready Clinic Edition)

Self-hosted, real-time SMS/MMS messaging hub built with **FastAPI**, **SQLite (WAL)**, and **Server-Sent Events (SSE)**, designed for **Firefox** and **Pixel 6 (SMS Gateway for Android)** behind an internal VPN/Nginx proxy.

## Key Features in v3.0

- **HIPAA-Ready Access Control:** Individual user accounts (`admin` and `staff`), Argon2id password hashing, automatic lockout after failed attempts, server-side 30-minute inactivity timeout (with 2-minute countdown warning and automatic PHI cleanup), and private authenticated MMS attachment serving (`/api/attachments/{id}`).
- **Immutable Audit Trail (`audit_logs`):** Append-only SQLite table protected by `BEFORE UPDATE` / `BEFORE DELETE` triggers and a SHA-256 hash chain, with admin viewer, CSV/JSON export, and cryptographic integrity verification.
- **Soft-Delete & Archiving:** Nothing clinical is ever permanently deleted. Conversations can be archived/unarchived (auto-reopening when a patient replies) and individual messages can be hidden (with admin-only inspection and restoration).
- **Clean Schema & Paginated Threads:** Canonical E.164 phone normalization (preserving shortcodes and `unknown`), dedicated `threads` table, paginated `/api/threads` and per-thread message history without the v2 500-message cap.
- **Firefox-First Zero-CDN Frontend:** Deterministic pure CSS layout, local emoji picker, resilient SSE with heartbeat watchdog, smart `build_id` auto-reload, optional chime (`airport_ding.mp3`), and PHI-free desktop notifications.
- **Lossless v2 → v3 Migration:** Standalone CLI (`scripts/migrate_v2_to_v3.py`) with `--dry-run`, SQLite Online Backup API snapshot, media migration, and full count/integrity reconciliation.

## Quick Start (Local Development)

```bash
cp .env.example .env
pip install -r requirements.txt
python scripts/manage_users.py create-admin --username doctor --display-name "Dr. Smith"
uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

For production deployment with Nginx HTTPS, systemd, Pixel 6 HMAC signing, and `sms_gateway_1937.db` migration, see [docs/deployment-nginx.md](docs/deployment-nginx.md).
