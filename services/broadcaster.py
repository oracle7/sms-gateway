import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Set

from config import settings
from database import utc_now
from version import APP_VERSION, BUILD_ID

logger = logging.getLogger("uvicorn.error")


@dataclass(eq=False)
class SSEClient:
    session_id: str
    queue: asyncio.Queue


class EventBroadcaster:
    """In-memory pub/sub hub for authenticated SSE clients."""

    def __init__(self) -> None:
        self.clients: Set[SSEClient] = set()

    @staticmethod
    def _format_sse(event_type: str, data: Dict[str, Any]) -> str:
        payload = json.dumps({"type": event_type, "data": data}, default=str)
        return f"data: {payload}\n\n"

    async def connect(self, session_id: str):
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        client = SSEClient(session_id=session_id, queue=queue)
        self.clients.add(client)
        logger.info(f"SSE client connected (session={session_id[:8]}...). Total: {len(self.clients)}")

        try:
            yield self._format_sse(
                "hello",
                {
                    "build_id": BUILD_ID,
                    "app_version": APP_VERSION,
                    "server_time": utc_now().isoformat(),
                },
            )

            while True:
                try:
                    msg = await asyncio.wait_for(
                        queue.get(),
                        timeout=float(settings.SSE_HEARTBEAT_SECONDS),
                    )
                    if msg is None:
                        break
                    yield msg
                except asyncio.TimeoutError:
                    yield self._format_sse("ping", {"ts": utc_now().isoformat()})
        finally:
            self.clients.discard(client)
            logger.info(f"SSE client disconnected (session={session_id[:8]}...). Total: {len(self.clients)}")

    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        formatted = self._format_sse(event_type, data)
        for client in list(self.clients):
            try:
                client.queue.put_nowait(formatted)
            except asyncio.QueueFull:
                try:
                    client.queue.get_nowait()
                    client.queue.put_nowait(formatted)
                except Exception:
                    self.clients.discard(client)

    async def disconnect_session(self, session_id: str, reason: str = "session_expired") -> None:
        """Notifies and closes all SSE streams belonging to a specific session."""
        formatted = self._format_sse("session_expired", {"reason": reason})
        for client in list(self.clients):
            if client.session_id == session_id:
                try:
                    client.queue.put_nowait(formatted)
                    client.queue.put_nowait(None)
                except asyncio.QueueFull:
                    self.clients.discard(client)


broadcaster = EventBroadcaster()
