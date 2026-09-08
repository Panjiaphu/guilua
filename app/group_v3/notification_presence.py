from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import Any


logger = logging.getLogger(__name__)


class GroupNotificationPresence:
    """Short-lived, Group-namespaced visible-tab presence in Valkey/Redis."""

    SURFACES = ("chat", "chat-translation", "call", "video", "radio")

    def __init__(self, redis_url: str | None, namespace: str, ttl_seconds: int = 75) -> None:
        self.redis_url = str(redis_url or "").strip()
        self.namespace = str(namespace or "ai-communication:group-v3").strip()
        self.ttl_seconds = max(60, min(int(ttl_seconds), 90))
        self._client: Any | None = None

    def _key(self, space_id: str, membership_id: str) -> str:
        return f"{self.namespace}:notification-presence:{space_id}:{membership_id}"

    def _redis(self):
        if not self.redis_url:
            return None
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def heartbeat(
        self,
        space_id: str,
        membership_id: str,
        tab_id: str,
        surface: str,
        visible: bool,
    ) -> bool:
        client = self._redis()
        if client is None:
            return False
        key = self._key(space_id, membership_id)
        now = time.time()
        try:
            pipeline = client.pipeline(transaction=True)
            pipeline.zremrangebyscore(key, "-inf", now)
            if visible:
                pipeline.zadd(key, {f"{tab_id}:{surface}": now + self.ttl_seconds})
                pipeline.expire(key, self.ttl_seconds + 5)
            else:
                pipeline.zrem(key, *[f"{tab_id}:{item}" for item in self.SURFACES])
            await pipeline.execute()
            return True
        except Exception as exc:  # pragma: no cover - external Valkey failure
            logger.warning("Group notification presence heartbeat failed: %s", exc)
            return False

    async def is_active(self, space_id: str, membership_id: str) -> bool | None:
        client = self._redis()
        if client is None:
            return None
        key = self._key(space_id, membership_id)
        try:
            pipeline = client.pipeline(transaction=True)
            pipeline.zremrangebyscore(key, "-inf", time.time())
            pipeline.zcard(key)
            result = await pipeline.execute()
            return bool(int(result[-1] or 0))
        except Exception as exc:  # pragma: no cover - external Valkey failure
            logger.warning("Group notification presence lookup failed: %s", exc)
            return None

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with suppress(Exception):
                close = getattr(client, "aclose", None) or getattr(client, "close", None)
                if close:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
