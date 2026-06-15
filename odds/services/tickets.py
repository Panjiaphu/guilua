from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from odds.models import MarketLine, MarketLineStatus, Ticket, TicketStatus

from .calculations import calculate_ticket


TICKET_LINE_PATTERN = re.compile(r"^(?P<code>L\d{1,6})\s+((?P<stake>\d+(?:[\.,]\d{1,2})?))", re.IGNORECASE)


@dataclass
class TicketPreviewLine:
    row_number: int
    raw_text: str
    market_code: str = ""
    customer_stake: Decimal | None = None
    market_line: MarketLine | None = None
    app_stake: Decimal | None = None
    remaining_cash: Decimal | None = None
    profit_if_win: Decimal | None = None
    profit_if_lose: Decimal | None = None
    status: str = "invalid"
    error: str = ""
    warning: str = ""


@dataclass
class TicketBatchPreview:
    raw_text: str
    lines: list[TicketPreviewLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ready_count(self):
        return sum(1 for line in self.lines if line.status == "ready")

    @property
    def can_save(self):
        return bool(self.lines) and all(line.status == "ready" for line in self.lines)


def parse_stake(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def parse_ticket_batch_text(raw_text):
    preview = TicketBatchPreview(raw_text=raw_text or "")
    source_lines = [line.strip() for line in preview.raw_text.splitlines() if line.strip()]
    if not source_lines:
        preview.errors.append("Chua co danh sach ve de phan tich.")
        return preview

    for row_number, raw_line in enumerate(source_lines, start=1):
        match = TICKET_LINE_PATTERN.search(raw_line)
        if not match:
            preview.lines.append(
                TicketPreviewLine(
                    row_number=row_number,
                    raw_text=raw_line,
                    error="Dinh dang dung: L001 1000.",
                )
            )
            continue

        market_code = match.group("code").upper()
        customer_stake = parse_stake(match.group("stake"))
        line = TicketPreviewLine(
            row_number=row_number,
            raw_text=raw_line,
            market_code=market_code,
            customer_stake=customer_stake,
        )
        if customer_stake is None or customer_stake <= Decimal("0"):
            line.error = "Von khach phai lon hon 0."
            preview.lines.append(line)
            continue

        market_line = MarketLine.objects.filter(code=market_code).first()
        if not market_line:
            line.error = f"Khong tim thay dong ty le {market_code}."
            preview.lines.append(line)
            continue

        market_line.refresh_status()
        line.market_line = market_line
        if market_line.status != MarketLineStatus.READY:
            line.error = f"Dong {market_code} chua san sang hoac thieu ty le ngoai."
            preview.lines.append(line)
            continue

        calculation = calculate_ticket(
            customer_stake=customer_stake,
            app_odds=market_line.app_odds,
            outside_odds=market_line.outside_odds,
        )
        line.app_stake = calculation.app_stake
        line.remaining_cash = calculation.remaining_cash
        line.profit_if_win = calculation.profit_if_win
        line.profit_if_lose = calculation.profit_if_lose
        line.status = "ready"
        if market_line.warning:
            line.warning = market_line.warning
        preview.lines.append(line)

    return preview


def create_ticket_from_market_line(market_line, customer_stake, customer_name="", note="", ticket_date=None):
    market_line.refresh_status()
    if market_line.status != MarketLineStatus.READY:
        raise ValidationError("Khong the tao ve khi dong ty le chua san sang.")

    calculation = calculate_ticket(
        customer_stake=customer_stake,
        app_odds=market_line.app_odds,
        outside_odds=market_line.outside_odds,
    )

    ticket_kwargs = {
        "market_line": market_line,
        "customer_name": customer_name,
        "customer_stake": calculation.customer_stake,
        "note": note,
        "match_name_snapshot": market_line.match_name,
        "market_type_snapshot": market_line.market_type,
        "selection_snapshot": market_line.selection,
        "handicap_snapshot": market_line.handicap,
        "app_odds_snapshot": calculation.app_odds,
        "outside_odds_snapshot": calculation.outside_odds,
        "app_stake": calculation.app_stake,
        "remaining_cash": calculation.remaining_cash,
        "customer_payout_if_win": calculation.customer_payout_if_win,
        "app_payout_if_win": calculation.app_payout_if_win,
        "profit_if_win": calculation.profit_if_win,
        "profit_if_lose": calculation.profit_if_lose,
    }
    if ticket_date:
        ticket_kwargs["ticket_date"] = ticket_date

    with transaction.atomic():
        ticket = Ticket.objects.create(**ticket_kwargs)
    return ticket


def create_tickets_from_preview(preview, customer_name="", note="", ticket_date=None):
    if not preview.can_save:
        raise ValidationError("Chi duoc luu ve khi tat ca dong preview hop le.")
    tickets = []
    with transaction.atomic():
        for line in preview.lines:
            tickets.append(
                create_ticket_from_market_line(
                    market_line=line.market_line,
                    customer_stake=line.customer_stake,
                    customer_name=customer_name,
                    note=note or f"Bulk {line.raw_text}",
                    ticket_date=ticket_date,
                )
            )
    return tickets


def summarize_day(ticket_date):
    tickets = Ticket.objects.filter(ticket_date=ticket_date)
    totals = tickets.aggregate(
        customer_stake=Sum("customer_stake"),
        app_stake=Sum("app_stake"),
        remaining_cash=Sum("remaining_cash"),
        profit_if_win=Sum("profit_if_win"),
        profit_if_lose=Sum("profit_if_lose"),
    )
    settled_profit = 0
    for ticket in tickets:
        if ticket.status == TicketStatus.WIN:
            settled_profit += ticket.profit_if_win
        elif ticket.status == TicketStatus.LOSE:
            settled_profit += ticket.profit_if_lose
        elif ticket.status == TicketStatus.PAID:
            if ticket.result == "win":
                settled_profit += ticket.profit_if_win
            elif ticket.result == "lose":
                settled_profit += ticket.profit_if_lose

    return {
        "ticket_date": ticket_date,
        "ticket_count": tickets.count(),
        "open_count": tickets.filter(status=TicketStatus.PENDING).count(),
        "settled_count": tickets.exclude(status=TicketStatus.PENDING).count(),
        "customer_stake": totals["customer_stake"] or 0,
        "app_stake": totals["app_stake"] or 0,
        "remaining_cash": totals["remaining_cash"] or 0,
        "profit_if_win": totals["profit_if_win"] or 0,
        "profit_if_lose": totals["profit_if_lose"] or 0,
        "settled_profit": settled_profit,
    }
