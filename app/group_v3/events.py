from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from contextvars import ContextVar
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.models import GroupEventOutbox


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GroupEvent:
    __slots__ = ("event_id", "event_type", "space_id", "resource_id")

    def __init__(self, event_id: str, event_type: str, space_id: str, resource_id: str) -> None:
        self.event_id = event_id
        self.event_type = event_type
        self.space_id = space_id
        self.resource_id = resource_id

    def as_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "type": self.event_type,
            "space_id": self.space_id,
            "resource_id": self.resource_id,
        }


class GroupEventBroker:
    """Durable invalidation outbox plus local/Redis fan-out.

    PostgreSQL remains the source of truth. The outbox and Redis payload never
    contain message text, media grants, tokens, or user secrets; clients only
    receive a signal to re-read authorized Group APIs.
    """

    def __init__(
        self,
        *,
        queue_size: int = 32,
        database: Any | None = None,
        redis_url: str | None = None,
        redis_namespace: str = "ai-communication:group-v3",
    ) -> None:
        self._queue_size = max(1, queue_size)
        self._database = database
        self._redis_url = str(redis_url or "").strip()
        self._channel = f"{str(redis_namespace or 'ai-communication:group-v3').strip()}:events"
        self._instance_id = uuid4().hex
        self._subscribers: dict[str, set[asyncio.Queue[GroupEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._closed = False
        self.notification_dispatcher: Any | None = None
        # Services enqueue events inside their SQLAlchemy transaction.  The
        # request-local handoff lets the router publish that exact row after
        # commit without creating a second semantic event.
        self._transaction_events: ContextVar[dict[tuple[str, str, str], str]] = ContextVar(
            "group_v3_transaction_events", default={}
        )

    @asynccontextmanager
    async def subscribe(self, space_id: str) -> AsyncIterator[asyncio.Queue[GroupEvent]]:
        queue: asyncio.Queue[GroupEvent] = asyncio.Queue(maxsize=self._queue_size)
        normalized_space_id = str(space_id)
        async with self._lock:
            self._subscribers[normalized_space_id].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(normalized_space_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(normalized_space_id, None)

    async def start(self) -> None:
        if not self._redis_url or self._listener_task:
            return
        try:
            import redis.asyncio as redis

            self._redis = redis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            self._listener_task = asyncio.create_task(self._listen_remote())
        except Exception as exc:  # pragma: no cover - depends on external Redis
            logger.warning("Group event Redis unavailable; local fan-out remains active: %s", exc)
            await self._close_redis()

    async def _listen_remote(self) -> None:
        if not self._redis:
            return
        try:
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            await self._pubsub.subscribe(self._channel)
            while not self._closed:
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message:
                    continue
                data = message.get("data")
                if not isinstance(data, str):
                    continue
                try:
                    payload = json.loads(data)
                except (TypeError, ValueError):
                    continue
                if payload.get("origin") == self._instance_id:
                    continue
                event = self._from_wire(payload)
                if event:
                    await self._fanout(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - depends on external Redis
            logger.warning("Group event Redis listener stopped: %s", exc)
        finally:
            if self._pubsub:
                with suppress(Exception):
                    close = getattr(self._pubsub, "aclose", None) or getattr(self._pubsub, "close", None)
                    if close:
                        result = close()
                        if hasattr(result, "__await__"):
                            await result
                self._pubsub = None

    @staticmethod
    def _from_wire(payload: Any) -> GroupEvent | None:
        if not isinstance(payload, dict):
            return None
        event_id = str(payload.get("event_id") or "").strip()
        event_type = str(payload.get("type") or "").strip()
        space_id = str(payload.get("space_id") or "").strip()
        resource_id = str(payload.get("resource_id") or "").strip()
        if not event_id or not event_type or not space_id:
            return None
        return GroupEvent(event_id[:64], event_type[:80], space_id[:36], resource_id[:80])

    async def _fanout(self, event: GroupEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.space_id, ()))
        for queue in subscribers:
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    def _persist_pending(self, event: GroupEvent) -> None:
        if not self._database:
            return
        with self._database.session() as db:
            with db.begin():
                if db.get(GroupEventOutbox, event.event_id):
                    return
                db.add(
                    GroupEventOutbox(
                        id=event.event_id,
                        space_id=event.space_id,
                        event_type=event.event_type,
                        resource_id=event.resource_id,
                        status="pending",
                        next_attempt_at=_now(),
                    )
                )

    def enqueue_in_transaction(self, db: Any, space_id: str, event_type: str, *, resource_id: Any = "") -> str:
        """Insert an outbox row using the caller's already-open transaction.

        No commit is performed here.  If the business transaction rolls back,
        the event row rolls back with it.  The router can subsequently call
        :meth:`publish` and the request-local handoff will dispatch this row.
        """
        normalized_space = str(space_id or "")[:36]
        normalized_type = str(event_type or "group.changed")[:80]
        normalized_resource = str(resource_id or "")[:80]
        event_id = uuid4().hex
        db.add(
            GroupEventOutbox(
                id=event_id,
                space_id=normalized_space,
                event_type=normalized_type,
                resource_id=normalized_resource,
                status="pending",
                next_attempt_at=_now(),
            )
        )
        current = dict(self._transaction_events.get())
        current[(normalized_space, normalized_type, normalized_resource)] = event_id
        self._transaction_events.set(current)
        return event_id

    def _mark(self, event_id: str, *, status: str, error: str = "", attempts: int | None = None) -> None:
        if not self._database:
            return
        with self._database.session() as db:
            with db.begin():
                row = db.get(GroupEventOutbox, event_id)
                if not row:
                    return
                row.status = status
                row.last_error = str(error or "")[:160]
                if attempts is not None:
                    row.attempts = attempts
                if status == "published":
                    row.published_at = _now()

    async def _publish_remote(self, event: GroupEvent) -> None:
        if not self._redis:
            return
        payload = event.as_dict()
        payload["origin"] = self._instance_id
        await self._redis.publish(self._channel, json.dumps(payload, separators=(",", ":")))

    async def publish(self, space_id: str, event_type: str, *, resource_id: Any = "") -> None:
        normalized_space = str(space_id)[:36]
        normalized_type = str(event_type or "group.changed")[:80]
        normalized_resource = str(resource_id or "")[:80]
        key = (normalized_space, normalized_type, normalized_resource)
        event_id = self._transaction_events.get().get(key)
        if event_id:
            remaining = dict(self._transaction_events.get())
            remaining.pop(key, None)
            self._transaction_events.set(remaining)
            event = GroupEvent(event_id, normalized_type, normalized_space, normalized_resource)
        else:
            event = GroupEvent(uuid4().hex, normalized_type, normalized_space, normalized_resource)
            try:
                self._persist_pending(event)
            except Exception as exc:
                logger.exception("Group event outbox write failed: %s", exc)
        await self._fanout(event)
        if self._redis:
            try:
                await self._publish_remote(event)
                self._mark(event.event_id, status="published")
            except Exception as exc:  # pragma: no cover - depends on external Redis
                self._mark(event.event_id, status="failed", error=str(exc), attempts=1)
        else:
            # Local SSE fan-out is useful in a single process, but it is not
            # durable distributed delivery. Keep the row pending so a later
            # worker can retry once Redis/Valkey is available.
            logger.info("Group event queued pending; Redis/Valkey unavailable")
        if self.notification_dispatcher:
            self.notification_dispatcher.kick()

    async def drain_outbox(self, limit: int = 100) -> int:
        if not self._database or not self._redis:
            return 0
        try:
            with self._database.session() as db:
                rows = list(
                    db.scalars(
                        select(GroupEventOutbox)
                        .where(
                            GroupEventOutbox.status.in_(("pending", "failed")),
                            GroupEventOutbox.next_attempt_at <= _now(),
                        )
                        .order_by(GroupEventOutbox.created_at, GroupEventOutbox.id)
                        .limit(max(1, min(int(limit), 500)))
                    ).all()
                )
        except (OperationalError, ProgrammingError) as exc:
            # A stale local database can start before its Group migration has
            # been applied. Readiness remains fail-closed; housekeeping must
            # not take down the process while waiting for migration.
            logger.warning("Group event outbox unavailable; skipping drain: %s", exc)
            return 0
        delivered = 0
        for row in rows:
            event = GroupEvent(row.id, row.event_type, row.space_id, row.resource_id)
            try:
                await self._publish_remote(event)
                self._mark(row.id, status="published", attempts=row.attempts + 1)
                delivered += 1
            except Exception as exc:  # pragma: no cover - depends on external Redis
                attempts = row.attempts + 1
                retry_at = _now() + timedelta(seconds=min(300, 2**min(attempts, 8)))
                self._mark(row.id, status="failed", error=str(exc), attempts=attempts)
                with self._database.session() as db:
                    with db.begin():
                        fresh = db.get(GroupEventOutbox, row.id)
                        if fresh:
                            fresh.next_attempt_at = retry_at
        return delivered

    async def _close_redis(self) -> None:
        if self._pubsub:
            with suppress(Exception):
                close = getattr(self._pubsub, "aclose", None) or getattr(self._pubsub, "close", None)
                if close:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
            self._pubsub = None
        if self._redis:
            with suppress(Exception):
                close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
                if close:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
            self._redis = None

    async def close(self) -> None:
        self._closed = True
        if self._listener_task:
            self._listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        await self._close_redis()
