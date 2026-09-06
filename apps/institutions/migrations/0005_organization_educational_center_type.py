from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institutions", "0004_organization_district"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="educational_center_type",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Clasificación específica del catálogo de centros, por ejemplo: "
                    "Centro escolar, Instituto o Complejo educativo."
                ),
                max_length=100,
                verbose_name="tipo de centro educativo",
            ),
        ),
    ]
