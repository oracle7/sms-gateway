import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from config import settings
from database import SessionLocal, init_db
from routers import admin, attachments, auth, contacts, events, health, messages, pages, threads, webhooks
from services.auth import session_reaper_loop
from services.broadcaster import broadcaster
from services.media import ensure_media_dir
from version import APP_VERSION

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_media_dir()
    init_db()
    if not settings.WEBHOOK_VERIFY_SIGNATURE:
        logger.warning(
            "WEBHOOK_VERIFY_SIGNATURE is false. Configure Signing Key in Pixel 6 app and enable it for full protection."
        )
    reaper_task = asyncio.create_task(session_reaper_loop(SessionLocal, broadcaster))
    try:
        yield
    finally:
        reaper_task.cancel()
        try:
            await reaper_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="SMS & MMS Gateway", version=APP_VERSION, lifespan=lifespan)

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    path = request.url.path
    if path.startswith("/static/"):
        if path.startswith("/static/css/") or path.startswith("/static/js/"):
            response.headers["Cache-Control"] = "no-cache"
    elif "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(threads.router, prefix="/api/threads", tags=["Threads"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])
app.include_router(attachments.router, prefix="/api/attachments", tags=["Attachments"])
app.include_router(contacts.router, prefix="/api/contacts", tags=["Contacts"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(webhooks.router, prefix="/webhook", tags=["Webhooks"])
app.include_router(events.router, prefix="/events", tags=["SSE"])
app.include_router(health.router, tags=["Health"])

pages.register_page_routes(app)
