import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from database import engine, Base
from routers import contacts_router, messages_router
# Import from clean, separate worker module
from worker import sync_inbox_loop

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schemas...")
    Base.metadata.create_all(bind=engine)
    
    logger.info("Spawning background transceiver workers...")
    polling_task = asyncio.create_task(sync_inbox_loop())
    
    yield
    
    logger.info("Canceling background polling tasks...")
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass
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

app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui/messages.html")