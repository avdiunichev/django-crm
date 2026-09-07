from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0040_alter_driver_license_categories_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="transportationelectronicdocument",
            name="generated_xml",
            field=models.TextField(
                blank=True,
                help_text="XML, возвращённый Контур.Диадок после GenerateTitleXml.",
                verbose_name="Итоговый XML титула",
            ),
        ),
    ]
