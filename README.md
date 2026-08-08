# 📱 SMS & MMS Gateway Hub

[![GitHub](https://img.shields.io/badge/GitHub-Repository-181717?style=flat&logo=github)](https://github.com/oracle7/sms-gateway)
[![Codeberg](https://img.shields.io/badge/Codeberg-Repository-2185d0?style=flat&logo=codeberg)](https://codeberg.org/oracle7/sms-gateway)

A lightweight, self-hosted, real-time web interface and REST API gateway built with **FastAPI**, **SQLite**, and **Server-Sent Events (SSE)**. It bridges web-based messaging directly to an Android SMS/MMS gateway, featuring live delivery status tracking, contact management, and multimedia attachment handling.

---

## 🏛️ Master Architecture & Blueprint

### 1. Architectural Highlights

* **Real-Time Data Pipeline:** Asynchronous webhook processing publishes inbound messages and status updates to an in-memory **SSE Broadcaster**, updating the UI instantly without polling.
* **Engine-Level Integrity:** Built-in SQLite constraints block "ghost messages" directly at the database layer.
* **Multi-Boolean Lifecycle Tracking:** Message states (`is_sent`, `is_delivered`, `is_failed`, `is_cancelled`, `web_viewed`) are tracked explicitly as separate boolean flags rather than mutating single strings.
* **Smart DID Fallback:** Native logic automatically resolves missing gateway sender/recipient identifiers using the configured system DID (`settings.SMS_DID`).
* **Isolated Contact Management:** Deleting a contact record purges only the address book metadata—message history and thread records remain 100% intact.

---

## 💾 Database Schema (`models.py`)

### `messages`

Primary store for all inbound and outbound SMS/MMS conversations.

| Column | Type | Constraints / Defaults | Description |
| --- | --- | --- | --- |
| `id` | String | Primary Key (UUID) | Internal primary identifier. |
| `message_id` | String | Indexed, Unique, Nullable | Native carrier/gateway ID for webhook matching. |
| `timestamp` | DateTime | Non-null (UTC) | Message timestamp. |
| `sender` | String | Nullable (E.164) | Sender phone number. |
| `recipient` | String | Nullable (E.164) | Recipient phone number. |
| `body` | String | Default: `""` | Message text contents. |
| `is_sent` | Boolean | Default: `0` | Outbound dispatch state. |
| `is_delivered` | Boolean | Default: `0` | Delivery confirmation state. |
| `is_read` | Boolean | Default: `0` | Read state. |
| `is_failed` | Boolean | Default: `0` | Message failure state. |
| `is_cancelled` | Boolean | Default: `0` | Cancelled transmission state. |
| `web_viewed` | Boolean | Default: `0` | UI rendered state. |
| `error_reason` | Text | Nullable | Captures carrier failure details (`sms:failed`). |

> **Engine Check Constraint:** `CHECK (sender IS NOT NULL OR recipient IS NOT NULL)`
> *Enforces strict database integrity against ghost bubbles or corrupted carrier webhooks.*

### `attachments`

Stores incoming MMS media files.

| Column | Type | Constraints / Defaults | Description |
| --- | --- | --- | --- |
| `id` | Integer | Primary Key (Autoincrement) | Internal ID. |
| `message_id` | String | Foreign Key $\rightarrow$ `messages.id` (`ON DELETE CASCADE`) | Parent message reference. |
| `filename` | String | Non-null | Relative static media path (e.g., `/static/media/...`). |
| `content_type` | String | Nullable | MIME type (e.g., `image/jpeg`). |

### `contacts`

Address book lookup table.

| Column | Type | Constraints / Defaults | Description |
| --- | --- | --- | --- |
| `phone_number` | String | Primary Key (E.164) | Normalized contact number. |
| `name` | String | Non-null | Display name. |
| `notes` | Text | Nullable | Freeform notes field. |

### `raw_webhooks`

Failsafe dump table for debugging and payload recovery.

| Column | Type | Constraints / Defaults | Description |
| --- | --- | --- | --- |
| `id` | Integer | Primary Key (Autoincrement) | Internal ID. |
| `received_at` | DateTime | Default UTC | Arrival timestamp. |
| `payload` | Text | Non-null | Raw JSON payload received from gateway. |

---

## 📂 Directory Layout

```text
/
├── .env.example          # Template environment variable configuration
├── config.py             # Environment variables & settings
├── database.py           # SQLAlchemy engine & SessionLocal dependency
├── models.py             # ORM models & database CheckConstraints
├── schemas.py            # Pydantic validation schemas
├── main.py               # Application entrypoint & router registration
│
├── services/
│   └── broadcaster.py    # SSE Event Broadcaster (Pub/Sub hub for web clients)
│
├── routers/
│   ├── send.py           # POST /messages (Dispatches outbound messages)
│   ├── fetch.py          # GET /messages (Queries database for UI threads)
│   ├── contacts.py       # CRUD endpoints for contact management
│   ├── webhooks.py       # POST /webhook/* (Inbound message & status updates)
│   └── events.py         # GET /events (Server-Sent Events endpoint)
│
├── templates/
│   ├── base.html         # Base Jinja2 layout (Tailwind CDN, CSS/JS includes)
│   ├── index.html        # Messages & Chat thread interface
│   ├── contacts.html     # Address book management interface
│   └── components/
│       ├── header.html   # Top navigation & status bar
│       ├── sidebar.html  # Thread list & contact quick-select
│       └── chat_area.html# Chat history panel & composer input
│
└── static/
    ├── media/            # Saved MMS media files
    ├── css/
    │   └── custom.css    # Custom UI styling overrides
    └── js/
        ├── sse.js        # EventSource listener for real-time UI updates
        ├── app.js        # Chat UI rendering, thread logic, & messaging
        └── contacts.js   # Contact CRUD modal logic

```

---

## 🔌 API Reference & Endpoints

### 1. Messaging (`routers/send.py` & `routers/fetch.py`)

* `POST /messages`: Dispatches an outbound SMS payload to the Android API $\rightarrow$ Records initial state in DB $\rightarrow$ Returns non-blocking response.
* `GET /messages`: Retrieves historical message threads. Supports filtering by `sender`, `recipient`, `from_datetime`, `to_datetime`, and `limit`.

### 2. Webhooks (`routers/webhooks.py`)

* `POST /webhook/inbound`: Processes `sms:received`, `sms:data-received`, and `mms:downloaded` events. Saves Base64 MMS files to `static/media/` and publishes live updates to `broadcaster.py`. *(Ignores preliminary `mms:received` notification headers).*
* `POST /webhook/status`: Listens for `sms:sent`, `sms:delivered`, `sms:failed`, and `sms:cancelled`. Updates specific status booleans by matching `message_id` and triggers real-time status checkmark updates in the UI.

### 3. Contact Management (`routers/contacts.py`)

* `GET /contacts`: Lists all stored contacts or searches by name/number.
* `POST /contacts`: Adds a new contact (`phone_number`, `name`, `notes`).
* `PUT /contacts/{phone_number}`: Updates contact details.
* `DELETE /contacts/{phone_number}`: Deletes the contact record while retaining historical messages.

### 4. Real-Time Event Pipeline (`routers/events.py`)

* `GET /events`: Opens a persistent `text/event-stream` SSE connection for frontend client push notifications.

---

## 🛠️ Setup & Local Deployment

### 1. Environment Requirements

* Python 3.10+
* SQLite 3.35+

### 2. Environment Configuration

Copy the provided `.env.example` file to create your active `.env` file, then edit the values to match your gateway setup:

```bash
cp .env.example .env

```

Modify the parameters inside `.env`:

```env
SMS_API_URL="http://<ANDROID_GATEWAY_IP>:<PORT>"
SMS_API_LOGIN="your_gateway_username"
SMS_API_PASS="your_gateway_password"
SMS_DID="+10123456789"

```

### 3. Installation

```bash
# Clone the repository
git clone https://codeberg.org/oracle7/sms-gateway.git
cd sms-gateway

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install direct runtime dependencies
pip install -r requirements.txt

# Start system service or run manually via Uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000

```

---

## 🚀 Running as a Systemd Service

For continuous production uptime, run under `systemd`:

```ini
[Unit]
Description=SMS Gateway Web Platform
After=network.target

[Service]
User=smsuser
WorkingDirectory=/var/www/sms-gateway
ExecStart=/var/www/sms-gateway/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target

```