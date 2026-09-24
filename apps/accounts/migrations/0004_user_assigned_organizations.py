from django.conf import settings
from django.db import migrations, models


def seed_assignments_from_cases(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    AuditCase = apps.get_model("audits", "AuditCase")
    through = User.assigned_organizations.through
    pairs = AuditCase.objects.order_by().values_list(
        "assigned_auditor_id", "audited_organization_id"
    ).distinct()
    through.objects.bulk_create(
        [through(user_id=user_id, organization_id=organization_id)
         for user_id, organization_id in pairs],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("institutions", "0007_organization_coordinates"),
        ("accounts", "0003_user_activation_requested_at"),
        ("audits", "0006_auditdocument_parent_report_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="assigned_organizations",
            field=models.ManyToManyField(
                blank=True,
                related_name="assigned_auditors",
                to="institutions.organization",
                verbose_name="organizaciones asignadas",
            ),
        ),
        migrations.RunPython(seed_assignments_from_cases, migrations.RunPython.noop),
    ]
