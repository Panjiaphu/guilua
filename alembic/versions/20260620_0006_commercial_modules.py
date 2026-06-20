"""add commercial content utilities and ai agent api

Revision ID: 20260620_0006
Revises: 20260619_0005
Create Date: 2026-06-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260620_0006"
down_revision: str | None = "20260619_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_type", sa.Enum("JOB", "SHOP", name="contentposttype"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=12), nullable=False),
        sa.Column("status", sa.Enum("DRAFT", "PUBLISHED", "ARCHIVED", name="contentpoststatus"), nullable=False),
        sa.Column("source", sa.Enum("ADMIN", "AI_AGENT", name="contentpostsource"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("ai_agent_name", sa.String(length=120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_posts_created_by_user_id", "content_posts", ["created_by_user_id"])
    op.create_index("ix_content_posts_locale", "content_posts", ["locale"])
    op.create_index("ix_content_posts_platform", "content_posts", ["platform"])
    op.create_index("ix_content_posts_published_at", "content_posts", ["published_at"])
    op.create_index("ix_content_posts_slug", "content_posts", ["slug"], unique=True)
    op.create_index("ix_content_posts_sort_order", "content_posts", ["sort_order"])
    op.create_index("ix_content_posts_source", "content_posts", ["source"])
    op.create_index("ix_content_posts_status", "content_posts", ["status"])
    op.create_index("ix_content_posts_type_sort", "content_posts", ["post_type", "sort_order", "created_at"])
    op.create_index("ix_content_posts_type_status_locale", "content_posts", ["post_type", "status", "locale"])

    op.create_table(
        "ai_agent_api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("allowed_post_types", sa.Text(), nullable=False),
        sa.Column("can_auto_publish", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_api_keys_is_active", "ai_agent_api_keys", ["is_active"])
    op.create_index("ix_ai_agent_api_keys_key_hash", "ai_agent_api_keys", ["key_hash"], unique=True)
    op.create_index("ix_ai_agent_api_keys_prefix", "ai_agent_api_keys", ["prefix"])

    op.create_table(
        "ai_agent_post_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_key_id", sa.Integer(), nullable=True),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("post_type", sa.String(length=32), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_post_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_key_id"], ["ai_agent_api_keys.id"]),
        sa.ForeignKeyConstraint(["created_post_id"], ["content_posts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_agent_post_logs_agent_key_id", "ai_agent_post_logs", ["agent_key_id"])
    op.create_index("ix_ai_agent_post_logs_created_post_id", "ai_agent_post_logs", ["created_post_id"])
    op.create_index("ix_ai_agent_post_logs_post_type", "ai_agent_post_logs", ["post_type"])

    op.create_table(
        "utility_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=False),
        sa.Column("route_path", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_member_only", sa.Boolean(), nullable=False),
        sa.Column("is_free", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_utility_items_is_active", "utility_items", ["is_active"])
    op.create_index("ix_utility_items_is_member_only", "utility_items", ["is_member_only"])
    op.create_index("ix_utility_items_key", "utility_items", ["key"], unique=True)
    op.create_index("ix_utility_items_sort_order", "utility_items", ["sort_order"])

    op.create_table(
        "member_utility_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("utility_key", sa.String(length=80), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_member_utility_usage_user_id", "member_utility_usage", ["user_id"])
    op.create_index("ix_member_utility_usage_user_key", "member_utility_usage", ["user_id", "utility_key"], unique=True)
    op.create_index("ix_member_utility_usage_utility_key", "member_utility_usage", ["utility_key"])

    op.create_table(
        "short_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("target_url", sa.String(length=700), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("click_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_short_links_code", "short_links", ["code"], unique=True)
    op.create_index("ix_short_links_user_id", "short_links", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_short_links_user_id", table_name="short_links")
    op.drop_index("ix_short_links_code", table_name="short_links")
    op.drop_table("short_links")
    op.drop_index("ix_member_utility_usage_utility_key", table_name="member_utility_usage")
    op.drop_index("ix_member_utility_usage_user_key", table_name="member_utility_usage")
    op.drop_index("ix_member_utility_usage_user_id", table_name="member_utility_usage")
    op.drop_table("member_utility_usage")
    op.drop_index("ix_utility_items_sort_order", table_name="utility_items")
    op.drop_index("ix_utility_items_key", table_name="utility_items")
    op.drop_index("ix_utility_items_is_member_only", table_name="utility_items")
    op.drop_index("ix_utility_items_is_active", table_name="utility_items")
    op.drop_table("utility_items")
    op.drop_index("ix_ai_agent_post_logs_post_type", table_name="ai_agent_post_logs")
    op.drop_index("ix_ai_agent_post_logs_created_post_id", table_name="ai_agent_post_logs")
    op.drop_index("ix_ai_agent_post_logs_agent_key_id", table_name="ai_agent_post_logs")
    op.drop_table("ai_agent_post_logs")
    op.drop_index("ix_ai_agent_api_keys_prefix", table_name="ai_agent_api_keys")
    op.drop_index("ix_ai_agent_api_keys_key_hash", table_name="ai_agent_api_keys")
    op.drop_index("ix_ai_agent_api_keys_is_active", table_name="ai_agent_api_keys")
    op.drop_table("ai_agent_api_keys")
    op.drop_index("ix_content_posts_type_status_locale", table_name="content_posts")
    op.drop_index("ix_content_posts_type_sort", table_name="content_posts")
    op.drop_index("ix_content_posts_status", table_name="content_posts")
    op.drop_index("ix_content_posts_source", table_name="content_posts")
    op.drop_index("ix_content_posts_sort_order", table_name="content_posts")
    op.drop_index("ix_content_posts_slug", table_name="content_posts")
    op.drop_index("ix_content_posts_published_at", table_name="content_posts")
    op.drop_index("ix_content_posts_platform", table_name="content_posts")
    op.drop_index("ix_content_posts_locale", table_name="content_posts")
    op.drop_index("ix_content_posts_created_by_user_id", table_name="content_posts")
    op.drop_table("content_posts")
