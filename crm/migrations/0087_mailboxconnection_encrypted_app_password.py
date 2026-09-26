from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crm", "0086_mailboxconnection")]

    operations = [
        migrations.AddField(
            model_name="mailboxconnection",
            name="encrypted_app_password",
            field=models.TextField(blank=True, verbose_name="Пароль приложения (зашифрован)"),
        ),
    ]
