# 📱 SMS & MMS Gateway Hub

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
├── config.py             # Environment configurations & settings
├── database.py           # SQLite connection setup
├── main.py               # FastAPI application entrypoint
├── messages.py           # API routes & web endpoints
├── models.py             # SQLAlchemy DB Models (Messages & Attachments)
├── schema.py             # Pydantic validation schemas
├── worker.py             # Background transceiver polling & MMS extraction logic
├── static/
│   └── mms/              # Media directory for stored MMS attachments
└── templates/
    └── messages.html     # Web chat user interface

```

---

## 🚀 Getting Started

### Prerequisites

* Python **3.10+**
* An accessible Android SMS Gateway Transceiver on your local network or public URL.

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/your-username/sms-gateway-hub.git
cd sms-gateway-hub

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
Create a `.env` file (or set variables in `config.py`):
```env
DATABASE_URL=sqlite:///database.db
SMS_API_URL=http://<YOUR_TRANSCEIVER_IP>:8080
SMS_API_LOGIN=your_login
SMS_API_PASS=your_password

```


5. **Run the application:**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000

```


6. **Access the Web Dashboard:**
Open your browser and navigate to `http://localhost:8000/messages`

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
* **Database:** SQLite
* **HTTP Client:** Requests / HTTPX
* **Frontend:** Jinja2 Templates, HTML5, CSS3, JavaScript

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://www.google.com/search?q=LICENSE) file for details.