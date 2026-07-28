from django.db import migrations

# CUTOVER WARNING:
# This historical migration must run only while a newly migrated target contains
# no users. Applying it to a populated legacy database activates every inactive
# non-staff account, including accounts that may have been deliberately disabled.
# The lossless cutover restores users only after migrations and preserves each
# source is_active value exactly. See DEPLOYMENT.md.


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
