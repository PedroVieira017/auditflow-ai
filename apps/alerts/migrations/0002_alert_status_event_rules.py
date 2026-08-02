from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="alertstatusevent",
            name="note",
            field=models.TextField(max_length=2_000),
        ),
        migrations.AddConstraint(
            model_name="alertstatusevent",
            constraint=models.CheckConstraint(
                condition=~Q(from_status=F("to_status")),
                name="alert_status_event_changes_status",
            ),
        ),
    ]
