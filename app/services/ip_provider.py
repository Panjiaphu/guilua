from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.models import ServiceRequest


@dataclass(frozen=True)
class IpProvisionResult:
    configured: bool
    success: bool
    endpoint: str = ""
    error: str = ""


def provision_ip_service(item: ServiceRequest) -> IpProvisionResult:
    settings = get_settings()
    if not settings.ip_service_provider_url or not settings.ip_service_provider_api_key:
        return IpProvisionResult(configured=False, success=False, error="IP service provider is not configured")

    payload = {
        "reference_code": item.reference_code,
        "service_type": item.service_type,
        "target_region": item.target_region,
        "protocol": item.protocol,
        "duration_hours": item.duration_hours,
        "device_label": item.device_label,
        "current_ip": item.current_ip,
        "member_note": item.member_note,
        "member_email": item.user.email if item.user else "",
    }
    headers = {
        "Authorization": f"Bearer {settings.ip_service_provider_api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            settings.ip_service_provider_url,
            json=payload,
            headers=headers,
            timeout=settings.ip_service_provider_timeout_seconds,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception as exc:  # noqa: BLE001 - provider errors must be visible to admin
        return IpProvisionResult(configured=True, success=False, error=str(exc))

    endpoint = str(
        data.get("endpoint")
        or data.get("assigned_endpoint")
        or data.get("proxy_url")
        or data.get("vpn_profile_url")
        or ""
    ).strip()
    if not endpoint:
        return IpProvisionResult(configured=True, success=False, error="Provider response did not include an endpoint")
    return IpProvisionResult(configured=True, success=True, endpoint=endpoint)
