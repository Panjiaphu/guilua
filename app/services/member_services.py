from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ServiceRequest, TransactionStatus, User
from app.services.email import queue_email


ALLOWED_IP_REGIONS = {"taiwan", "japan", "singapore", "united_states", "vietnam"}
ALLOWED_IP_PROTOCOLS = {"recommended", "vpn", "proxy", "residential"}


def make_service_reference() -> str:
    return f"GS{uuid4().hex[:12].upper()}"


def create_ip_service_request(
    db: Session,
    user: User,
    target_region: str,
    protocol: str,
    duration_hours: int,
    device_label: str = "",
    current_ip: str = "",
    member_note: str = "",
) -> ServiceRequest:
    region = target_region if target_region in ALLOWED_IP_REGIONS else "taiwan"
    selected_protocol = protocol if protocol in ALLOWED_IP_PROTOCOLS else "recommended"
    hours = min(max(duration_hours, 1), 720)

    item = ServiceRequest(
        reference_code=make_service_reference(),
        user_id=user.id,
        service_type="ip_switch",
        status=TransactionStatus.PENDING.value,
        target_region=region,
        protocol=selected_protocol,
        duration_hours=hours,
        device_label=device_label.strip(),
        current_ip=current_ip.strip(),
        member_note=member_note.strip(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    queue_email(
        db,
        user.email,
        f"Guilua - đã nhận yêu cầu dịch vụ {item.reference_code}",
        f"Yêu cầu dịch vụ chuyển IP {item.reference_code} của bạn đang chờ quản trị viên kiểm tra.",
        "member_service_created",
        user=user,
    )
    admin_email = get_settings().admin_notification_email
    if admin_email:
        queue_email(
            db,
            admin_email,
            f"Guilua - yêu cầu dịch vụ mới {item.reference_code}",
            f"Thành viên {user.email} vừa tạo yêu cầu chuyển IP tới {item.target_region}.",
            "admin_service_created",
            user=user,
        )
    return item
