from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("services", "0001_initial")]

    operations = [
        migrations.RemoveField(model_name="service", name="deposit_amount"),
        migrations.RemoveField(model_name="service", name="requires_deposit"),
    ]
