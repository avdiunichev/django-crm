from django.db import migrations


def merge_counts(apps, schema_editor):
    Transportation = apps.get_model("crm", "Transportation")
    TransportOrder = apps.get_model("crm", "TransportOrder")
    for model in (Transportation, TransportOrder):
        for item in model.objects.exclude(pallet_count__isnull=True).iterator():
            item.package_count = (item.package_count or 0) + (item.pallet_count or 0)
            item.pallet_count = None
            item.save(update_fields=["package_count", "pallet_count", "updated_at"])


def reverse_merge_counts(apps, schema_editor):
    # Обратное разделение невозможно без потери смысла: после объединения система
    # хранит одно количество грузовых мест.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0050_transportation_business_statuses"),
    ]

    operations = [
        migrations.RunPython(merge_counts, reverse_merge_counts),
    ]
