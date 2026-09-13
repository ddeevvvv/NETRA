import asyncio
import logging
from typing import List
from fastapi import WebSocket
from redis.asyncio import Redis
from app.core.config import settings

logger = logging.getLogger("ibvap.websocket")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total active clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Remaining active clients: {len(self.active_connections)}")

    async def broadcast_text(self, message: str):
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Error sending message to WebSocket client: {e}")
                disconnected.append(connection)
        
        # Clean up any dead connections
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

async def redis_subscriber_loop():
    """Background task to listen for Redis pub/sub messages and broadcast to WebSocket clients."""
    pubsub = None
    redis_client = None
    while True:
        try:
            redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(settings.REDIS_ALERTS_CHANNEL)
            logger.info(f"Subscribed to Redis pub/sub channel '{settings.REDIS_ALERTS_CHANNEL}'")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    payload = message["data"]
                    await manager.broadcast_text(payload)

        except asyncio.CancelledError:
            logger.info("Redis subscriber task cancelled.")
            break
        except Exception as e:
            logger.debug(f"Redis pub/sub connection retry: {e}")
            await asyncio.sleep(5)  # Retry connection every 5 seconds without crashing app
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(settings.REDIS_ALERTS_CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    pass
            if redis_client:
                try:
                    await redis_client.aclose()
                except Exception:
                    pass
