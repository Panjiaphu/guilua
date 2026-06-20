from __future__ import annotations

import ipaddress
import json
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import IpReputationCache, SecurityEvent, SecurityIncident, SecurityPlaybook, SecurityRule, User
from app.services.email import queue_email


SUSPICIOUS_PATTERNS = (
    (re.compile(r"(\bunion\b.+\bselect\b|information_schema|sleep\(|benchmark\()", re.I), "injection_probe", 35),
    (re.compile(r"(<script|javascript:|onerror=|onload=|document\.cookie)", re.I), "xss_probe", 30),
    (re.compile(r"(\.\./|\.\.\\|/etc/passwd|boot\.ini|win\.ini)", re.I), "path_traversal_probe", 30),
)
SUSPICIOUS_USER_AGENTS = ("sqlmap", "nikto", "nmap", "masscan", "acunetix", "nessus", "wpscan")
RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


@dataclass(frozen=True)
class SecurityDecision:
    allowed: bool
    event_type: str
    severity: str
    risk_score: int
    reason: str
    rule: SecurityRule | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def client_ip(request: Request) -> str:
    settings = get_settings()
    if settings.security_trusted_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip", "")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else ""


def ip_version(ip_address: str) -> str:
    try:
        return f"ipv{ipaddress.ip_address(ip_address).version}"
    except ValueError:
        return "unknown"


def _match_cidr(ip_address: str, cidr: str) -> bool:
    try:
        return ipaddress.ip_address(ip_address) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _matches_rule(rule: SecurityRule, ip_address: str, path: str, user_agent: str, country_code: str = "") -> bool:
    value = rule.value.strip()
    if not value:
        return False
    if rule.rule_type in {"ip_allow", "ip_block"}:
        return ip_address == value
    if rule.rule_type in {"cidr_allow", "cidr_block"}:
        return _match_cidr(ip_address, value)
    if rule.rule_type == "user_agent_block":
        return value.lower() in user_agent.lower()
    if rule.rule_type in {"country_allow", "country_block"}:
        return country_code.upper() == value.upper()
    if rule.rule_type in {"path_protect", "route_rate_limit"}:
        return path.startswith(value)
    return False


def _detect_payload(path: str, query: str, user_agent: str) -> tuple[str, int, str]:
    inspected = f"{path}?{query}"
    for pattern, incident_type, score in SUSPICIOUS_PATTERNS:
        if pattern.search(inspected):
            return incident_type, score, "Suspicious request payload"
    lowered_ua = user_agent.lower()
    if any(token in lowered_ua for token in SUSPICIOUS_USER_AGENTS):
        return "suspicious_user_agent", 25, "Suspicious user-agent"
    return "", 0, ""


def _route_limit(path: str) -> int:
    settings = get_settings()
    if path.startswith("/login"):
        return settings.security_login_rate_limit_max_attempts
    if path.startswith("/admin"):
        return settings.security_admin_rate_limit_max_requests
    if path.startswith("/api/agent"):
        return settings.security_agent_api_rate_limit_max_requests
    return settings.security_rate_limit_max_requests


def _rate_limited(ip_address: str, path: str) -> bool:
    settings = get_settings()
    if not settings.security_rate_limit_enabled or not ip_address:
        return False
    window = settings.security_rate_limit_window_seconds
    if path.startswith("/login"):
        window = settings.security_login_rate_limit_window_seconds
    now = time.time()
    bucket_key = f"{ip_address}:{path.split('/', 3)[:3]}"
    bucket = RATE_BUCKETS[bucket_key]
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    bucket.append(now)
    return len(bucket) > _route_limit(path)


def evaluate_request(db: Session, request: Request) -> SecurityDecision:
    settings = get_settings()
    ip_address = client_ip(request)
    path = request.url.path
    user_agent = request.headers.get("user-agent", "")
    geo = get_ip_reputation(db, ip_address)
    request.state.security_geo = geo

    if ip_address in settings.security_ip_allowlist:
        return SecurityDecision(True, "request_allowed", "info", 0, "Environment allowlist")
    if ip_address in settings.security_ip_blocklist:
        return SecurityDecision(False, "request_blocked", "high", 80, "Environment blocklist")
    country_code = str(geo.get("country_code") or "").upper()
    if country_code and settings.security_country_allowlist:
        if country_code not in {item.upper() for item in settings.security_country_allowlist}:
            return SecurityDecision(False, "request_blocked", "high", 72, "Environment country allowlist")
    if country_code and country_code in {item.upper() for item in settings.security_country_blocklist}:
        return SecurityDecision(False, "request_blocked", "high", 72, "Environment country blocklist")
    if settings.security_admin_ip_restriction_enabled and path.startswith("/admin"):
        if ip_address not in settings.security_admin_ip_allowlist:
            return SecurityDecision(False, "request_blocked", "high", 75, "Admin IP restriction")

    active_rules = (
        db.query(SecurityRule)
        .filter(SecurityRule.is_active.is_(True))
        .order_by(SecurityRule.action.asc(), SecurityRule.created_at.desc())
        .all()
    )
    now = utcnow()
    for rule in active_rules:
        if rule.expires_at and rule.expires_at < now:
            continue
        if not _matches_rule(rule, ip_address, path, user_agent, country_code):
            continue
        if rule.action == "allow":
            return SecurityDecision(True, "request_allowed", rule.severity, 0, rule.name, rule)
        if rule.action == "block":
            return SecurityDecision(False, "request_blocked", rule.severity, 85, rule.name, rule)

    if _rate_limited(ip_address, path):
        return SecurityDecision(False, "rate_limited", "medium", 45, "Application rate limit")

    incident_type, risk_score, reason = _detect_payload(path, request.url.query, user_agent)
    if incident_type:
        return SecurityDecision(
            not settings.security_block_suspicious_payloads,
            "suspicious_payload" if incident_type != "suspicious_user_agent" else "suspicious_user_agent",
            "medium",
            risk_score,
            reason,
        )

    if path.startswith("/admin"):
        return SecurityDecision(True, "admin_access", "info", 5, "Admin route access")
    return SecurityDecision(True, "request_allowed", "info", 0, "Allowed")


def get_ip_reputation(db: Session, ip_address: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.security_geoip_enabled or not ip_address or settings.security_geoip_provider == "none":
        return {}
    now = utcnow()
    cached = db.query(IpReputationCache).filter(IpReputationCache.ip_address == ip_address).first()
    if cached and cached.expires_at > now:
        return {
            "country_code": cached.country_code,
            "country_name": cached.country_name,
            "region": cached.region,
            "city": cached.city,
            "asn": cached.asn,
            "isp": cached.isp,
            "risk_score": cached.risk_score,
        }
    if not settings.security_geoip_api_url:
        return {}
    raw = _fetch_geoip(ip_address)
    if not raw:
        return {}
    normalized = _normalize_geoip_payload(raw)
    expires_at = now + timedelta(hours=max(settings.security_geoip_cache_hours, 1))
    if not cached:
        cached = IpReputationCache(ip_address=ip_address, expires_at=expires_at)
        db.add(cached)
    cached.ip_version = ip_version(ip_address)
    cached.country_code = normalized["country_code"]
    cached.country_name = normalized["country_name"]
    cached.region = normalized["region"]
    cached.city = normalized["city"]
    cached.asn = normalized["asn"]
    cached.isp = normalized["isp"]
    cached.organization = normalized["organization"]
    cached.is_proxy = normalized["is_proxy"]
    cached.is_vpn = normalized["is_vpn"]
    cached.is_tor = normalized["is_tor"]
    cached.is_hosting = normalized["is_hosting"]
    cached.risk_score = normalized["risk_score"]
    cached.provider = settings.security_geoip_provider
    cached.raw_json = json.dumps(raw, ensure_ascii=False)
    cached.checked_at = now
    cached.expires_at = expires_at
    db.commit()
    return normalized


def _fetch_geoip(ip_address: str) -> dict[str, Any]:
    settings = get_settings()
    api_url = settings.security_geoip_api_url or ""
    api_key = settings.security_geoip_api_key or ""
    url = api_url.replace("{ip}", ip_address).replace("{key}", api_key)
    if "{ip}" not in api_url and not api_url.rstrip("/").endswith(ip_address):
        url = f"{api_url.rstrip('/')}/{ip_address}"
    headers = {"Accept": "application/json"}
    if api_key and "{key}" not in api_url:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=2.5) as client:
            response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_geoip_payload(data: dict[str, Any]) -> dict[str, Any]:
    country_code = data.get("country_code") or data.get("countryCode") or data.get("country") or ""
    country_name = data.get("country_name") or data.get("countryName") or data.get("country") or ""
    asn_value = data.get("asn") or data.get("as") or ""
    threat = data.get("threat") if isinstance(data.get("threat"), dict) else {}
    security = data.get("security") if isinstance(data.get("security"), dict) else {}
    is_proxy = bool(data.get("proxy") or threat.get("is_proxy") or security.get("is_proxy"))
    is_vpn = bool(data.get("vpn") or threat.get("is_vpn") or security.get("is_vpn"))
    is_tor = bool(data.get("tor") or threat.get("is_tor") or security.get("is_tor"))
    is_hosting = bool(data.get("hosting") or threat.get("is_datacenter") or security.get("is_datacenter"))
    risk_score = 0
    if is_proxy:
        risk_score += 15
    if is_vpn:
        risk_score += 15
    if is_tor:
        risk_score += 35
    if is_hosting:
        risk_score += 10
    return {
        "country_code": str(country_code).upper()[:8],
        "country_name": str(country_name)[:120],
        "region": str(data.get("region") or data.get("regionName") or "")[:120],
        "city": str(data.get("city") or "")[:120],
        "asn": str(asn_value)[:80],
        "isp": str(data.get("isp") or data.get("org") or data.get("organization") or "")[:160],
        "organization": str(data.get("organization") or data.get("org") or "")[:160],
        "is_proxy": is_proxy,
        "is_vpn": is_vpn,
        "is_tor": is_tor,
        "is_hosting": is_hosting,
        "risk_score": risk_score,
    }


def log_security_event(
    db: Session,
    *,
    request: Request | None = None,
    event_type: str,
    severity: str = "info",
    risk_score: int = 0,
    status_code: int | None = None,
    rule: SecurityRule | None = None,
    username_or_email: str = "",
    user: User | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    if not settings.security_logging_enabled:
        return
    ip_address = client_ip(request) if request else ""
    path = request.url.path if request else ""
    method = request.method if request else ""
    user_agent = request.headers.get("user-agent", "") if request else ""
    referer = request.headers.get("referer", "") if request else ""
    geo = getattr(request.state, "security_geo", {}) if request else {}
    request_id = request.headers.get("x-request-id", "") if request else ""
    request_id = request_id or secrets.token_urlsafe(10)
    event = SecurityEvent(
        event_type=event_type,
        severity=severity,
        risk_score=risk_score,
        ip_address=ip_address,
        ip_version=ip_version(ip_address),
        country_code=str(geo.get("country_code") or ""),
        country_name=str(geo.get("country_name") or ""),
        region=str(geo.get("region") or ""),
        city=str(geo.get("city") or ""),
        asn=str(geo.get("asn") or ""),
        isp=str(geo.get("isp") or ""),
        path=path,
        method=method,
        status_code=status_code,
        user_agent=user_agent[:2000],
        referer=referer[:2000],
        user_id=user.id if user else None,
        username_or_email=username_or_email.strip().lower()[:255],
        rule_id=rule.id if rule else None,
        request_id=request_id,
        details_json=json.dumps(details or {}, ensure_ascii=False),
    )
    db.add(event)
    _upsert_incident(db, event)
    db.commit()
    if settings.security_notify_on_high_risk and risk_score >= settings.security_auto_block_threshold:
        _queue_security_alert(db, event)


def _upsert_incident(db: Session, event: SecurityEvent) -> None:
    incident_type = _incident_type_for_event(event)
    if not incident_type:
        return
    window_start = utcnow() - timedelta(hours=6)
    incident = (
        db.query(SecurityIncident)
        .filter(
            SecurityIncident.incident_type == incident_type,
            SecurityIncident.affected_ip == event.ip_address,
            SecurityIncident.status.in_(["open", "investigating"]),
            SecurityIncident.created_at >= window_start,
        )
        .first()
    )
    if not incident:
        incident = SecurityIncident(
            title=f"{incident_type.replace('_', ' ').title()} - {event.ip_address or 'unknown IP'}",
            incident_type=incident_type,
            status="open",
            severity=event.severity,
            summary=event.details_json,
            affected_ip=event.ip_address,
            affected_user_id=event.user_id,
            event_count=0,
            first_seen_at=event.created_at,
        )
        db.add(incident)
    incident.event_count += 1
    incident.last_seen_at = event.created_at
    incident.severity = event.severity if event.risk_score >= 50 else incident.severity


def _incident_type_for_event(event: SecurityEvent) -> str:
    if event.event_type == "login_failed":
        return "brute_force"
    if event.event_type == "ai_agent_auth_failed":
        return "ai_agent_abuse"
    if event.event_type == "rate_limited":
        return "dos_signal"
    details = event.details_json.lower()
    if "injection_probe" in details:
        return "injection_probe"
    if "xss_probe" in details:
        return "xss_probe"
    if "path_traversal_probe" in details:
        return "path_traversal_probe"
    if event.event_type == "shortlink_redirect":
        return "shortlink_abuse" if event.risk_score >= 30 else ""
    return ""


def _queue_security_alert(db: Session, event: SecurityEvent) -> None:
    settings = get_settings()
    recipient = settings.security_alert_email or settings.admin_notification_email
    if not recipient:
        return
    queue_email(
        db,
        recipient,
        f"Guilua security alert: {event.event_type}",
        (
            f"Security event: {event.event_type}\n"
            f"Severity: {event.severity}\nRisk score: {event.risk_score}\n"
            f"IP: {event.ip_address}\nPath: {event.path}\nDetails: {event.details_json}"
        ),
        "security_alert",
    )


def dashboard_summary(db: Session) -> dict[str, Any]:
    since = utcnow() - timedelta(hours=24)
    events_24h = db.query(func.count(SecurityEvent.id)).filter(SecurityEvent.created_at >= since).scalar() or 0
    blocked_24h = (
        db.query(func.count(SecurityEvent.id))
        .filter(SecurityEvent.created_at >= since, SecurityEvent.event_type.in_(["request_blocked", "rate_limited"]))
        .scalar()
        or 0
    )
    high_risk_24h = (
        db.query(func.count(SecurityEvent.id))
        .filter(SecurityEvent.created_at >= since, SecurityEvent.risk_score >= 50)
        .scalar()
        or 0
    )
    open_incidents = (
        db.query(func.count(SecurityIncident.id))
        .filter(SecurityIncident.status.in_(["open", "investigating"]))
        .scalar()
        or 0
    )
    top_ips = (
        db.query(SecurityEvent.ip_address, func.count(SecurityEvent.id).label("count"))
        .filter(SecurityEvent.created_at >= since, SecurityEvent.ip_address != "")
        .group_by(SecurityEvent.ip_address)
        .order_by(func.count(SecurityEvent.id).desc())
        .limit(8)
        .all()
    )
    return {
        "events_24h": events_24h,
        "blocked_24h": blocked_24h,
        "high_risk_24h": high_risk_24h,
        "open_incidents": open_incidents,
        "top_ips": top_ips,
    }


def ensure_default_playbooks(db: Session) -> None:
    defaults = [
        {
            "incident_type": "brute_force",
            "title": "Login brute force",
            "description": "Repeated failed login attempts against member or admin accounts.",
            "immediate_steps": "Confirm affected IPs and accounts, temporarily block abusive IP ranges, verify admin account activity.",
            "containment_steps": "Keep rate limit enabled, rotate exposed passwords, force password reset for affected users if needed.",
            "eradication_steps": "Review logs for credential stuffing pattern and remove stale credentials.",
            "recovery_steps": "Confirm normal login traffic and monitor alerts for 24 hours.",
            "prevention_steps": "Use strong passwords, email verification, IP rules for admin, and external WAF when traffic grows.",
            "checklist_json": json.dumps(["Block abusive IP", "Review admin logins", "Notify affected member"], ensure_ascii=False),
        },
        {
            "incident_type": "injection_probe",
            "title": "Injection probe",
            "description": "Requests contain common SQL injection or command probing signatures.",
            "immediate_steps": "Inspect payload path/query and confirm whether any endpoint returned 5xx.",
            "containment_steps": "Enable suspicious payload blocking if probes continue and add route-specific rules.",
            "eradication_steps": "Patch vulnerable validation paths and confirm ORM parameterization.",
            "recovery_steps": "Review affected records and rotate secrets if compromise is suspected.",
            "prevention_steps": "Keep validation strict, avoid raw SQL, and place Render behind a WAF for larger traffic.",
            "checklist_json": json.dumps(["Check 5xx errors", "Review affected route", "Add block rule"], ensure_ascii=False),
        },
        {
            "incident_type": "dos_signal",
            "title": "Application DoS signal",
            "description": "A client or route exceeded application rate limits.",
            "immediate_steps": "Identify top IPs/routes, block abusive clients, and check Render metrics.",
            "containment_steps": "Lower route limit temporarily, enable CDN/WAF filtering for public pages.",
            "eradication_steps": "Remove expensive unauthenticated operations or cache public responses.",
            "recovery_steps": "Restore normal limits after traffic stabilizes.",
            "prevention_steps": "Use infrastructure WAF/CDN for volumetric attacks; app firewall is only one layer.",
            "checklist_json": json.dumps(["Check top IPs", "Review Render metrics", "Enable WAF/CDN"], ensure_ascii=False),
        },
    ]
    for item in defaults:
        existing = db.query(SecurityPlaybook).filter(SecurityPlaybook.incident_type == item["incident_type"]).first()
        if existing:
            continue
        db.add(SecurityPlaybook(is_active=True, **item))
    db.commit()


class SecurityFirewallMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not settings.security_firewall_enabled or request.url.path.startswith("/static"):
            return await call_next(request)
        with SessionLocal() as db:
            try:
                decision = evaluate_request(db, request)
                should_log = (
                    decision.event_type != "request_allowed"
                    or request.url.path.startswith("/admin")
                    or settings.security_log_suspicious_payloads
                )
                if not decision.allowed:
                    log_security_event(
                        db,
                        request=request,
                        event_type=decision.event_type,
                        severity=decision.severity,
                        risk_score=decision.risk_score,
                        status_code=403 if decision.event_type == "request_blocked" else 429,
                        rule=decision.rule,
                        details={"reason": decision.reason},
                    )
                    status_code = 429 if decision.event_type == "rate_limited" else 403
                    return PlainTextResponse("Request blocked by Guilua security policy.", status_code=status_code)
                if should_log and decision.event_type != "request_allowed":
                    log_security_event(
                        db,
                        request=request,
                        event_type=decision.event_type,
                        severity=decision.severity,
                        risk_score=decision.risk_score,
                        details={"reason": decision.reason},
                    )
                elif request.url.path.startswith("/admin"):
                    log_security_event(db, request=request, event_type="admin_access", severity="info", risk_score=5)
            except Exception:
                db.rollback()
        return await call_next(request)
