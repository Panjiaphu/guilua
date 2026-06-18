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
