from django.db import migrations, models

CREATE_IMMUTABLE_TRIGGER = """
CREATE OR REPLACE FUNCTION audit_prevent_update_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_event rows are immutable: UPDATE and DELETE are forbidden.';
END;
$$;

CREATE TRIGGER no_update_audit_event
BEFORE UPDATE ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION audit_prevent_update_delete();

CREATE TRIGGER no_delete_audit_event
BEFORE DELETE ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION audit_prevent_update_delete();
"""

DROP_IMMUTABLE_TRIGGER = """
DROP TRIGGER IF EXISTS no_update_audit_event ON audit_auditevent;
DROP TRIGGER IF EXISTS no_delete_audit_event ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_prevent_update_delete();
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("actor_id", models.BigIntegerField(null=True, blank=True)),
                ("actor_email", models.EmailField(blank=True)),
                ("tenant_id", models.BigIntegerField(null=True, blank=True)),
                ("event_type", models.CharField(max_length=100, db_index=True)),
                ("resource_type", models.CharField(max_length=100, blank=True)),
                ("resource_id", models.CharField(max_length=100, blank=True)),
                ("payload", models.JSONField(default=dict)),
                ("ip_address", models.GenericIPAddressField(null=True, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Audit Event",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunSQL(
            sql=CREATE_IMMUTABLE_TRIGGER,
            reverse_sql=DROP_IMMUTABLE_TRIGGER,
        ),
    ]
