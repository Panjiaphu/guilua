from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransactionType(StrEnum):
    SEND_HOME = "send_home"
    BUY_USDT = "buy_usdt"
    SELL_USDT = "sell_usdt"


class TransactionStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    NEEDS_INFO = "needs_info"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EmailStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class ContentPostStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ContentPostSource(StrEnum):
    ADMIN = "admin"
    AI_AGENT = "ai_agent"


class ContentPostType(StrEnum):
    JOB = "job"
    SHOP = "shop"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    locale: Mapped[str] = mapped_column(String(12), default="vi")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transactions: Mapped[list["TransactionRequest"]] = relationship(back_populates="user")
    email_replies: Mapped[list["EmailReply"]] = relationship(back_populates="user")
    service_requests: Mapped[list["ServiceRequest"]] = relationship(back_populates="user")
    content_posts: Mapped[list["ContentPost"]] = relationship(back_populates="created_by")
    utility_usage: Mapped[list["MemberUtilityUsage"]] = relationship(back_populates="user")


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair: Mapped[str] = mapped_column(String(32), index=True)
    buy_rate: Mapped[float] = mapped_column(Numeric(18, 6))
    sell_rate: Mapped[float] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(32), default="manual")
    is_manual: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_exchange_rates_pair_updated", "pair", "updated_at"),)


class TransactionRequest(Base):
    __tablename__ = "transaction_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), index=True)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), default=TransactionStatus.PENDING, index=True
    )
    amount_twd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_vnd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_usdt: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    rate_pair: Mapped[str] = mapped_column(String(32), default="")
    rate_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    recipient_name: Mapped[str] = mapped_column(String(120), default="")
    recipient_bank: Mapped[str] = mapped_column(String(120), default="")
    recipient_account: Mapped[str] = mapped_column(String(120), default="")
    contact_phone: Mapped[str] = mapped_column(String(64), default="")
    contact_line: Mapped[str] = mapped_column(String(120), default="")
    usdt_network: Mapped[str] = mapped_column(String(32), default="")
    wallet_address: Mapped[str] = mapped_column(String(255), default="")
    member_note: Mapped[str] = mapped_column(Text, default="")
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="transactions")
    email_replies: Mapped[list["EmailReply"]] = relationship(back_populates="transaction")


class EmailNotification(Base):
    __tablename__ = "email_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[EmailStatus] = mapped_column(Enum(EmailStatus), default=EmailStatus.QUEUED, index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transaction_requests.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailReply(Base):
    __tablename__ = "email_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender: Mapped[str] = mapped_column(String(255), index=True)
    recipient: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    provider_message_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    raw_payload: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transaction_requests.id"), nullable=True, index=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User | None] = relationship(back_populates="email_replies")
    transaction: Mapped[TransactionRequest | None] = relationship(back_populates="email_replies")


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    service_type: Mapped[str] = mapped_column(String(64), default="ip_switch", index=True)
    status: Mapped[str] = mapped_column(String(32), default=TransactionStatus.PENDING.value, index=True)
    target_region: Mapped[str] = mapped_column(String(64), default="")
    protocol: Mapped[str] = mapped_column(String(64), default="")
    duration_hours: Mapped[int] = mapped_column(Integer, default=24)
    device_label: Mapped[str] = mapped_column(String(120), default="")
    current_ip: Mapped[str] = mapped_column(String(80), default="")
    member_note: Mapped[str] = mapped_column(Text, default="")
    assigned_endpoint: Mapped[str] = mapped_column(String(255), default="")
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="service_requests")


class ContentPost(Base):
    __tablename__ = "content_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_type: Mapped[ContentPostType] = mapped_column(Enum(ContentPostType), index=True)
    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    target_url: Mapped[str] = mapped_column(String(500), default="")
    platform: Mapped[str] = mapped_column(String(64), default="other", index=True)
    locale: Mapped[str] = mapped_column(String(12), default="vi", index=True)
    status: Mapped[ContentPostStatus] = mapped_column(
        Enum(ContentPostStatus), default=ContentPostStatus.DRAFT, index=True
    )
    source: Mapped[ContentPostSource] = mapped_column(
        Enum(ContentPostSource), default=ContentPostSource.ADMIN, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    ai_agent_name: Mapped[str] = mapped_column(String(120), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    tags: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    created_by: Mapped[User | None] = relationship(back_populates="content_posts")

    __table_args__ = (
        Index("ix_content_posts_type_status_locale", "post_type", "status", "locale"),
        Index("ix_content_posts_type_sort", "post_type", "sort_order", "created_at"),
    )


class AiAgentApiKey(Base):
    __tablename__ = "ai_agent_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    allowed_post_types: Mapped[str] = mapped_column(Text, default='["job","shop"]')
    can_auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    logs: Mapped[list["AiAgentPostLog"]] = relationship(back_populates="agent_key")


class AiAgentPostLog(Base):
    __tablename__ = "ai_agent_post_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_key_id: Mapped[int | None] = mapped_column(ForeignKey("ai_agent_api_keys.id"), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    post_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    request_ip: Mapped[str] = mapped_column(String(64), default="")
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_post_id: Mapped[int | None] = mapped_column(ForeignKey("content_posts.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent_key: Mapped[AiAgentApiKey | None] = relationship(back_populates="logs")


class UtilityItem(Base):
    __tablename__ = "utility_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(64), default="spark")
    route_path: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_member_only: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_free: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MemberUtilityUsage(Base):
    __tablename__ = "member_utility_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    utility_key: Mapped[str] = mapped_column(String(80), index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="utility_usage")

    __table_args__ = (Index("ix_member_utility_usage_user_key", "user_id", "utility_key", unique=True),)


class ShortLink(Base):
    __tablename__ = "short_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    target_url: Mapped[str] = mapped_column(String(700))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
