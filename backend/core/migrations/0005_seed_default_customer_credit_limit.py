from django.db import migrations


def seed_default_customer_credit_limit(apps, schema_editor):
    SystemSetting = apps.get_model('core', 'SystemSetting')
    SystemSetting.objects.get_or_create(
        key='DEFAULT_CUSTOMER_CREDIT_LIMIT',
        defaults={
            'value': '0.00',
            'description': 'Default credit limit assigned to new customers (set to 0 to disable credit by default)',
        },
    )


def reverse(apps, schema_editor):
    SystemSetting = apps.get_model('core', 'SystemSetting')
    SystemSetting.objects.filter(key='DEFAULT_CUSTOMER_CREDIT_LIMIT').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_seed_session_timeout_settings'),
    ]

    operations = [
        migrations.RunPython(seed_default_customer_credit_limit, reverse),
    ]
