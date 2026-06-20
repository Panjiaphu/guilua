"""add security firewall and crypto analysis content

Revision ID: 20260620_0007
Revises: 20260620_0006
Create Date: 2026-06-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260620_0007"
down_revision: str | None = "20260620_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE contentposttype ADD VALUE IF NOT EXISTS 'CRYPTO_ANALYSIS'")

    op.add_column("content_posts", sa.Column("market_session", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("content_posts", sa.Column("market_bias", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("content_posts", sa.Column("risk_level", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("content_posts", sa.Column("tradingview_symbol", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("content_posts", sa.Column("tradingview_url", sa.String(length=500), nullable=False, server_default=""))
    op.add_column("content_posts", sa.Column("analysis_category", sa.String(length=80), nullable=False, server_default=""))
    op.create_index("ix_content_posts_market_session", "content_posts", ["market_session"])
    op.create_index("ix_content_posts_market_bias", "content_posts", ["market_bias"])
    op.create_index("ix_content_posts_risk_level", "content_posts", ["risk_level"])
    op.create_index("ix_content_posts_analysis_category", "content_posts", ["analysis_category"])

    op.create_table(
        "security_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("rule_type", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_rules_action", "security_rules", ["action"])
    op.create_index("ix_security_rules_created_by_user_id", "security_rules", ["created_by_user_id"])
    op.create_index("ix_security_rules_is_active", "security_rules", ["is_active"])
    op.create_index("ix_security_rules_rule_type", "security_rules", ["rule_type"])
    op.create_index("ix_security_rules_severity", "security_rules", ["severity"])
    op.create_index("ix_security_rules_value", "security_rules", ["value"])

    op.create_table(
        "ip_reputation_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("ip_version", sa.String(length=16), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=False),
        sa.Column("country_name", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("asn", sa.String(length=80), nullable=False),
        sa.Column("isp", sa.String(length=160), nullable=False),
        sa.Column("organization", sa.String(length=160), nullable=False),
        sa.Column("is_proxy", sa.Boolean(), nullable=False),
        sa.Column("is_vpn", sa.Boolean(), nullable=False),
        sa.Column("is_tor", sa.Boolean(), nullable=False),
        sa.Column("is_hosting", sa.Boolean(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ip_reputation_cache_country_code", "ip_reputation_cache", ["country_code"])
    op.create_index("ix_ip_reputation_cache_expires_at", "ip_reputation_cache", ["expires_at"])
    op.create_index("ix_ip_reputation_cache_ip_address", "ip_reputation_cache", ["ip_address"], unique=True)
    op.create_index("ix_ip_reputation_cache_risk_score", "ip_reputation_cache", ["risk_score"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("ip_version", sa.String(length=16), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=False),
        sa.Column("country_name", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("asn", sa.String(length=80), nullable=False),
        sa.Column("isp", sa.String(length=160), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("referer", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username_or_email", sa.String(length=255), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["security_rules.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_events_country_code", "security_events", ["country_code"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])
    op.create_index("ix_security_events_ip_address", "security_events", ["ip_address"])
    op.create_index("ix_security_events_ip_created", "security_events", ["ip_address", "created_at"])
    op.create_index("ix_security_events_path", "security_events", ["path"])
    op.create_index("ix_security_events_request_id", "security_events", ["request_id"])
    op.create_index("ix_security_events_risk_score", "security_events", ["risk_score"])
    op.create_index("ix_security_events_rule_id", "security_events", ["rule_id"])
    op.create_index("ix_security_events_severity", "security_events", ["severity"])
    op.create_index("ix_security_events_type_created", "security_events", ["event_type", "created_at"])
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"])
    op.create_index("ix_security_events_username_or_email", "security_events", ["username_or_email"])

    op.create_table(
        "security_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("affected_ip", sa.String(length=80), nullable=False),
        sa.Column("affected_user_id", sa.Integer(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["affected_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_incidents_affected_ip", "security_incidents", ["affected_ip"])
    op.create_index("ix_security_incidents_affected_user_id", "security_incidents", ["affected_user_id"])
    op.create_index("ix_security_incidents_incident_type", "security_incidents", ["incident_type"])
    op.create_index("ix_security_incidents_severity", "security_incidents", ["severity"])
    op.create_index("ix_security_incidents_status", "security_incidents", ["status"])

    op.create_table(
        "security_playbooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("immediate_steps", sa.Text(), nullable=False),
        sa.Column("containment_steps", sa.Text(), nullable=False),
        sa.Column("eradication_steps", sa.Text(), nullable=False),
        sa.Column("recovery_steps", sa.Text(), nullable=False),
        sa.Column("prevention_steps", sa.Text(), nullable=False),
        sa.Column("checklist_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_playbooks_incident_type", "security_playbooks", ["incident_type"], unique=True)
    op.create_index("ix_security_playbooks_is_active", "security_playbooks", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_security_playbooks_is_active", table_name="security_playbooks")
    op.drop_index("ix_security_playbooks_incident_type", table_name="security_playbooks")
    op.drop_table("security_playbooks")
    op.drop_index("ix_security_incidents_status", table_name="security_incidents")
    op.drop_index("ix_security_incidents_severity", table_name="security_incidents")
    op.drop_index("ix_security_incidents_incident_type", table_name="security_incidents")
    op.drop_index("ix_security_incidents_affected_user_id", table_name="security_incidents")
    op.drop_index("ix_security_incidents_affected_ip", table_name="security_incidents")
    op.drop_table("security_incidents")
    op.drop_index("ix_security_events_username_or_email", table_name="security_events")
    op.drop_index("ix_security_events_user_id", table_name="security_events")
    op.drop_index("ix_security_events_type_created", table_name="security_events")
    op.drop_index("ix_security_events_severity", table_name="security_events")
    op.drop_index("ix_security_events_rule_id", table_name="security_events")
    op.drop_index("ix_security_events_risk_score", table_name="security_events")
    op.drop_index("ix_security_events_request_id", table_name="security_events")
    op.drop_index("ix_security_events_path", table_name="security_events")
    op.drop_index("ix_security_events_ip_created", table_name="security_events")
    op.drop_index("ix_security_events_ip_address", table_name="security_events")
    op.drop_index("ix_security_events_event_type", table_name="security_events")
    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_security_events_country_code", table_name="security_events")
    op.drop_table("security_events")
    op.drop_index("ix_ip_reputation_cache_risk_score", table_name="ip_reputation_cache")
    op.drop_index("ix_ip_reputation_cache_ip_address", table_name="ip_reputation_cache")
    op.drop_index("ix_ip_reputation_cache_expires_at", table_name="ip_reputation_cache")
    op.drop_index("ix_ip_reputation_cache_country_code", table_name="ip_reputation_cache")
    op.drop_table("ip_reputation_cache")
    op.drop_index("ix_security_rules_value", table_name="security_rules")
    op.drop_index("ix_security_rules_severity", table_name="security_rules")
    op.drop_index("ix_security_rules_rule_type", table_name="security_rules")
    op.drop_index("ix_security_rules_is_active", table_name="security_rules")
    op.drop_index("ix_security_rules_created_by_user_id", table_name="security_rules")
    op.drop_index("ix_security_rules_action", table_name="security_rules")
    op.drop_table("security_rules")
    op.drop_index("ix_content_posts_analysis_category", table_name="content_posts")
    op.drop_index("ix_content_posts_risk_level", table_name="content_posts")
    op.drop_index("ix_content_posts_market_bias", table_name="content_posts")
    op.drop_index("ix_content_posts_market_session", table_name="content_posts")
    op.drop_column("content_posts", "analysis_category")
    op.drop_column("content_posts", "tradingview_url")
    op.drop_column("content_posts", "tradingview_symbol")
    op.drop_column("content_posts", "risk_level")
    op.drop_column("content_posts", "market_bias")
    op.drop_column("content_posts", "market_session")
