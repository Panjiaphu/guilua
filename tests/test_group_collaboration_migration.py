from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app import models as _models
from app.core.config import get_settings
from app.db import Base


ROOT = Path(__file__).resolve().parents[1]
LEGACY_REVISION = "20260904_0023"
COLLABORATION_REVISION = "20260907_0024"


def _alembic_config(database_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


def _bootstrap_legacy_revision(database_path: Path, config: Config) -> None:
    """Create 0023 through the migration-under-test, not older SQLite history.

    Historical revisions are immutable and include PostgreSQL-oriented ALTER
    statements that SQLite cannot execute. Build the current ORM schema, add
    the migration-only archive table, then exercise the 0024 downgrade to get
    the exact legacy shape used by these round-trip tests.
    """

    assert _models.GroupSpace.__tablename__ == "group_spaces"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE group_chat_translation_legacy_archive (
                    id VARCHAR(36) PRIMARY KEY,
                    space_id VARCHAR(36) NOT NULL,
                    message_id VARCHAR(36) NOT NULL,
                    recipient_membership_id VARCHAR(36) NOT NULL,
                    idempotency_key VARCHAR(128) NOT NULL,
                    message_fingerprint VARCHAR(64) NOT NULL,
                    source_language VARCHAR(8) NOT NULL,
                    target_language VARCHAR(8) NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    translated_ciphertext BLOB,
                    translated_nonce BLOB,
                    encryption_version VARCHAR(32) NOT NULL,
                    provider_model VARCHAR(80) NOT NULL,
                    provider_request_id VARCHAR(128) NOT NULL,
                    failure_code VARCHAR(80) NOT NULL,
                    final_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": COLLABORATION_REVISION},
        )
    engine.dispose()
    command.downgrade(config, LEGACY_REVISION)


def _seed_legacy_rows(database_path: Path) -> list[dict]:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = "2026-09-07 08:30:00.000000"
    rows = [
        {
            "id": "translation-final-legacy-00000001",
            "recipient_membership_id": "membership-owner-legacy-00000001",
            "idempotency_key": "legacy-final-request",
            "status": "final",
            "translated_ciphertext": b"\x01legacy-final-ciphertext\xff",
            "translated_nonce": b"legacy-final",
            "encryption_version": "aes-256-gcm-v1",
            "provider_model": "legacy-model",
            "provider_request_id": "legacy-provider-request",
            "failure_code": "",
            "final_at": now,
        },
        {
            "id": "translation-pending-legacy-0001",
            "recipient_membership_id": "membership-member-legacy-0000001",
            "idempotency_key": "legacy-pending-request",
            "status": "pending",
            "translated_ciphertext": None,
            "translated_nonce": None,
            "encryption_version": "",
            "provider_model": "",
            "provider_request_id": "",
            "failure_code": "",
            "final_at": None,
        },
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO group_spaces (
                    id, title, description, created_by_type, created_by_id,
                    created_by_user_id, lifecycle_status, version,
                    message_sequence, created_at, updated_at
                ) VALUES (
                    :id, 'Migration QA', '', 'member', '42', '42',
                    'active', 1, 1, :now, :now
                )
                """
            ),
            {"id": "space-legacy-0000000000000000000001", "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO group_memberships (
                    id, space_id, principal_type, principal_id,
                    principal_user_id, display_name, role, status,
                    joined_at, updated_at
                ) VALUES
                    (:owner, :space, 'member', '42', '42', 'Owner',
                     'owner', 'active', :now, :now),
                    (:member, :space, 'member', '84', '84', 'Member',
                     'member', 'active', :now, :now)
                """
            ),
            {
                "owner": rows[0]["recipient_membership_id"],
                "member": rows[1]["recipient_membership_id"],
                "space": "space-legacy-0000000000000000000001",
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO group_messages (
                    id, space_id, sequence, sender_type, sender_id,
                    sender_user_id, sender_display_name, client_message_id,
                    source_language, content_type, content_ciphertext,
                    content_nonce, encryption_version, status, created_at
                ) VALUES (
                    :id, :space, 1, 'member', '42', '42', 'Owner',
                    'legacy-message-client-id', 'vi', 'text', :ciphertext,
                    :nonce, 'aes-256-gcm-v1', 'active', :now
                )
                """
            ),
            {
                "id": "message-legacy-00000000000000000001",
                "space": "space-legacy-0000000000000000000001",
                "ciphertext": b"source-ciphertext",
                "nonce": b"source-nonce",
                "now": now,
            },
        )
        for row in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO group_chat_translations (
                        id, space_id, message_id, recipient_membership_id,
                        idempotency_key, message_fingerprint, source_language,
                        target_language, status, translated_ciphertext,
                        translated_nonce, encryption_version, provider_model,
                        provider_request_id, failure_code, final_at,
                        created_at, updated_at
                    ) VALUES (
                        :id, :space_id, :message_id, :recipient_membership_id,
                        :idempotency_key, :message_fingerprint, 'vi', 'en',
                        :status, :translated_ciphertext, :translated_nonce,
                        :encryption_version, :provider_model,
                        :provider_request_id, :failure_code, :final_at,
                        :created_at, :updated_at
                    )
                    """
                ),
                {
                    **row,
                    "space_id": "space-legacy-0000000000000000000001",
                    "message_id": "message-legacy-00000000000000000001",
                    "message_fingerprint": "f" * 64,
                    "created_at": now,
                    "updated_at": now,
                },
            )
    engine.dispose()
    return rows


def _legacy_snapshot(database_path: Path) -> list[dict]:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, recipient_membership_id, idempotency_key, status,
                       translated_ciphertext, translated_nonce,
                       encryption_version, provider_model,
                       provider_request_id, failure_code
                FROM group_chat_translations
                ORDER BY id
                """
            )
        ).mappings().all()
        result = [dict(row) for row in rows]
    engine.dispose()
    return result


def test_0024_preserves_legacy_encrypted_rows_across_upgrade_downgrade_upgrade(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "group-collaboration-migration.sqlite3"
    config = _alembic_config(database_path, monkeypatch)
    _bootstrap_legacy_revision(database_path, config)
    seeded = _seed_legacy_rows(database_path)
    expected = sorted(
        (
            {
                key: row[key]
                for key in (
                    "id",
                    "recipient_membership_id",
                    "idempotency_key",
                    "status",
                    "translated_ciphertext",
                    "translated_nonce",
                    "encryption_version",
                    "provider_model",
                    "provider_request_id",
                    "failure_code",
                )
            }
            for row in seeded
        ),
        key=lambda row: row["id"],
    )

    command.upgrade(config, COLLABORATION_REVISION)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        archive = connection.execute(
            text(
                """
                SELECT id, recipient_membership_id, idempotency_key, status,
                       translated_ciphertext, translated_nonce,
                       encryption_version, provider_model,
                       provider_request_id, failure_code
                FROM group_chat_translation_legacy_archive
                ORDER BY id
                """
            )
        ).mappings().all()
        current = connection.execute(
            text(
                """
                SELECT id, recipient_membership_id, status, cost_state,
                       translated_ciphertext, translated_nonce
                FROM group_chat_translations
                """
            )
        ).mappings().all()
        historical_events = connection.execute(
            text(
                "SELECT COUNT(*) FROM group_event_outbox "
                "WHERE notification_status != 'completed'"
            )
        ).scalar_one()
    engine.dispose()

    assert [dict(row) for row in archive] == expected
    assert len(current) == 1
    assert current[0]["id"] == seeded[0]["id"]
    assert current[0]["recipient_membership_id"] == seeded[0]["recipient_membership_id"]
    assert current[0]["status"] == "final"
    assert current[0]["cost_state"] == "settled"
    assert current[0]["translated_ciphertext"] == seeded[0]["translated_ciphertext"]
    assert current[0]["translated_nonce"] == seeded[0]["translated_nonce"]
    assert historical_events == 0

    command.downgrade(config, LEGACY_REVISION)
    assert _legacy_snapshot(database_path) == expected

    command.upgrade(config, COLLABORATION_REVISION)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM group_chat_translation_legacy_archive")
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM group_chat_translations")
        ).scalar_one() == 1
    engine.dispose()
    get_settings.cache_clear()


def test_0024_membership_deletion_keeps_cost_history_and_downgrades_safely(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "group-collaboration-membership-delete.sqlite3"
    config = _alembic_config(database_path, monkeypatch)
    _bootstrap_legacy_revision(database_path, config)
    seeded = _seed_legacy_rows(database_path)
    command.upgrade(config, COLLABORATION_REVISION)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.commit()
        with connection.begin():
            connection.execute(
                text("DELETE FROM group_memberships WHERE id = :membership_id"),
                {"membership_id": seeded[0]["recipient_membership_id"]},
            )
            assert connection.execute(
                text("SELECT COUNT(*) FROM group_chat_translations")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT COUNT(*) FROM group_chat_translation_requests")
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM group_chat_translation_legacy_archive "
                    "WHERE recipient_membership_id = :membership_id"
                ),
                {"membership_id": seeded[0]["recipient_membership_id"]},
            ).scalar_one() == 0
    engine.dispose()

    command.downgrade(config, LEGACY_REVISION)
    snapshot = _legacy_snapshot(database_path)
    assert [row["id"] for row in snapshot] == [seeded[1]["id"]]
    assert snapshot[0]["translated_ciphertext"] == seeded[1]["translated_ciphertext"]
    get_settings.cache_clear()
