from fastapi import Request

from app.core.config import get_settings


MESSAGES = {
    "vi": {
        "nav.send_home": "Gui tien",
        "nav.buy_usdt": "Mua USDT",
        "nav.sell_usdt": "Ban USDT",
        "nav.rates": "Ty gia",
        "nav.member": "Hoi vien",
        "nav.admin": "Quan tri",
        "nav.login": "Dang nhap",
        "nav.logout": "Dang xuat",
        "home.title": "Guilua Finance",
        "home.subtitle": "Gui tien TWD ve Viet Nam, mua ban USDT va theo doi yeu cau tren mot dashboard song ngu.",
        "auth.email": "Email",
        "auth.password": "Mat khau",
        "auth.full_name": "Ho ten",
        "auth.login": "Dang nhap",
        "auth.register": "Dang ky",
        "auth.verify_badge": "Email da xac minh",
        "member.dashboard": "Dashboard thanh vien",
        "member.requests": "Yeu cau cua toi",
        "member.new_request": "Tao yeu cau giao dich",
        "admin.dashboard": "Dashboard quan tri",
        "admin.requests": "Quan ly yeu cau",
        "rates.manual": "Ty gia thu cong",
        "status.pending": "Dang cho",
        "status.in_review": "Dang xu ly",
        "status.needs_info": "Can bo sung",
        "status.approved": "Da duyet",
        "status.completed": "Da hoan thanh",
        "status.rejected": "Tu choi",
        "status.cancelled": "Da huy",
    },
    "zh-TW": {
        "nav.send_home": "匯款",
        "nav.buy_usdt": "買 USDT",
        "nav.sell_usdt": "賣 USDT",
        "nav.rates": "匯率",
        "nav.member": "會員中心",
        "nav.admin": "管理後台",
        "nav.login": "登入",
        "nav.logout": "登出",
        "home.title": "Guilua Finance",
        "home.subtitle": "以雙語介面處理台幣匯款到越南、USDT 買賣與交易申請追蹤。",
        "auth.email": "Email",
        "auth.password": "密碼",
        "auth.full_name": "姓名",
        "auth.login": "登入",
        "auth.register": "註冊",
        "auth.verify_badge": "Email 已驗證",
        "member.dashboard": "會員儀表板",
        "member.requests": "我的申請",
        "member.new_request": "建立交易申請",
        "admin.dashboard": "管理儀表板",
        "admin.requests": "交易申請管理",
        "rates.manual": "手動匯率",
        "status.pending": "待處理",
        "status.in_review": "審核中",
        "status.needs_info": "需補件",
        "status.approved": "已核准",
        "status.completed": "已完成",
        "status.rejected": "已拒絕",
        "status.cancelled": "已取消",
    },
}


def resolve_locale(request: Request) -> str:
    settings = get_settings()
    lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_locale
    return lang if lang in settings.supported_locales else settings.default_locale


def t(locale: str, key: str) -> str:
    return MESSAGES.get(locale, MESSAGES["vi"]).get(key, key)
