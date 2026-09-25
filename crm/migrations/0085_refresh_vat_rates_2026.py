from datetime import date
from decimal import Decimal

from django.db import migrations


def refresh_vat_rates(apps, schema_editor):
    VATRate = apps.get_model("crm", "VATRate")
    current_rates = (
        ("without_vat", "Без НДС", Decimal("0"), True, None),
        ("0", "НДС 0%", Decimal("0"), False, None),
        ("5", "НДС 5% (УСН)", Decimal("5"), False, date(2025, 1, 1)),
        ("7", "НДС 7% (УСН)", Decimal("7"), False, date(2025, 1, 1)),
        ("10", "НДС 10%", Decimal("10"), False, None),
        ("22", "НДС 22%", Decimal("22"), False, date(2026, 1, 1)),
    )
    for code, name, rate, is_without_vat, valid_from in current_rates:
        VATRate.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "rate": rate,
                "is_without_vat": is_without_vat,
                "is_active": True,
                "valid_from": valid_from,
            },
        )
    VATRate.objects.filter(code="18").update(
        name="НДС 18% (архивная ставка)", is_active=False
    )
    VATRate.objects.filter(code="20").update(
        name="НДС 20% (архивная до 01.01.2026)", is_active=False
    )


class Migration(migrations.Migration):
    dependencies = [("crm", "0084_organization_payment_terms")]

    operations = [migrations.RunPython(refresh_vat_rates, migrations.RunPython.noop)]
