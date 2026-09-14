from django.db import migrations


def normalize_client_references(apps, schema_editor):
    Transportation = apps.get_model("crm", "Transportation")

    for transportation in Transportation.objects.filter(
        source_order__isnull=False
    ).select_related("source_order"):
        order = transportation.source_order
        expected_reference = f"{order.number} от {order.document_date:%d.%m.%Y}"
        if transportation.client_reference in ("", order.number):
            Transportation.objects.filter(pk=transportation.pk).update(
                client_reference=expected_reference
            )


class Migration(migrations.Migration):
    dependencies = [("crm", "0061_transportation_customer_payment_terms")]

    operations = [
        migrations.RunPython(normalize_client_references, migrations.RunPython.noop),
    ]
