from django.db import migrations


def set_admin_staff_status(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(role='ADMIN', is_staff=False).update(
        is_staff=True,
        is_superuser=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_user_pin_code'),
    ]

    operations = [
        migrations.RunPython(set_admin_staff_status, reverse_code=migrations.RunPython.noop),
    ]
