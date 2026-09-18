from django.db import migrations, models
import django.core.validators
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [("institutions", "0006_organization_email")]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=9,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("-90")),
                    django.core.validators.MaxValueValidator(Decimal("90")),
                ],
                verbose_name="latitud",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=7,
                max_digits=10,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("-180")),
                    django.core.validators.MaxValueValidator(Decimal("180")),
                ],
                verbose_name="longitud",
            ),
        ),
    ]
