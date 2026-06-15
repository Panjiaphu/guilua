from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from odds.models import MarketLineStatus, Ticket, TicketResult, TicketStatus

from .calculations import calculate_ticket


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
        if ticket.status != TicketStatus.SETTLED:
            continue
        if ticket.result == TicketResult.WIN:
            settled_profit += ticket.profit_if_win
        elif ticket.result == TicketResult.LOSE:
            settled_profit += ticket.profit_if_lose

    return {
        "ticket_date": ticket_date,
        "ticket_count": tickets.count(),
        "open_count": tickets.filter(status=TicketStatus.OPEN).count(),
        "settled_count": tickets.filter(status=TicketStatus.SETTLED).count(),
        "customer_stake": totals["customer_stake"] or 0,
        "app_stake": totals["app_stake"] or 0,
        "remaining_cash": totals["remaining_cash"] or 0,
        "profit_if_win": totals["profit_if_win"] or 0,
        "profit_if_lose": totals["profit_if_lose"] or 0,
        "settled_profit": settled_profit,
    }
