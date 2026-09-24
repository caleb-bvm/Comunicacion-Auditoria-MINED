import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_technicalsupportrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='technicalsupportrequest',
            name='is_public_request',
            field=models.BooleanField(default=False, verbose_name='solicitud pública'),
        ),
        migrations.AddField(
            model_name='technicalsupportrequest',
            name='requester_contact',
            field=models.EmailField(blank=True, max_length=254, verbose_name='correo de contacto indicado'),
        ),
        migrations.AddField(
            model_name='technicalsupportrequest',
            name='requester_identifier',
            field=models.CharField(blank=True, max_length=254, verbose_name='usuario o correo indicado'),
        ),
        migrations.AddField(
            model_name='technicalsupportrequest',
            name='requester_name',
            field=models.CharField(blank=True, max_length=180, verbose_name='nombre del solicitante'),
        ),
        migrations.AddField(
            model_name='technicalsupportrequest',
            name='reset_sent_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='enlace de restablecimiento enviado'),
        ),
        migrations.AlterField(
            model_name='technicalsupportrequest',
            name='category',
            field=models.CharField(choices=[('password_reset', 'Restablecimiento de contraseña'), ('account_reactivation', 'Reactivación de cuenta'), ('close_sessions', 'Cierre de sesiones'), ('access_data', 'Corrección de datos de acceso'), ('technical_error', 'Investigación de error'), ('catalog', 'Corrección o importación de catálogo'), ('other', 'Otro soporte técnico')], max_length=30, verbose_name='tipo'),
        ),
        migrations.AlterField(
            model_name='technicalsupportrequest',
            name='requested_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='requested_technical_support', to=settings.AUTH_USER_MODEL, verbose_name='solicitada por'),
        ),
    ]
