from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import SummaryDateForm, TicketCreateForm
from .models import MarketLine, OddsImportBatch, Ticket
from .services.import_flow import (
    ImportPreview,
    PreviewLine,
    format_decimal,
    merge_outside_odds,
    parse_app_odds_text,
    parse_decimal,
    refresh_preview_status,
)
from .services.tickets import create_ticket_from_market_line, summarize_day


SESSION_PREVIEW_KEY = "odds_import_preview"


def _line_to_dict(line):
    return {
        "row_number": line.row_number,
        "match_name": line.match_name,
        "market_type": line.market_type,
        "selection": line.selection,
        "handicap": line.handicap,
        "app_odds": format_decimal(line.app_odds),
        "outside_odds": format_decimal(line.outside_odds),
        "status": line.status,
        "warning": line.warning,
        "error": line.error,
        "raw_text": line.raw_text,
        "needs_confirmation": line.needs_confirmation,
        "confidence": line.confidence,
    }


def _preview_to_dict(preview):
    return {
        "raw_app_text": preview.raw_app_text,
        "errors": preview.errors,
        "lines": [_line_to_dict(line) for line in preview.lines],
    }


def _preview_from_dict(data):
    preview = ImportPreview(raw_app_text=data.get("raw_app_text", ""))
    preview.errors = list(data.get("errors", []))
    for item in data.get("lines", []):
        line = PreviewLine(
            row_number=int(item["row_number"]),
            match_name=item["match_name"],
            market_type=item["market_type"],
            selection=item["selection"],
            handicap=item.get("handicap", ""),
            app_odds=parse_decimal(item.get("app_odds")),
            outside_odds=parse_decimal(item.get("outside_odds")),
            status=item.get("status", "missing_outside_odds"),
            warning=item.get("warning", ""),
            error=item.get("error", ""),
            raw_text=item.get("raw_text", ""),
            needs_confirmation=bool(item.get("needs_confirmation")),
            confidence=item.get("confidence", "normal"),
        )
        preview.lines.append(refresh_preview_status(line))
    return preview


def _get_preview(request):
    data = request.session.get(SESSION_PREVIEW_KEY)
    return _preview_from_dict(data) if data else None


def _store_preview(request, preview):
    request.session[SESSION_PREVIEW_KEY] = _preview_to_dict(preview)
    request.session.modified = True


def import_odds(request):
    preview = _get_preview(request)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "parse_app":
            preview = parse_app_odds_text(request.POST.get("raw_app_text", ""))
            _store_preview(request, preview)
            if preview.errors:
                messages.error(request, preview.errors[-1])
            else:
                messages.success(request, f"Da parse {len(preview.lines)} dong ty le app.")

        elif action == "merge_outside" and preview:
            preview.errors = []
            merge_outside_odds(preview, request.POST.get("outside_odds_text", ""))
            _store_preview(request, preview)
            if preview.errors:
                messages.error(request, preview.errors[-1])
            else:
                messages.success(request, "Da ghep ty le ngoai theo dung thu tu preview.")

        elif action == "update_manual" and preview:
            preview.errors = []
            for line in preview.lines:
                key = f"outside_odds_{line.row_number}"
                line.outside_odds = parse_decimal(request.POST.get(key))
                refresh_preview_status(line)
            _store_preview(request, preview)
            messages.success(request, "Da cap nhat ty le ngoai tren preview.")

        elif action == "save_lines" and preview:
            preview.errors = []
            for line in preview.lines:
                refresh_preview_status(line)
            if not preview.can_save:
                messages.error(request, "Chi duoc luu khi tat ca dong co app odds va outside odds hop le.")
            else:
                batch = OddsImportBatch.objects.create(raw_app_text=preview.raw_app_text)
                for line in preview.lines:
                    MarketLine.objects.create(
                        batch=batch,
                        row_number=line.row_number,
                        match_name=line.match_name,
                        market_type=line.market_type,
                        selection=line.selection,
                        handicap=line.handicap,
                        app_odds=line.app_odds,
                        outside_odds=line.outside_odds,
                    )
                request.session.pop(SESSION_PREVIEW_KEY, None)
                messages.success(request, "Da luu bang ty le hoan chinh. Co the nhap ve.")
                return redirect("odds:tickets")

        else:
            messages.error(request, "Chua co preview de xu ly.")

    return render(
        request,
        "odds/import.html",
        {
            "preview": preview,
            "recent_lines": MarketLine.objects.order_by("-created_at")[:8],
        },
    )


def tickets(request):
    form = TicketCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = create_ticket_from_market_line(
                market_line=form.cleaned_data["market_line"],
                customer_stake=form.cleaned_data["customer_stake"],
                customer_name=form.cleaned_data["customer_name"],
                note=form.cleaned_data["note"],
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Da tao ve #{ticket.id} va luu snapshot odds.")
            return redirect("odds:tickets")

    return render(
        request,
        "odds/tickets.html",
        {
            "form": form,
            "ready_lines": MarketLine.objects.filter(status="ready").order_by("-created_at")[:20],
            "tickets": Ticket.objects.select_related("market_line").order_by("-created_at")[:30],
        },
    )


def summary(request):
    form = SummaryDateForm(request.GET or None)
    ticket_date = timezone.localdate()
    if form.is_valid():
        ticket_date = form.cleaned_data["ticket_date"]
    data = summarize_day(ticket_date)
    tickets_for_day = Ticket.objects.filter(ticket_date=ticket_date).order_by("-created_at")

    copy_lines = [
        f"Ngay: {ticket_date:%Y-%m-%d}",
        f"So ve: {data['ticket_count']}",
        f"Tong von khach: {Decimal(data['customer_stake']):,.2f}",
        f"Tong nhap app: {Decimal(data['app_stake']):,.2f}",
        f"Tien con lai: {Decimal(data['remaining_cash']):,.2f}",
        f"Lai neu khach thang: {Decimal(data['profit_if_win']):,.2f}",
        f"Lai neu khach thua: {Decimal(data['profit_if_lose']):,.2f}",
        f"Lai da doi soat: {Decimal(data['settled_profit']):,.2f}",
    ]

    return render(
        request,
        "odds/summary.html",
        {
            "form": form,
            "summary": data,
            "tickets": tickets_for_day,
            "copy_text": "\n".join(copy_lines),
        },
    )
