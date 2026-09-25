from django.db import migrations, models


def set_authority_documents(apps, schema_editor):
    Organization = apps.get_model("crm", "Organization")
    Organization.objects.filter(kind="entrepreneur").update(
        acting_basis="Лист записи ЕГРИП"
    )
    Organization.objects.exclude(kind="entrepreneur").update(acting_basis="Устав")


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0082_contract_number_by_party_pair"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="acting_basis",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="Документ, подтверждающий полномочия",
            ),
        ),
        migrations.AlterField(
            model_name="organizationrequisitechange",
            name="field_name",
            field=models.CharField(
                choices=[
                    ("kind", "Вид контрагента"),
                    ("short_name", "Наименование"),
                    ("name", "Полное наименование"),
                    ("tax_id", "ИНН"),
                    ("kpp", "КПП"),
                    ("ogrn", "ОГРН / ОГРНИП"),
                    ("registration_date", "Дата регистрации"),
                    ("legal_address", "Юридический адрес"),
                    ("director_position", "Должность руководителя"),
                    ("director_name", "Ф. И. О. руководителя"),
                    ("acting_basis", "Документ, подтверждающий полномочия"),
                ],
                max_length=40,
                verbose_name="Реквизит",
            ),
        ),
        migrations.RunPython(set_authority_documents, migrations.RunPython.noop),
    ]
