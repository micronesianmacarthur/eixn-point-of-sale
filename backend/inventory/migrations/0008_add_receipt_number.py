from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0007_add_owner_fields_to_receipt'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryreceipt',
            name='receipt_number',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
