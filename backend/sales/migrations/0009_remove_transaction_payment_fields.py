from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0008_backfill_payments'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='transaction',
            name='payment_type',
        ),
        migrations.RemoveField(
            model_name='transaction',
            name='payment_amount',
        ),
    ]