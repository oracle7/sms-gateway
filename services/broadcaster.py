import asyncio
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("uvicorn.error")

class EventBroadcaster:
    def __init__(self):
        # A set to hold all active client queues
        self.connections = set()

    async def connect(self):
        """Called when a new browser opens the web UI."""
        queue = asyncio.Queue()
        self.connections.add(queue)
        logger.info(f"New SSE client connected. Total clients: {len(self.connections)}")
        try:
            while True:
                # Wait until there is a message in the queue to yield to the browser
                yield await queue.get()
        finally:
            self.connections.remove(queue)
            logger.info(f"SSE client disconnected. Total clients: {len(self.connections)}")

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """Called by your webhooks to broadcast to all connected browsers."""
        # SSE format requires "data: <string>\n\n"
        payload = json.dumps({"type": event_type, "data": data})
        sse_formatted_message = f"data: {payload}\n\n"
        
        for queue in self.connections:
            await queue.put(sse_formatted_message)

# Instantiate a single global instance for the whole app to share
broadcaster = EventBroadcaster()