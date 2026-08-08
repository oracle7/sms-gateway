import os
import logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Import database initialization
from database import engine, Base
import models

# Import our modular routers (we will create these files next!)
from routers import send, fetch, contacts, webhooks, events, health

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

# Ensure required directories exist
os.makedirs("static/media", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)

# Create database tables automatically
Base.metadata.create_all(bind=engine)

app = FastAPI(title="SMS Gateway Backend", version="2.0")

# Enable CORS for the web UI if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (CSS, JS, and user media attachments)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount Jinja2 templates for the modular HTML
templates = Jinja2Templates(directory="templates")

# Register our modular API routers
app.include_router(send.router, prefix="/api/messages", tags=["Send"])
app.include_router(fetch.router, prefix="/api/messages", tags=["Fetch"])
app.include_router(contacts.router, prefix="/api/contacts", tags=["Contacts"])
app.include_router(webhooks.router, prefix="/webhook", tags=["Webhooks"])
app.include_router(events.router, prefix="/events", tags=["Real-Time SSE"])
app.include_router(health.router, prefix="/health", tags=["Health"])

# --- PAGE ROUTES ---
@app.get("/")
async def index_page(request: Request):
    """Serves the main messaging/chat interface."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/contacts")
async def contacts_page(request: Request):
    """Serves the contact management interface."""
    return templates.TemplateResponse(request=request, name="contacts.html")