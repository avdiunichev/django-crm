from django.db import migrations


def correct_status(apps, schema_editor):
    Transportation = apps.get_model("crm", "Transportation")
    Transportation.objects.filter(
        legacy_shipment__status="planned",
        status="vehicle_confirmed",
    ).update(status="executor_selected")


class Migration(migrations.Migration):
    dependencies = [("crm", "0011_backfill_organizations_and_transportations")]

    operations = [migrations.RunPython(correct_status, migrations.RunPython.noop)]
