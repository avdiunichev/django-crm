from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0039_bankstatementline_payment_reference_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="driver",
            name="license_categories",
            field=models.CharField(
                help_text="Например: B, C, CE",
                max_length=100,
                verbose_name="Категории",
            ),
        ),
        migrations.AlterField(
            model_name="driverlicense",
            name="categories",
            field=models.CharField(
                help_text="Например: B, C, CE",
                max_length=100,
                verbose_name="Категории",
            ),
        ),
    ]
