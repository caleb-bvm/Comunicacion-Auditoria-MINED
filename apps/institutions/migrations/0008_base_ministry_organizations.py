from django.db import migrations

# Previous reports without a registered institution are archived under DAI-MINED, and
# departmental audits are matched by these codes, so every environment needs them.
DEPARTMENTS = [
    ("AHUACHAPAN", "Ahuachapán"), ("SANTA-ANA", "Santa Ana"), ("SONSONATE", "Sonsonate"),
    ("CHALATENANGO", "Chalatenango"), ("LA-LIBERTAD", "La Libertad"), ("SAN-SALVADOR", "San Salvador"),
    ("CUSCATLAN", "Cuscatlán"), ("LA-PAZ", "La Paz"), ("CABANAS", "Cabañas"),
    ("SAN-VICENTE", "San Vicente"), ("USULUTAN", "Usulután"), ("SAN-MIGUEL", "San Miguel"),
    ("MORAZAN", "Morazán"), ("LA-UNION", "La Unión"),
]


def create_base_organizations(apps, schema_editor):
    Organization = apps.get_model("institutions", "Organization")
    # Existing records keep their data: only missing codes are created.
    Organization.objects.get_or_create(code="DAI-MINED", defaults={
        "name": "Dirección de Auditoría Interna", "kind": "ministry_unit", "department": "San Salvador",
    })
    for suffix, department in DEPARTMENTS:
        Organization.objects.get_or_create(code=f"DDE-{suffix}", defaults={
            "name": f"Dirección Departamental de Educación de {department}",
            "kind": "departmental_office", "department": department,
        })


class Migration(migrations.Migration):
    dependencies = [("institutions", "0007_organization_coordinates")]

    operations = [
        migrations.RunPython(create_base_organizations, migrations.RunPython.noop),
    ]
