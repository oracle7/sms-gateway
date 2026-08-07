import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from database import engine, Base
# Added the webhook router import here:
from routers import contacts_router, messages_router
from routers.webhook import router as webhook_router

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schemas...")
    Base.metadata.create_all(bind=engine)
    
    os.makedirs("static/media", exist_ok=True)
    
    # The background polling worker has been intentionally removed here
    # to favor the new push-based webhook architecture.
    logger.info("SMS Gateway service started (Webhook mode active).")
    
    yield
    
    logger.info("SMS Gateway service stopped cleanly.")

app = FastAPI(
    title="SMS Gateway API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contacts_router)
app.include_router(messages_router)
# Mount the new webhook router:
app.include_router(webhook_router)

app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui/messages.html")