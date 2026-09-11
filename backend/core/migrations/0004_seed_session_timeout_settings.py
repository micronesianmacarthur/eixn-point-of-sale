from django.db import migrations


def seed_session_timeout_settings(apps, schema_editor):
    SystemSetting = apps.get_model('core', 'SystemSetting')
    SystemSetting.objects.get_or_create(
        key='SESSION_IDLE_TIMEOUT_ENABLED',
        defaults={
            'value': 'true',
            'description': 'Enable or disable idle session timeout (auto-logout after inactivity)',
        },
    )
    SystemSetting.objects.get_or_create(
        key='SESSION_IDLE_TIMEOUT',
        defaults={
            'value': '300',
            'description': 'Idle session timeout in seconds (1-30 minutes, default 300 = 5 min)',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_businessinfo'),
    ]

    operations = [
        migrations.RunPython(seed_session_timeout_settings),
    ]
