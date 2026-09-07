import re

from django.db import migrations, models


def normalize_organization_tax_ids(apps, schema_editor):
    Organization = apps.get_model("crm", "Organization")
    seen = {}
    for organization in Organization.objects.exclude(tax_id="").order_by("pk"):
        normalized = re.sub(r"\D", "", organization.tax_id or "")
        if not normalized:
            normalized = ""
        if normalized in seen:
            raise RuntimeError(
                "Нельзя включить уникальность ИНН: у контрагентов "
                f"№{seen[normalized]} и №{organization.pk} одинаковый ИНН {normalized}."
            )
        if normalized:
            seen[normalized] = organization.pk
        if organization.tax_id != normalized:
            Organization.objects.filter(pk=organization.pk).update(tax_id=normalized)


class Migration(migrations.Migration):
    dependencies = [("crm", "0017_organization_profit_tax_rate")]

    operations = [
        migrations.RunPython(normalize_organization_tax_ids, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.UniqueConstraint(
                condition=~models.Q(tax_id=""),
                fields=("tax_id",),
                name="unique_nonempty_organization_tax_id",
            ),
        ),
    ]
