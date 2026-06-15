from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


MONEY_QUANT = Decimal("0.01")
ODDS_QUANT = Decimal("0.001")


class TicketCalculationError(ValueError):
    pass


@dataclass(frozen=True)
class TicketCalculation:
    customer_stake: Decimal
    app_odds: Decimal
    outside_odds: Decimal
    app_stake: Decimal
    remaining_cash: Decimal
    customer_payout_if_win: Decimal
    app_payout_if_win: Decimal
    profit_if_win: Decimal
    profit_if_lose: Decimal


def to_decimal(value, field_name="value"):
    if value in (None, ""):
        raise TicketCalculationError(f"{field_name} is required.")
    try:
        return Decimal(str(value).strip())
    except Exception as exc:
        raise TicketCalculationError(f"{field_name} must be numeric.") from exc


def quantize_money(value):
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def normalize_odds(value, field_name="odds"):
    odds = to_decimal(value, field_name).quantize(ODDS_QUANT)
    if odds <= Decimal("1"):
        raise TicketCalculationError(f"{field_name} must be greater than 1.")
    return odds


def calculate_ticket(customer_stake, app_odds, outside_odds):
    stake = to_decimal(customer_stake, "customer_stake")
    if stake <= Decimal("0"):
        raise TicketCalculationError("customer_stake must be greater than 0.")

    app = normalize_odds(app_odds, "app_odds")
    outside = normalize_odds(outside_odds, "outside_odds")

    app_stake = quantize_money(stake * outside / app)
    remaining_cash = quantize_money(stake - app_stake)
    customer_payout_if_win = quantize_money(stake * outside)
    app_payout_if_win = quantize_money(app_stake * app)
    profit_if_win = quantize_money(app_payout_if_win - customer_payout_if_win + remaining_cash)
    profit_if_lose = remaining_cash

    return TicketCalculation(
        customer_stake=quantize_money(stake),
        app_odds=app,
        outside_odds=outside,
        app_stake=app_stake,
        remaining_cash=remaining_cash,
        customer_payout_if_win=customer_payout_if_win,
        app_payout_if_win=app_payout_if_win,
        profit_if_win=profit_if_win,
        profit_if_lose=profit_if_lose,
    )
