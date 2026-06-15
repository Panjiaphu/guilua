from django import forms
from django.utils import timezone
from decimal import Decimal

from .models import MarketLine, Ticket


class TicketCreateForm(forms.Form):
    market_line = forms.ModelChoiceField(
        queryset=MarketLine.objects.none(),
        label="Dong ty le",
        empty_label="Chon dong ty le da san sang",
    )
    customer_name = forms.CharField(label="Ten khach", required=False, max_length=120)
    customer_stake = forms.DecimalField(
        label="Von khach",
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
    )
    note = forms.CharField(label="Ghi chu", required=False, max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["market_line"].queryset = MarketLine.objects.filter(status="ready")


class BulkTicketForm(forms.Form):
    raw_tickets = forms.CharField(
        label="Paste danh sach ve",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 7,
                "placeholder": "L001 1000\nL002 500\nL003 2000",
            }
        ),
    )
    customer_name = forms.CharField(label="Ten khach", required=False, max_length=120)
    note = forms.CharField(label="Ghi chu", required=False, max_length=255)


class SummaryDateForm(forms.Form):
    ticket_date = forms.DateField(
        label="Ngay",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class TicketSettleForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["status", "result"]
