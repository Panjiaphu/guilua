from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def next_sequence_code(model, field_name, prefix):
    last = model.objects.order_by("-id").first()
    number = (last.id + 1) if last else 1
    while model.objects.filter(**{field_name: f"{prefix}{number:03d}"}).exists():
        number += 1
    return f"{prefix}{number:03d}"


class MarketLineStatus(models.TextChoices):
    MISSING_OUTSIDE_ODDS = "missing_outside_odds", "Thieu ty le ngoai"
    READY = "ready", "San sang"
    NEEDS_CONFIRMATION = "needs_confirmation", "Can xac nhan"
    INVALID = "invalid", "Khong hop le"
    CLOSED = "closed", "Da dong"


class TicketStatus(models.TextChoices):
    PENDING = "pending", "Cho doi"
    WIN = "win", "Thang"
    LOSE = "lose", "Thua"
    PUSH = "push", "Hoa von"
    HALF_WIN = "half_win", "Thang nua"
    HALF_LOSS = "half_loss", "Thua nua"
    CANCELLED = "cancelled", "Huy"
    PAID = "paid", "Da thanh toan"


class TicketResult(models.TextChoices):
    PENDING = "pending", "Chua co ket qua"
    WIN = "win", "Khach thang"
    LOSE = "lose", "Khach thua"
    VOID = "void", "Huy"


class OddsImportBatch(models.Model):
    raw_app_text = models.TextField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Import {self.id or 'new'} - {self.created_at:%Y-%m-%d %H:%M}"


class MarketLine(models.Model):
    batch = models.ForeignKey(
        OddsImportBatch,
        related_name="lines",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    code = models.CharField(max_length=20, unique=True, blank=True)
    row_number = models.PositiveIntegerField(default=1)
    match_name = models.CharField(max_length=255)
    market_type = models.CharField(max_length=120)
    selection = models.CharField(max_length=120)
    handicap = models.CharField(max_length=60, blank=True)
    app_odds = models.DecimalField(max_digits=10, decimal_places=3)
    outside_odds = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=MarketLineStatus.choices,
        default=MarketLineStatus.MISSING_OUTSIDE_ODDS,
    )
    warning = models.CharField(max_length=255, blank=True)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "row_number", "id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["match_name", "market_type"]),
        ]

    def clean(self):
        errors = {}
        if self.app_odds is None or self.app_odds <= Decimal("1"):
            errors["app_odds"] = "Ty le app phai lon hon 1."
        if self.outside_odds is not None and self.outside_odds <= Decimal("1"):
            errors["outside_odds"] = "Ty le ngoai phai lon hon 1."
        if errors:
            raise ValidationError(errors)

    def refresh_status(self):
        self.error = ""
        self.warning = ""
        if self.app_odds is None or self.app_odds <= Decimal("1"):
            self.status = MarketLineStatus.INVALID
            self.error = "Ty le app phai lon hon 1."
        elif self.outside_odds is None:
            self.status = MarketLineStatus.MISSING_OUTSIDE_ODDS
        elif self.outside_odds <= Decimal("1"):
            self.status = MarketLineStatus.INVALID
            self.error = "Ty le ngoai phai lon hon 1."
        else:
            self.status = MarketLineStatus.READY
            if self.outside_odds >= self.app_odds:
                self.warning = "Canh bao: ty le ngoai lon hon hoac bang ty le app."
        return self.status

    @property
    def is_ready(self):
        return self.status == MarketLineStatus.READY

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_sequence_code(MarketLine, "code", "L")
        self.refresh_status()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.match_name} - {self.market_type} - {self.selection}"


class Ticket(models.Model):
    market_line = models.ForeignKey(
        MarketLine,
        related_name="tickets",
        on_delete=models.PROTECT,
    )
    ticket_code = models.CharField(max_length=20, unique=True, blank=True)
    customer_name = models.CharField(max_length=120, blank=True)
    customer_stake = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)

    match_name_snapshot = models.CharField(max_length=255)
    market_type_snapshot = models.CharField(max_length=120)
    selection_snapshot = models.CharField(max_length=120)
    handicap_snapshot = models.CharField(max_length=60, blank=True)
    app_odds_snapshot = models.DecimalField(max_digits=10, decimal_places=3)
    outside_odds_snapshot = models.DecimalField(max_digits=10, decimal_places=3)

    app_stake = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_cash = models.DecimalField(max_digits=12, decimal_places=2)
    customer_payout_if_win = models.DecimalField(max_digits=12, decimal_places=2)
    app_payout_if_win = models.DecimalField(max_digits=12, decimal_places=2)
    profit_if_win = models.DecimalField(max_digits=12, decimal_places=2)
    profit_if_lose = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=16,
        choices=TicketStatus.choices,
        default=TicketStatus.PENDING,
    )
    result = models.CharField(
        max_length=16,
        choices=TicketResult.choices,
        default=TicketResult.PENDING,
    )
    ticket_date = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-ticket_date", "-created_at"]
        indexes = [
            models.Index(fields=["ticket_date"]),
            models.Index(fields=["status", "result"]),
        ]

    def save(self, *args, **kwargs):
        if not self.ticket_code:
            self.ticket_code = next_sequence_code(Ticket, "ticket_code", "A")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticket_code} - {self.customer_name or 'Khach'} - {self.customer_stake}"
