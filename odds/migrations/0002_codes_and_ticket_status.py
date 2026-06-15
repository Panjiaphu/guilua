from django.db import migrations, models


def populate_codes(apps, schema_editor):
    MarketLine = apps.get_model("odds", "MarketLine")
    Ticket = apps.get_model("odds", "Ticket")

    for index, line in enumerate(MarketLine.objects.order_by("created_at", "id"), start=1):
        line.code = f"L{index:03d}"
        line.save(update_fields=["code"])

    for index, ticket in enumerate(Ticket.objects.order_by("created_at", "id"), start=1):
        ticket.ticket_code = f"A{index:03d}"
        if ticket.status == "open":
            ticket.status = "pending"
        elif ticket.status == "settled":
            ticket.status = "paid"
        elif ticket.status == "void":
            ticket.status = "cancelled"
        ticket.save(update_fields=["ticket_code", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("odds", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketline",
            name="code",
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="ticket_code",
            field=models.CharField(blank=True, max_length=20, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Cho doi"),
                    ("win", "Thang"),
                    ("lose", "Thua"),
                    ("push", "Hoa von"),
                    ("half_win", "Thang nua"),
                    ("half_loss", "Thua nua"),
                    ("cancelled", "Huy"),
                    ("paid", "Da thanh toan"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.RunPython(populate_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="marketline",
            name="code",
            field=models.CharField(blank=True, max_length=20, unique=True),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="ticket_code",
            field=models.CharField(blank=True, max_length=20, unique=True),
        ),
    ]
