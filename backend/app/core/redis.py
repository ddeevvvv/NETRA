import json
import logging
from typing import Dict, Any
from redis.asyncio import Redis
from app.core.config import settings
from app.core.websocket_manager import manager

logger = logging.getLogger("ibvap.redis")

async def publish_event(event_data: Dict[str, Any]):
    """
    Publishes event JSON to Redis pub/sub channel 'ibvap:alerts'
    and ensures connected WebSocket clients receive it immediately.
    """
    event_json = json.dumps(event_data, default=str)

    # 1. Directly broadcast to local active WebSockets
    await manager.broadcast_text(event_json)

    # 2. Publish to Redis Pub/Sub if Redis is available
    try:
        redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.publish(settings.REDIS_ALERTS_CHANNEL, event_json)
        await redis_client.aclose()
        logger.debug(f"Published event to Redis channel '{settings.REDIS_ALERTS_CHANNEL}'")
    except Exception as e:
        logger.debug(f"Redis publish fallback (Redis offline or unreachable): {e}")
