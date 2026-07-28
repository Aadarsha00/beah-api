from django.db import migrations


def activate_legacy_users(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        is_active=False,
        is_staff=False,
        is_superuser=False,
    ).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_activate_new_users")]

    operations = [
        migrations.RunPython(
            activate_legacy_users,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
