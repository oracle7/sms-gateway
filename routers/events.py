from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from services.broadcaster import broadcaster

router = APIRouter()

@router.get("/")
async def sse_endpoint(request: Request):
    """
    Server-Sent Events (SSE) endpoint.
    The web UI's JavaScript connects here via EventSource("/events")
    to receive real-time webhook updates without polling.
    """
    return StreamingResponse(
        broadcaster.connect(), 
        media_type="text/event-stream"
    )