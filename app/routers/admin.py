from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import require_admin, verify_csrf
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import (
    AiAgentApiKey,
    AiAgentPostLog,
    ContentPost,
    ContentPostSource,
    ContentPostStatus,
    ContentPostType,
    EmailNotification,
    EmailReply,
    MemberUtilityUsage,
    SecurityEvent,
    SecurityIncident,
    SecurityPlaybook,
    SecurityRule,
    ServiceRequest,
    TransactionRequest,
    TransactionStatus,
    User,
    UtilityItem,
)
from app.services.commercial import (
    create_agent_key,
    create_content_post,
    dump_json_list,
    unique_slug,
    update_post_status_timestamp,
    validate_public_url,
)
from app.services.email import flush_email_queue, mark_reply_processed, queue_email
from app.services.ip_provider import provision_ip_service
from app.services.media import save_uploaded_image
from app.services.rates import latest_rates, update_manual_rate
from app.services.security_firewall import dashboard_summary


router = APIRouter(prefix="/admin")


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    requests = db.query(TransactionRequest).order_by(TransactionRequest.created_at.desc()).limit(50).all()
    service_requests = db.query(ServiceRequest).order_by(ServiceRequest.created_at.desc()).limit(50).all()
    emails = db.query(EmailNotification).order_by(EmailNotification.created_at.desc()).limit(20).all()
    replies = db.query(EmailReply).order_by(EmailReply.created_at.desc()).limit(20).all()
    member_count = db.query(User).filter(User.is_admin.is_(False)).count()
    content_counts = {
        "jobs": db.query(ContentPost).filter(ContentPost.post_type == ContentPostType.JOB).count(),
        "shop": db.query(ContentPost).filter(ContentPost.post_type == ContentPostType.SHOP).count(),
        "crypto_analysis": db.query(ContentPost).filter(ContentPost.post_type == ContentPostType.CRYPTO_ANALYSIS).count(),
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=context(
            request,
            admin=admin,
            requests=requests,
            service_requests=service_requests,
            rates=latest_rates(db),
            emails=emails,
            replies=replies,
            statuses=list(TransactionStatus),
            member_count=member_count,
            content_counts=content_counts,
            security_summary=dashboard_summary(db),
        ),
    )


@router.post("/requests/{request_id}")
def update_request(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    status: str = Form(...),
    admin_note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(TransactionRequest, request_id)
    if not item:
        return RedirectResponse("/admin?error=not_found", status_code=303)
    item.status = TransactionStatus(status)
    item.admin_note = admin_note.strip()
    db.commit()
    db.refresh(item)
    queue_email(
        db,
        item.user.email,
        f"Guilua - cập nhật yêu cầu {item.reference_code}",
        f"Trạng thái yêu cầu hiện tại: {item.status.value}. Ghi chú quản trị: {item.admin_note or '-'}",
        "member_transaction_status",
        user=item.user,
        transaction=item,
    )
    return RedirectResponse("/admin?updated=1", status_code=303)


@router.post("/rates")
def update_rate(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    pair: str = Form(...),
    buy_rate: str = Form(...),
    sell_rate: str = Form(...),
    note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    try:
        parsed_buy = Decimal(buy_rate)
        parsed_sell = Decimal(sell_rate)
    except InvalidOperation:
        return RedirectResponse("/admin?error=invalid_rate", status_code=303)
    if parsed_buy <= 0 or parsed_sell <= 0:
        return RedirectResponse("/admin?error=invalid_rate", status_code=303)
    update_manual_rate(db, pair=pair, buy_rate=parsed_buy, sell_rate=parsed_sell, note=note.strip())
    return RedirectResponse("/admin?rate_updated=1", status_code=303)


@router.post("/services/{service_id}")
def update_service_request(
    request: Request,
    service_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    status: str = Form(...),
    assigned_endpoint: str = Form(""),
    admin_note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(ServiceRequest, service_id)
    if not item:
        return RedirectResponse("/admin?error=service_not_found", status_code=303)
    if status not in {state.value for state in TransactionStatus}:
        return RedirectResponse("/admin?error=invalid_service_status", status_code=303)
    item.status = status
    item.assigned_endpoint = assigned_endpoint.strip()
    item.admin_note = admin_note.strip()
    if item.status in {TransactionStatus.APPROVED.value, TransactionStatus.COMPLETED.value} and not item.assigned_endpoint:
        provision = provision_ip_service(item)
        if provision.success:
            item.assigned_endpoint = provision.endpoint
        elif provision.configured:
            provider_note = "Không thể cấp endpoint tự động, vui lòng kiểm tra provider và cấp thủ công."
            item.admin_note = f"{item.admin_note}\n{provider_note}".strip()
    db.commit()
    db.refresh(item)
    queue_email(
        db,
        item.user.email,
        f"Guilua - cập nhật dịch vụ {item.reference_code}",
        (
            f"Trạng thái dịch vụ chuyển IP hiện tại: {item.status}. "
            f"Endpoint: {item.assigned_endpoint or '-'}. "
            f"Ghi chú quản trị: {item.admin_note or '-'}"
        ),
        "member_service_status",
        user=item.user,
    )
    return RedirectResponse("/admin?service_updated=1", status_code=303)


@router.post("/email/flush")
def flush_emails(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    sent = flush_email_queue(db)
    return RedirectResponse(f"/admin?email_flush={len(sent)}", status_code=303)


@router.post("/email-replies/{reply_id}/processed")
def process_email_reply(
    request: Request,
    reply_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    mark_reply_processed(db, reply_id)
    return RedirectResponse("/admin?reply_processed=1", status_code=303)


@router.get("/ai-agents")
def ai_agents(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    keys = db.query(AiAgentApiKey).order_by(AiAgentApiKey.created_at.desc()).all()
    logs = db.query(AiAgentPostLog).order_by(AiAgentPostLog.created_at.desc()).limit(80).all()
    raw_key = request.query_params.get("raw_key", "")
    return templates.TemplateResponse(
        request=request,
        name="admin/ai_agents.html",
        context=context(request, admin=admin, keys=keys, logs=logs, raw_key=raw_key),
    )


@router.post("/ai-agents")
def create_ai_agent_key(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    name: str = Form(...),
    allowed_post_types: str = Form("job,shop,crypto_analysis"),
    can_auto_publish: bool = Form(False),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    _, raw_key = create_agent_key(
        db,
        name=name,
        allowed_post_types=[item.strip() for item in allowed_post_types.split(",") if item.strip()],
        can_auto_publish=can_auto_publish,
    )
    return RedirectResponse(f"/admin/ai-agents?raw_key={raw_key}", status_code=303)


@router.post("/ai-agents/{key_id}/toggle")
def toggle_ai_agent_key(
    request: Request,
    key_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(AiAgentApiKey, key_id)
    if not item:
        return RedirectResponse("/admin/ai-agents?error=not_found", status_code=303)
    item.is_active = not item.is_active
    db.commit()
    return RedirectResponse("/admin/ai-agents?updated=1", status_code=303)


def _post_type_from_section(section: str) -> ContentPostType:
    if section == "jobs":
        return ContentPostType.JOB
    if section == "shop":
        return ContentPostType.SHOP
    if section == "crypto-analysis":
        return ContentPostType.CRYPTO_ANALYSIS
    raise HTTPException(status_code=404, detail="Unknown post section")


def _post_image_url_from_form(
    *,
    image_url: str,
    image_file: UploadFile | None,
    title: str,
    section: str,
) -> str:
    if not image_file or not image_file.filename:
        return image_url.strip()
    image_file.file.seek(0)
    saved = save_uploaded_image(
        content=image_file.file.read(),
        original_filename=image_file.filename,
        folder=f"posts/{section}",
        name_hint=title,
    )
    return saved.url


@router.get("/posts/{section}")
def admin_posts(section: str, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    post_type = _post_type_from_section(section)
    posts = (
        db.query(ContentPost)
        .filter(ContentPost.post_type == post_type)
        .order_by(ContentPost.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/posts.html",
        context=context(
            request,
            admin=admin,
            section=section,
            post_type=post_type.value,
            posts=posts,
            statuses=list(ContentPostStatus),
        ),
    )


@router.get("/posts/{section}/new")
def new_admin_post(section: str, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    post_type = _post_type_from_section(section)
    return templates.TemplateResponse(
        request=request,
        name="admin/post_form.html",
        context=context(request, admin=admin, section=section, post_type=post_type.value, post=None),
    )


@router.get("/posts/{section}/{post_id}/edit")
def edit_admin_post(section: str, post_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    post_type = _post_type_from_section(section)
    post = db.get(ContentPost, post_id)
    if not post or post.post_type != post_type:
        raise HTTPException(status_code=404, detail="Post not found")
    return templates.TemplateResponse(
        request=request,
        name="admin/post_form.html",
        context=context(request, admin=admin, section=section, post_type=post_type.value, post=post),
    )


@router.post("/posts/{section}")
def create_admin_post(
    section: str,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    summary: str = Form(""),
    content: str = Form(""),
    image_url: str = Form(""),
    image_file: UploadFile | None = File(None),
    target_url: str = Form(""),
    platform: str = Form("other"),
    locale: str = Form("vi"),
    status: str = Form("draft"),
    tags: str = Form(""),
    sort_order: int = Form(0),
    market_session: str = Form(""),
    market_bias: str = Form(""),
    risk_level: str = Form(""),
    tradingview_symbol: str = Form(""),
    tradingview_url: str = Form(""),
    analysis_category: str = Form(""),
):
    verify_csrf(request, csrf_token)
    admin = require_admin(request, db)
    post_type = _post_type_from_section(section)
    try:
        final_image_url = _post_image_url_from_form(
            image_url=image_url,
            image_file=image_file,
            title=title,
            section=section,
        )
        create_content_post(
            db,
            post_type=post_type.value,
            title=title,
            summary=summary,
            content=content,
            image_url=final_image_url,
            target_url=target_url,
            platform=platform,
            locale=locale,
            status=status,
            source=ContentPostSource.ADMIN.value,
            created_by=admin,
            tags=tags,
            sort_order=sort_order,
            market_session=market_session,
            market_bias=market_bias,
            risk_level=risk_level,
            tradingview_symbol=tradingview_symbol,
            tradingview_url=tradingview_url,
            analysis_category=analysis_category,
        )
    except ValueError:
        return RedirectResponse(f"/admin/posts/{section}/new?error=invalid_input", status_code=303)
    return RedirectResponse(f"/admin/posts/{section}?created=1", status_code=303)


@router.post("/posts/{section}/{post_id}")
def update_admin_post(
    section: str,
    post_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    summary: str = Form(""),
    content: str = Form(""),
    image_url: str = Form(""),
    image_file: UploadFile | None = File(None),
    target_url: str = Form(""),
    platform: str = Form("other"),
    locale: str = Form("vi"),
    status: str = Form("draft"),
    tags: str = Form(""),
    sort_order: int = Form(0),
    market_session: str = Form(""),
    market_bias: str = Form(""),
    risk_level: str = Form(""),
    tradingview_symbol: str = Form(""),
    tradingview_url: str = Form(""),
    analysis_category: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    post_type = _post_type_from_section(section)
    post = db.get(ContentPost, post_id)
    if not post or post.post_type != post_type:
        return RedirectResponse(f"/admin/posts/{section}?error=not_found", status_code=303)
    try:
        final_image_url = _post_image_url_from_form(
            image_url=image_url,
            image_file=image_file,
            title=title,
            section=section,
        )
        if final_image_url:
            validate_public_url(final_image_url)
        if target_url:
            validate_public_url(target_url)
        if tradingview_url:
            validate_public_url(tradingview_url)
    except ValueError:
        return RedirectResponse(f"/admin/posts/{section}/{post_id}/edit?error=invalid_input", status_code=303)
    old_status = post.status.value
    post.title = title.strip()
    post.slug = unique_slug(db, title, existing_id=post.id)
    post.summary = summary.strip()
    post.content = content.strip()
    post.image_url = final_image_url
    post.target_url = target_url.strip()
    post.platform = platform.strip() or "other"
    post.market_session = market_session.strip()
    post.market_bias = market_bias.strip()
    post.risk_level = risk_level.strip()
    post.tradingview_symbol = tradingview_symbol.strip().upper()
    post.tradingview_url = tradingview_url.strip()
    post.analysis_category = analysis_category.strip()
    post.locale = locale if locale in {"vi", "zh-TW"} else "vi"
    post.status = ContentPostStatus(status)
    post.tags = dump_json_list(tags)
    post.sort_order = sort_order
    update_post_status_timestamp(post, old_status)
    db.commit()
    return RedirectResponse(f"/admin/posts/{section}?updated=1", status_code=303)


@router.post("/posts/{section}/{post_id}/archive")
def archive_admin_post(
    section: str,
    post_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    post = db.get(ContentPost, post_id)
    if post:
        post.status = ContentPostStatus.ARCHIVED
        update_post_status_timestamp(post, ContentPostStatus.PUBLISHED.value)
        db.commit()
    return RedirectResponse(f"/admin/posts/{section}?archived=1", status_code=303)


@router.get("/utilities")
def admin_utilities(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    items = db.query(UtilityItem).order_by(UtilityItem.sort_order.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/utilities.html",
        context=context(request, admin=admin, utilities=items),
    )


@router.post("/utilities/{utility_id}")
def update_admin_utility(
    utility_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    route_path: str = Form(""),
    is_active: bool = Form(False),
    is_member_only: bool = Form(False),
    is_free: bool = Form(False),
    sort_order: int = Form(0),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(UtilityItem, utility_id)
    if not item:
        return RedirectResponse("/admin/utilities?error=not_found", status_code=303)
    item.title = title.strip()
    item.description = description.strip()
    item.route_path = route_path.strip()
    item.is_active = is_active
    item.is_member_only = is_member_only
    item.is_free = is_free
    item.sort_order = sort_order
    db.commit()
    return RedirectResponse("/admin/utilities?updated=1", status_code=303)


@router.get("/members")
def admin_members(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    members = db.query(User).order_by(User.created_at.desc()).limit(200).all()
    usage = db.query(MemberUtilityUsage).order_by(MemberUtilityUsage.updated_at.desc()).limit(300).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/members.html",
        context=context(request, admin=admin, members=members, usage=usage),
    )


@router.get("/firewall")
def admin_firewall(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    events = db.query(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(120).all()
    rules = db.query(SecurityRule).order_by(SecurityRule.created_at.desc()).limit(80).all()
    incidents = db.query(SecurityIncident).order_by(SecurityIncident.updated_at.desc()).limit(80).all()
    playbooks = db.query(SecurityPlaybook).filter(SecurityPlaybook.is_active.is_(True)).order_by(SecurityPlaybook.title.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/firewall.html",
        context=context(
            request,
            admin=admin,
            events=events,
            rules=rules,
            incidents=incidents,
            playbooks=playbooks,
            security_summary=dashboard_summary(db),
        ),
    )


@router.post("/firewall/rules")
def create_firewall_rule(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    name: str = Form(...),
    rule_type: str = Form(...),
    value: str = Form(...),
    action: str = Form("block"),
    severity: str = Form("medium"),
    note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    admin = require_admin(request, db)
    if rule_type not in {
        "ip_allow",
        "ip_block",
        "cidr_allow",
        "cidr_block",
        "country_allow",
        "country_block",
        "user_agent_block",
        "path_protect",
        "route_rate_limit",
    }:
        return RedirectResponse("/admin/firewall?error=invalid_rule_type", status_code=303)
    if action not in {"allow", "block", "challenge", "log"}:
        return RedirectResponse("/admin/firewall?error=invalid_action", status_code=303)
    item = SecurityRule(
        name=name.strip()[:160],
        rule_type=rule_type,
        value=value.strip()[:255],
        action=action,
        severity=severity if severity in {"info", "low", "medium", "high", "critical"} else "medium",
        note=note.strip(),
        created_by_user_id=admin.id,
        is_active=True,
    )
    db.add(item)
    db.commit()
    return RedirectResponse("/admin/firewall?rule_created=1", status_code=303)


@router.post("/firewall/rules/{rule_id}/toggle")
def toggle_firewall_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(SecurityRule, rule_id)
    if not item:
        return RedirectResponse("/admin/firewall?error=rule_not_found", status_code=303)
    item.is_active = not item.is_active
    db.commit()
    return RedirectResponse("/admin/firewall?rule_updated=1", status_code=303)


@router.post("/firewall/incidents/{incident_id}")
def update_firewall_incident(
    incident_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    status: str = Form(...),
    resolution_note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(SecurityIncident, incident_id)
    if not item:
        return RedirectResponse("/admin/firewall?error=incident_not_found", status_code=303)
    if status not in {"open", "investigating", "contained", "resolved", "false_positive"}:
        return RedirectResponse("/admin/firewall?error=invalid_status", status_code=303)
    item.status = status
    item.resolution_note = resolution_note.strip()
    db.commit()
    return RedirectResponse("/admin/firewall?incident_updated=1", status_code=303)
