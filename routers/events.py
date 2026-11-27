from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from services.auth import AuthContext, require_auth_no_refresh
from services.broadcaster import broadcaster

router = APIRouter()


@router.get("")
@router.get("/")
async def sse_endpoint(auth: AuthContext = Depends(require_auth_no_refresh)):
    """Authenticated Server-Sent Events stream for real-time clinic updates."""
    return StreamingResponse(
        broadcaster.connect(auth.session.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
