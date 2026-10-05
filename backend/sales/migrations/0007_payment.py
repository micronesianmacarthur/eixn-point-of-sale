from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0006_session_cash_count_breakdown'),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('payment_type', models.CharField(choices=[('CASH', 'Cash'), ('CARD', 'Card'), ('STORE_CREDIT', 'Store Credit'), ('OWNER_DRAW', 'Owner Draw')], max_length=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('transaction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='sales.transaction')),
            ],
            options={
                'ordering': ['payment_type'],
            },
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(fields=('transaction', 'payment_type'), name='unique_payment_type_per_transaction'),
        ),
    ]