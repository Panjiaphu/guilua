from django.contrib import admin

from .models import MarketLine, OddsImportBatch, Ticket


@admin.register(OddsImportBatch)
class OddsImportBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "note", "created_at", "updated_at")
    search_fields = ("note", "raw_app_text")


@admin.register(MarketLine)
class MarketLineAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "match_name",
        "market_type",
        "selection",
        "app_odds",
        "outside_odds",
        "status",
        "updated_at",
    )
    list_filter = ("status", "market_type")
    search_fields = ("code", "match_name", "market_type", "selection")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_code",
        "ticket_date",
        "customer_name",
        "match_name_snapshot",
        "customer_stake",
        "app_stake",
        "remaining_cash",
        "status",
        "result",
    )
    list_filter = ("ticket_date", "status", "result")
    search_fields = ("ticket_code", "customer_name", "match_name_snapshot", "selection_snapshot")
