from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0041_transportationelectronicdocument_generated_xml"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="terminated_on",
            field=models.DateField(
                blank=True, null=True, verbose_name="Дата расторжения"
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="payment_terms",
            field=models.TextField(blank=True, verbose_name="Условия оплаты"),
        ),
        migrations.AddField(
            model_name="contract",
            name="debt_limit",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=14,
                validators=[MinValueValidator(Decimal("0"))],
                verbose_name="Лимит задолженности",
            ),
        ),
    ]
