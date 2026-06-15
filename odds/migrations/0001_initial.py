from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="OddsImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("raw_app_text", models.TextField()),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MarketLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("row_number", models.PositiveIntegerField(default=1)),
                ("match_name", models.CharField(max_length=255)),
                ("market_type", models.CharField(max_length=120)),
                ("selection", models.CharField(max_length=120)),
                ("handicap", models.CharField(blank=True, max_length=60)),
                ("app_odds", models.DecimalField(decimal_places=3, max_digits=10)),
                ("outside_odds", models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("missing_outside_odds", "Thieu ty le ngoai"),
                            ("ready", "San sang"),
                            ("needs_confirmation", "Can xac nhan"),
                            ("invalid", "Khong hop le"),
                            ("closed", "Da dong"),
                        ],
                        default="missing_outside_odds",
                        max_length=32,
                    ),
                ),
                ("warning", models.CharField(blank=True, max_length=255)),
                ("error", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="odds.oddsimportbatch",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "row_number", "id"],
                "indexes": [
                    models.Index(fields=["status"], name="odds_market_status_89c92c_idx"),
                    models.Index(fields=["match_name", "market_type"], name="odds_market_match_n_25a969_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_name", models.CharField(blank=True, max_length=120)),
                ("customer_stake", models.DecimalField(decimal_places=2, max_digits=12)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("match_name_snapshot", models.CharField(max_length=255)),
                ("market_type_snapshot", models.CharField(max_length=120)),
                ("selection_snapshot", models.CharField(max_length=120)),
                ("handicap_snapshot", models.CharField(blank=True, max_length=60)),
                ("app_odds_snapshot", models.DecimalField(decimal_places=3, max_digits=10)),
                ("outside_odds_snapshot", models.DecimalField(decimal_places=3, max_digits=10)),
                ("app_stake", models.DecimalField(decimal_places=2, max_digits=12)),
                ("remaining_cash", models.DecimalField(decimal_places=2, max_digits=12)),
                ("customer_payout_if_win", models.DecimalField(decimal_places=2, max_digits=12)),
                ("app_payout_if_win", models.DecimalField(decimal_places=2, max_digits=12)),
                ("profit_if_win", models.DecimalField(decimal_places=2, max_digits=12)),
                ("profit_if_lose", models.DecimalField(decimal_places=2, max_digits=12)),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Dang mo"), ("settled", "Da doi soat"), ("void", "Huy")],
                        default="open",
                        max_length=16,
                    ),
                ),
                (
                    "result",
                    models.CharField(
                        choices=[
                            ("pending", "Chua co ket qua"),
                            ("win", "Khach thang"),
                            ("lose", "Khach thua"),
                            ("void", "Huy"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("ticket_date", models.DateField(default=django.utils.timezone.localdate)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "market_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tickets",
                        to="odds.marketline",
                    ),
                ),
            ],
            options={
                "ordering": ["-ticket_date", "-created_at"],
                "indexes": [
                    models.Index(fields=["ticket_date"], name="odds_ticket_ticket__8d25fd_idx"),
                    models.Index(fields=["status", "result"], name="odds_ticket_status_80ffc4_idx"),
                ],
            },
        ),
    ]
