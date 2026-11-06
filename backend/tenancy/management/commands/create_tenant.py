"""Create a tenant. Platform operators only: self-service creation is disabled.

    python manage.py create_tenant --slug acme --name "Acme Pharma"

Creates the tenant with no members. Add people with `create_tenant_user`.
"""

from django.core.management.base import BaseCommand, CommandError

from tenancy.serializers import TenantCreateSerializer


class Command(BaseCommand):
    help = "Create a tenant (platform operators only)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)

    def handle(self, *args, **options):
        s = TenantCreateSerializer(data={"slug": options["slug"], "name": options["name"]})
        if not s.is_valid():
            problems = "; ".join(f"{f}: {' '.join(map(str, e))}" for f, e in s.errors.items())
            raise CommandError(f"Tenant not created. {problems}")
        tenant = s.save()
        self.stdout.write(self.style.SUCCESS(f"Created tenant {tenant.slug} ({tenant.public_id})."))
