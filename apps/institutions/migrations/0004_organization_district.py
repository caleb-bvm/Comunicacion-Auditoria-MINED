from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institutions", "0003_alter_schoolboardmember_identity_document"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="district",
            field=models.CharField(blank=True, max_length=100, verbose_name="distrito"),
        ),
    ]
