# 📱 SMS & MMS Gateway Hub

[![GitHub](https://img.shields.io/badge/GitHub-Repository-181717?style=flat&logo=github)](https://github.com/oracle7/sms-gateway)
[![Codeberg](https://img.shields.io/badge/Codeberg-Repository-2185d0?style=flat&logo=codeberg)](https://codeberg.org/oracle7/sms-gateway)

A lightweight, high-performance web interface and background synchronization service built with **FastAPI** and **SQLite**. It interfaces seamlessly with an Android SMS Transceiver device to send, receive, and render SMS/MMS messages with full multimedia support.

---

## ✨ Features

* **🔄 Asynchronous Real-Time Polling:** Background worker (`worker.py`) constantly syncs messages with the Android transceiver without freezing the web interface.
* **🖼️ Smart MMS Extraction:** Automatically parses transceiver system logs to correlate MMS push notifications with their underlying media files (JPG, PNG, Audio, etc.).
* **💬 Threaded Chat UI:** Clean, responsive web frontend for viewing message threads, sending replies, and inspecting attachments.
* **🛡️ Filtering & Blacklisting:** Built-in safeguards to filter out redundant operator MMS notifications and block specific unwanted phone numbers.
* **🗃️ Lightweight SQLite Backend:** Efficient local storage setup using raw SQL performance alongside standard ORM capabilities.

---

## 🏗️ Architecture Overview

The system is decoupled into two primary components to ensure high availability and responsiveness:

```
                  ┌──────────────────────┐
                  │ Android Transceiver  │
                  └──────────┬───────────┘
                             │
            ┌────────────────┴────────────────┐
            │                                 │
     (HTTP Polling)                   (HTTP Requests)
            │                                 │
            ▼                                 ▼
   ┌─────────────────┐               ┌─────────────────┐
   │    worker.py    │               │   messages.py   │
   │ (Sync & Media)  │               │  (API & Views)  │
   └────────┬────────┘               └────────┬────────┘
            │                                 │
            └───────────┐         ┌───────────┘
                        ▼         ▼
                   ┌───────────────────┐
                   │ SQLite Database   │
                   └───────────────────┘

```

1. **`messages.py` (API & Web Server):** Fast, non-blocking API endpoints powered by **FastAPI**. Serves the frontend templates and handles user actions (sending messages, fetching threads).
2. **`worker.py` (Background Worker):** An isolated, continuous async process that polls the transceiver inbox, resolves MMS attachment metadata via log inspection, downloads media files to `static/mms/`, and populates the database.

---

## 📁 Directory Structure

```text
.
├── frontend/                 # UI HTML Templates
│   ├── contacts.html         # Contacts management view
│   ├── header.html           # Reusable navigation header component
│   └── messages.html         # Main messaging interface and chat threads
├── routers/                  # FastAPI Modular Route Handlers
│   ├── __init__.py           # Package initializer
│   ├── contacts.py           # Contacts API endpoints
│   └── messages.py           # Messages API endpoints and views
├── static/                   # Public Static Assets
│   ├── media/                # Directory for downloaded MMS attachments
│   └── airport_ding.mp3      # Audio alert for new message notifications
├── .gitignore                # Git untracked files configuration
├── bootstrap_db.py           # Database initial setup/seeding script
├── config.py                 # Environment variables and app configuration
├── database.py               # SQLite database connection setup
├── generate_prototype.py     # Mock data generator for testing
├── LICENSE                   # Mozilla Public License 2.0 (MPL 2.0)
├── main.py                   # FastAPI application entrypoint
├── models.py                 # SQLAlchemy database models
├── README.md                 # Project documentation
├── requirements.txt          # Python dependencies list
├── schemas.py                # Pydantic data validation schemas
├── start_app.sh              # Application startup script
└── worker.py                 # Background polling worker for SMS/MMS sync

```

---

## 🚀 Getting Started

### Prerequisites

* Python **3.10+**
* An accessible Android SMS Gateway Transceiver on your local network or public URL.

### Installation

### Installation

1. **Clone the repository:**

   Choose your preferred platform:

   * **GitHub:**
     ```bash
     git clone [https://github.com/oracle7/sms-gateway.git](https://github.com/oracle7/sms-gateway.git)
     cd sms-gateway
     ```

   * **Codeberg:**
     ```bash
     git clone [https://codeberg.org/oracle7/sms-gateway.git](https://codeberg.org/oracle7/sms-gateway.git)
     cd sms-gateway
     ```

2. **Create and activate a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

```


3. **Install dependencies:**
```bash
pip install -r requirements.txt

```


4. **Configure environment variables:**
   Copy the example environment file and update it with your transceiver credentials:
```bash
   cp .env.example .env
   nano .env  # Edit the file to set TRANSCEIVER_URL, API_KEY, etc.
```


5. **Run the application:**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000

```


6. **Access the Web Dashboard:**
Open your browser and navigate to `http://<server_URL>:8000/messages`

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
* **Database:** SQLite
* **HTTP Client:** Requests / HTTPX
* **Frontend:** Jinja2 Templates, HTML5, CSS3, JavaScript

---

## 📄 License

This project is licensed under the Mozilla Public License 2.0 - see the [LICENSE](./LICENSE) file for details.