import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from database import engine, Base
from routers import contacts_router, messages_router
from routers.webhook import router as webhook_router

# DISABLED WORKER:
# import worker 

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schemas...")
    Base.metadata.create_all(bind=engine)
    
    os.makedirs("static/media", exist_ok=True)
    
    # --- DISABLED WORKER ROUTINE ---
    # logger.info("Starting background polling worker...")
    # polling_task = asyncio.create_task(worker.sync_inbox_loop())
    
    logger.info("SMS Gateway service started (Webhook mode active).")
    
    yield
    
    # --- CLEANUP ON SHUTDOWN ---
    # logger.info("Cancelling background polling worker...")
    # polling_task.cancel()
    # try:
    #     await polling_task
    # except asyncio.CancelledError:
    #     pass
        
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
app.include_router(webhook_router)

app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui/messages.html")