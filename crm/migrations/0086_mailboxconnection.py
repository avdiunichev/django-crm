# Generated manually to introduce personal VK WorkSpace mailbox metadata.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0085_refresh_vat_rates_2026"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailboxConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("provider", models.CharField(choices=[("vk_workspace", "VK WorkSpace")], default="vk_workspace", max_length=32, verbose_name="Почтовый сервис")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="Адрес ящика")),
                ("is_connected", models.BooleanField(default=False, verbose_name="Подключена")),
                ("connected_at", models.DateTimeField(blank=True, null=True, verbose_name="Подключена")),
                ("last_synced_at", models.DateTimeField(blank=True, null=True, verbose_name="Последняя синхронизация")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="mailbox_connection", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={"verbose_name": "подключение почты", "verbose_name_plural": "подключения почты"},
        ),
    ]
