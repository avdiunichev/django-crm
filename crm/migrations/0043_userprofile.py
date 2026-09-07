from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_profiles(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL.split(".")[0], settings.AUTH_USER_MODEL.split(".")[1])
    UserProfile = apps.get_model("crm", "UserProfile")
    for user in User.objects.all():
        role = "admin" if user.is_staff or user.is_superuser else "manager"
        UserProfile.objects.get_or_create(
            user=user,
            defaults={"role": role, "can_see_all_records": True},
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm", "0042_contract_terminated_on_payment_terms_debt_limit"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("admin", "Администратор"),
                            ("director", "Руководитель"),
                            ("logistician", "Логист"),
                            ("accountant", "Бухгалтер"),
                            ("manager", "Менеджер"),
                            ("driver", "Водитель / внешний пользователь"),
                        ],
                        default="manager",
                        max_length=20,
                        verbose_name="Роль",
                    ),
                ),
                ("can_see_all_records", models.BooleanField(default=True, verbose_name="Видит все записи")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crm_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "профиль пользователя CRM",
                "verbose_name_plural": "профили пользователей CRM",
            },
        ),
        migrations.RunPython(create_profiles, migrations.RunPython.noop),
    ]
