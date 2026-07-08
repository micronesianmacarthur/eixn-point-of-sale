from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '__first__'),
        ('inventory', '0006_alter_inventoryreceiptitem_product'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryreceipt',
            name='owner_contribution_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14),
        ),
        migrations.AddField(
            model_name='inventoryreceipt',
            name='owner_customer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='receipts', to='customers.customer'),
        ),
    ]
