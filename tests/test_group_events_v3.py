from __future__ import annotations

import asyncio

from app.group_v3.events import GroupEventBroker
from app.core.config import Settings
from app.db import Base, Database
from app.models import GroupEventOutbox, GroupSpace


def test_group_event_broker_fans_out_bounded_non_secret_invalidations():
    async def scenario():
        broker = GroupEventBroker(queue_size=1)
        async with broker.subscribe("space-1") as first, broker.subscribe("space-1") as second:
            await broker.publish("space-1", "message.created", resource_id="message-1")
            await broker.publish("space-1", "message.updated", resource_id="message-1")
            first_event = first.get_nowait()
            second_event = second.get_nowait()
            assert first_event.event_type == second_event.event_type == "message.updated"
            assert first_event.resource_id == second_event.resource_id == "message-1"
            assert "content" not in first_event.as_dict()
            assert "token" not in first_event.as_dict()

    asyncio.run(scenario())


def test_group_event_outbox_persists_and_is_secret_free(tmp_path):
    database = Database(Settings(database_url=f"sqlite:///{(tmp_path / 'events.sqlite3').as_posix()}"))
    Base.metadata.create_all(database.engine)
    with database.session() as db:
        with db.begin():
            db.add(
                GroupSpace(
                    id="space-events-0001",
                    title="Events",
                    description="",
                    created_by_type="member",
                    created_by_id="member-1",
                    created_by_user_id="user-1",
                )
            )

    async def scenario():
        broker = GroupEventBroker(database=database)
        async with broker.subscribe("space-events-0001") as queue:
            await broker.publish("space-events-0001", "media_session.created", resource_id="session-1")
            event = queue.get_nowait()
            assert event.as_dict() == {
                "event_id": event.event_id,
                "type": "media_session.created",
                "space_id": "space-events-0001",
                "resource_id": "session-1",
            }
            assert "token" not in event.as_dict()
            return event.event_id

    event_id = asyncio.run(scenario())
    with database.session() as db:
        row = db.get(GroupEventOutbox, event_id)
        assert row is not None
        assert row.status == "pending"
        assert row.published_at is None
    database.dispose()


def test_group_event_outbox_drain_is_noop_before_stale_local_migration(tmp_path):
    database = Database(Settings(database_url=f"sqlite:///{(tmp_path / 'stale.sqlite3').as_posix()}"))

    async def scenario():
        broker = GroupEventBroker(database=database)
        assert await broker.drain_outbox() == 0

    asyncio.run(scenario())
    database.dispose()


def test_group_event_enqueue_is_atomic_with_business_transaction(tmp_path):
    database = Database(Settings(database_url=f"sqlite:///{(tmp_path / 'atomic.sqlite3').as_posix()}"))
    Base.metadata.create_all(database.engine)
    broker = GroupEventBroker(database=database)

    try:
        with database.session() as db:
            try:
                with db.begin():
                    db.add(
                        GroupSpace(
                            id="space-atomic-rollback",
                            title="Rollback",
                            description="",
                            created_by_type="member",
                            created_by_id="member-1",
                            created_by_user_id="user-1",
                        )
                    )
                    db.flush()
                    broker.enqueue_in_transaction(db, "space-atomic-rollback", "space.created", resource_id="space-atomic-rollback")
                    raise RuntimeError("force rollback")
            except RuntimeError:
                pass
        with database.session() as db:
            assert db.get(GroupSpace, "space-atomic-rollback") is None
            assert db.get(GroupEventOutbox, "space-atomic-rollback") is None

        with database.session() as db:
            with db.begin():
                db.add(
                    GroupSpace(
                        id="space-atomic-commit",
                        title="Commit",
                        description="",
                        created_by_type="member",
                        created_by_id="member-1",
                        created_by_user_id="user-1",
                    )
                )
                db.flush()
                event_id = broker.enqueue_in_transaction(db, "space-atomic-commit", "space.created", resource_id="space-atomic-commit")
        with database.session() as db:
            row = db.get(GroupEventOutbox, event_id)
            assert row is not None and row.status == "pending"
    finally:
        database.dispose()
