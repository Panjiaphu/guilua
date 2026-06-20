from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AiAgentApiKey,
    AiAgentPostLog,
    ContentPost,
    ContentPostSource,
    ContentPostStatus,
    ContentPostType,
    MemberUtilityUsage,
    ShortLink,
    UtilityItem,
    User,
)


DEFAULT_UTILITIES = (
    {
        "key": "free_vpn_random_ip",
        "title": "Free VPN / Random IP",
        "description": "Trang tải và hướng dẫn tiện ích chuyển IP khi admin cấu hình link.",
        "icon": "shield",
        "route_path": "/utilities/free-vpn",
        "sort_order": 10,
    },
    {
        "key": "qr_generator",
        "title": "QR Generator",
        "description": "Tạo mã QR miễn phí cho URL hoặc nội dung ngắn.",
        "icon": "qr",
        "route_path": "/utilities/qr",
        "sort_order": 20,
    },
    {
        "key": "shortlink_generator",
        "title": "Shortlink Generator",
        "description": "Tạo link rút gọn miễn phí với kiểm tra URL an toàn.",
        "icon": "link",
        "route_path": "/utilities/shortlink",
        "sort_order": 30,
    },
    {
        "key": "ping_website",
        "title": "Ping Website",
        "description": "Kiểm tra trạng thái HTTP và thời gian phản hồi website public.",
        "icon": "activity",
        "route_path": "/utilities/ping",
        "sort_order": 40,
    },
    {
        "key": "idea_webapp_app",
        "title": "Ý tưởng webapp/app",
        "description": "Gửi ý tưởng website, webapp hoặc app để liên hệ admin.",
        "icon": "spark",
        "route_path": "/build-idea",
        "sort_order": 50,
    },
    {
        "key": "advertising_contact",
        "title": "Liên hệ quảng cáo",
        "description": "Liên hệ đặt quảng cáo hoặc hợp tác nội dung.",
        "icon": "megaphone",
        "route_path": "/advertising",
        "sort_order": 60,
    },
)

ALLOWED_POST_TYPES = {item.value for item in ContentPostType}
ALLOWED_POST_STATUSES = {item.value for item in ContentPostStatus}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass(frozen=True)
class PingResult:
    ok: bool
    url: str
    status_code: int | None
    response_time_ms: int | None
    error: str


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or secrets.token_urlsafe(6).lower()


def unique_slug(db: Session, title: str, existing_id: int | None = None) -> str:
    base = slugify(title)
    candidate = base
    counter = 2
    while True:
        query = db.query(ContentPost).filter(ContentPost.slug == candidate)
        if existing_id is not None:
            query = query.filter(ContentPost.id != existing_id)
        if not query.first():
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item).strip() for item in data if str(item).strip()] if isinstance(data, list) else []


def dump_json_list(values: list[str] | tuple[str, ...] | str | None) -> str:
    if values is None:
        return "[]"
    if isinstance(values, str):
        items = [item.strip() for item in values.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in values if str(item).strip()]
    return json.dumps(items, ensure_ascii=False)


def validate_public_url(url: str, require_http: bool = True) -> str:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if require_http and parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError("URL host is required")
    if parsed.scheme in {"javascript", "data", "file"}:
        raise ValueError("URL scheme is not allowed")
    return cleaned


def ensure_not_private_target(url: str) -> str:
    cleaned = validate_public_url(url)
    hostname = urlparse(cleaned).hostname
    if not hostname:
        raise ValueError("URL host is required")
    lowered = hostname.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"} or lowered.endswith(".local"):
        raise ValueError("Local or private hosts are not allowed")
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError("Cannot resolve host") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError("Private or internal IP targets are not allowed")
    return cleaned


def ping_public_url(url: str) -> PingResult:
    started = time.perf_counter()
    try:
        cleaned = ensure_not_private_target(url)
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            response = client.head(cleaned)
            if response.status_code in {405, 403}:
                response = client.get(cleaned)
        elapsed = int((time.perf_counter() - started) * 1000)
        return PingResult(True, cleaned, response.status_code, elapsed, "")
    except Exception as exc:  # noqa: BLE001 - user-facing utility should return a result
        elapsed = int((time.perf_counter() - started) * 1000)
        return PingResult(False, url.strip(), None, elapsed, str(exc))


def ensure_default_utilities(db: Session) -> None:
    for data in DEFAULT_UTILITIES:
        existing = db.query(UtilityItem).filter(UtilityItem.key == data["key"]).first()
        if existing:
            continue
        db.add(UtilityItem(is_active=True, is_member_only=False, is_free=True, **data))
    db.commit()


def record_utility_usage(db: Session, user: User | None, utility_key: str) -> None:
    if not user:
        return
    usage = (
        db.query(MemberUtilityUsage)
        .filter(MemberUtilityUsage.user_id == user.id, MemberUtilityUsage.utility_key == utility_key)
        .first()
    )
    if not usage:
        usage = MemberUtilityUsage(user_id=user.id, utility_key=utility_key, usage_count=0)
        db.add(usage)
    usage.usage_count += 1
    usage.last_used_at = datetime.now(timezone.utc)
    db.commit()


def create_shortlink(db: Session, target_url: str, user: User | None = None) -> ShortLink:
    cleaned = ensure_not_private_target(target_url)
    while True:
        code = secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:7]
        if not db.query(ShortLink).filter(ShortLink.code == code).first():
            break
    item = ShortLink(code=code, target_url=cleaned, user_id=user.id if user else None)
    db.add(item)
    db.commit()
    db.refresh(item)
    record_utility_usage(db, user, "shortlink_generator")
    return item


def hash_agent_key(raw_key: str) -> str:
    settings = get_settings()
    digest = hmac.new(settings.secret_key.encode("utf-8"), raw_key.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def create_agent_key(
    db: Session,
    name: str,
    allowed_post_types: list[str] | None = None,
    can_auto_publish: bool = False,
) -> tuple[AiAgentApiKey, str]:
    raw_key = f"gla_{secrets.token_urlsafe(32)}"
    item = AiAgentApiKey(
        name=name.strip() or "AI Agent",
        key_hash=hash_agent_key(raw_key),
        prefix=raw_key[:10],
        allowed_post_types=dump_json_list(allowed_post_types or ["job", "shop"]),
        can_auto_publish=can_auto_publish,
        is_active=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, raw_key


def verify_agent_key(db: Session, raw_key: str | None) -> AiAgentApiKey | None:
    if not raw_key:
        return None
    item = db.query(AiAgentApiKey).filter(AiAgentApiKey.key_hash == hash_agent_key(raw_key.strip())).first()
    if not item or not item.is_active:
        return None
    item.last_used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def log_agent_request(
    db: Session,
    *,
    agent_key: AiAgentApiKey | None,
    endpoint: str,
    post_type: str,
    request_ip: str,
    status_code: int,
    error_message: str = "",
    created_post_id: int | None = None,
) -> None:
    db.add(
        AiAgentPostLog(
            agent_key_id=agent_key.id if agent_key else None,
            endpoint=endpoint,
            post_type=post_type,
            request_ip=request_ip,
            status_code=status_code,
            error_message=error_message,
            created_post_id=created_post_id,
        )
    )
    db.commit()


def create_content_post(
    db: Session,
    *,
    post_type: str,
    title: str,
    summary: str = "",
    content: str = "",
    image_url: str = "",
    target_url: str = "",
    platform: str = "other",
    locale: str = "vi",
    status: str = "draft",
    source: str = "admin",
    created_by: User | None = None,
    ai_agent_name: str = "",
    tags: list[str] | str | None = None,
    sort_order: int = 0,
) -> ContentPost:
    if post_type not in ALLOWED_POST_TYPES:
        raise ValueError("Invalid post type")
    if status not in ALLOWED_POST_STATUSES:
        raise ValueError("Invalid post status")
    if image_url:
        validate_public_url(image_url)
    if target_url:
        validate_public_url(target_url)
    published_at = datetime.now(timezone.utc) if status == ContentPostStatus.PUBLISHED.value else None
    post = ContentPost(
        post_type=ContentPostType(post_type),
        title=title.strip(),
        slug=unique_slug(db, title),
        summary=summary.strip(),
        content=content.strip(),
        image_url=image_url.strip(),
        target_url=target_url.strip(),
        platform=platform.strip() or "other",
        locale=locale if locale in {"vi", "zh-TW"} else "vi",
        status=ContentPostStatus(status),
        source=ContentPostSource(source),
        created_by_user_id=created_by.id if created_by else None,
        ai_agent_name=ai_agent_name.strip(),
        tags=dump_json_list(tags),
        sort_order=sort_order,
        published_at=published_at,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def update_post_status_timestamp(post: ContentPost, old_status: str | None = None) -> None:
    if post.status == ContentPostStatus.PUBLISHED and not post.published_at:
        post.published_at = datetime.now(timezone.utc)
    if old_status == ContentPostStatus.PUBLISHED.value and post.status != ContentPostStatus.PUBLISHED:
        post.published_at = None
