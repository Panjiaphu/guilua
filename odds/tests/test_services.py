from decimal import Decimal
import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.core.exceptions import ValidationError
from django.test import Client, TestCase

django.setup()

from odds.models import MarketLine
from odds.services.calculations import TicketCalculationError, calculate_ticket
from odds.services.import_flow import merge_outside_odds, parse_app_odds_text
from odds.services.tickets import create_ticket_from_market_line, parse_ticket_batch_text


class CalculationTests(unittest.TestCase):
    def test_calculates_app_stake_and_profit_fields(self):
        result = calculate_ticket(customer_stake="1000", app_odds="2.00", outside_odds="1.80")

        self.assertEqual(result.app_stake, Decimal("900.00"))
        self.assertEqual(result.remaining_cash, Decimal("100.00"))
        self.assertEqual(result.customer_payout_if_win, Decimal("1800.00"))
        self.assertEqual(result.app_payout_if_win, Decimal("1800.00"))
        self.assertEqual(result.profit_if_win, Decimal("100.00"))
        self.assertEqual(result.profit_if_lose, Decimal("100.00"))

    def test_rejects_invalid_odds_and_stake(self):
        with self.assertRaises(TicketCalculationError):
            calculate_ticket(customer_stake="0", app_odds="2", outside_odds="1.8")
        with self.assertRaises(TicketCalculationError):
            calculate_ticket(customer_stake="100", app_odds="1", outside_odds="1.8")
        with self.assertRaises(TicketCalculationError):
            calculate_ticket(customer_stake="100", app_odds="2", outside_odds="1")


class ImportFlowTests(unittest.TestCase):
    def test_app_paste_keeps_outside_odds_empty(self):
        preview = parse_app_odds_text("Team A vs Team B | Handicap | Team A | -0.5 | 1.95")

        self.assertEqual(len(preview.lines), 1)
        line = preview.lines[0]
        self.assertEqual(line.app_odds, Decimal("1.95"))
        self.assertIsNone(line.outside_odds)
        self.assertEqual(line.status, "missing_outside_odds")

    def test_merges_outside_odds_by_order_and_warns_when_needed(self):
        preview = parse_app_odds_text(
            "A vs B | Over/Under | Over | 2.5 | 1.90\n"
            "C vs D | Moneyline | C | 2.10"
        )
        merge_outside_odds(preview, "1.88\n2.20")

        self.assertTrue(preview.can_save)
        self.assertEqual(preview.lines[0].outside_odds, Decimal("1.88"))
        self.assertEqual(preview.lines[1].warning, "Canh bao: ty le ngoai lon hon hoac bang ty le app.")

    def test_blocks_ambiguous_mapping(self):
        preview = parse_app_odds_text("Only one unclear row 1.80")

        self.assertEqual(preview.lines[0].status, "needs_confirmation")
        self.assertFalse(preview.can_save)

    def test_outside_odds_count_must_match_rows(self):
        preview = parse_app_odds_text(
            "A vs B | Handicap | A | -0.5 | 1.90\n"
            "C vs D | Handicap | C | +0.5 | 2.00"
        )
        merge_outside_odds(preview, "1.80")

        self.assertFalse(preview.can_save)
        self.assertIn("khong khop", preview.errors[-1])


class TicketWorkflowTests(TestCase):
    def test_blocks_ticket_when_market_line_missing_outside_odds(self):
        line = MarketLine.objects.create(
            match_name="A vs B",
            market_type="Handicap",
            selection="A",
            handicap="-0.5",
            app_odds=Decimal("1.90"),
        )

        with self.assertRaises(ValidationError):
            create_ticket_from_market_line(line, customer_stake=Decimal("1000"))

    def test_ticket_stores_snapshot_and_does_not_follow_line_edits(self):
        line = MarketLine.objects.create(
            match_name="A vs B",
            market_type="Handicap",
            selection="A",
            handicap="-0.5",
            app_odds=Decimal("2.00"),
            outside_odds=Decimal("1.80"),
        )

        ticket = create_ticket_from_market_line(line, customer_stake=Decimal("1000"))

        line.app_odds = Decimal("2.20")
        line.outside_odds = Decimal("1.70")
        line.save()
        ticket.refresh_from_db()

        self.assertEqual(ticket.app_odds_snapshot, Decimal("2.000"))
        self.assertEqual(ticket.outside_odds_snapshot, Decimal("1.800"))
        self.assertEqual(ticket.app_stake, Decimal("900.00"))

    def test_market_line_and_ticket_codes_are_generated(self):
        line = MarketLine.objects.create(
            match_name="A vs B",
            market_type="Handicap",
            selection="A",
            handicap="-0.5",
            app_odds=Decimal("2.00"),
            outside_odds=Decimal("1.80"),
        )
        ticket = create_ticket_from_market_line(line, customer_stake=Decimal("1000"))

        self.assertTrue(line.code.startswith("L"))
        self.assertTrue(ticket.ticket_code.startswith("A"))
        self.assertEqual(ticket.status, "pending")

    def test_bulk_ticket_preview_uses_market_line_code(self):
        line = MarketLine.objects.create(
            match_name="A vs B",
            market_type="Handicap",
            selection="A",
            handicap="-0.5",
            app_odds=Decimal("2.00"),
            outside_odds=Decimal("1.80"),
        )

        preview = parse_ticket_batch_text(f"{line.code} 1000")

        self.assertTrue(preview.can_save)
        self.assertEqual(preview.lines[0].market_code, line.code)
        self.assertEqual(preview.lines[0].app_stake, Decimal("900.00"))

    def test_bulk_ticket_preview_blocks_missing_outside_odds(self):
        line = MarketLine.objects.create(
            match_name="A vs B",
            market_type="Handicap",
            selection="A",
            handicap="-0.5",
            app_odds=Decimal("2.00"),
        )

        preview = parse_ticket_batch_text(f"{line.code} 1000")

        self.assertFalse(preview.can_save)
        self.assertIn("chua san sang", preview.lines[0].error)


class RouteRenderTests(TestCase):
    def test_main_routes_render(self):
        client = Client()

        for path in ["/", "/tickets/", "/summary/"]:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
