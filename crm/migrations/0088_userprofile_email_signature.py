from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crm", "0087_mailboxconnection_encrypted_app_password")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="email_signature",
            field=models.TextField(blank=True, verbose_name="Подпись для электронной почты"),
        ),
    ]
