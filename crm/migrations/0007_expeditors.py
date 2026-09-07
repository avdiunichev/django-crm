import django.db.models.deletion
from django.db import migrations, models


def assign_existing_shipments(apps, schema_editor):
    CompanyProfile = apps.get_model("crm", "CompanyProfile")
    Shipment = apps.get_model("crm", "Shipment")
    if not Shipment.objects.filter(expeditor__isnull=True).exists():
        return
    expeditor = CompanyProfile.objects.order_by("pk").first()
    if expeditor is None:
        expeditor = CompanyProfile.objects.create(
            name="Экспедитор",
            short_name="Экспедитор",
            tax_id="не указан",
            legal_address="не указан",
        )
    Shipment.objects.filter(expeditor__isnull=True).update(expeditor=expeditor)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0006_companyprofile_customer_kpp"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="companyprofile",
            options={
                "ordering": ("name",),
                "verbose_name": "экспедитор",
                "verbose_name_plural": "экспедиторы",
            },
        ),
        migrations.AddField(
            model_name="companyprofile",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="Активен"),
        ),
        migrations.AddField(
            model_name="shipment",
            name="expeditor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shipments",
                to="crm.companyprofile",
                verbose_name="Экспедитор",
            ),
        ),
        migrations.RunPython(assign_existing_shipments, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="shipment",
            name="expeditor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shipments",
                to="crm.companyprofile",
                verbose_name="Экспедитор",
            ),
        ),
    ]
