"""Create a user in a tenant with one or more system roles. Platform operators only.

Public self-registration is disabled, so this is how accounts are made:

    NEW_USER_PASSWORD='...' python manage.py create_tenant_user \
        --tenant acme --email reviewer@acme.example --role reviewer \
        --full-name "R. Reviewer" --password-env NEW_USER_PASSWORD

The password is read from the named environment variable, never from the
command line (which would leave it in shell history and process lists), and is
checked against the configured password validators.

If the email already exists, the account and its password are left as they are
and only the membership and roles are added; no password is needed then.
A Reviewer or VP must enrol in MFA at first sign-in before they can act.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from authorization.models import MembershipRole, Role
from tenancy.models import Tenant, TenantMembership

ROLE_NAMES = [choice.value for choice in Role.BuiltIn]


class Command(BaseCommand):
    help = "Create a tenant user with system roles (platform operators only)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant slug.")
        parser.add_argument("--email", required=True)
        parser.add_argument("--role", action="append", required=True, choices=ROLE_NAMES)
        parser.add_argument("--full-name", default="")
        parser.add_argument(
            "--password-env",
            help="Environment variable holding the new user's password (new users only).",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        try:
            tenant = Tenant.objects.get(slug=options["tenant"], status=Tenant.Status.ACTIVE)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"No active tenant {options['tenant']!r}.") from exc

        roles = []
        for name in sorted(set(options["role"])):
            # The platform-wide built-in role (tenant=None, seeded by
            # authorization/seed.py). Some databases also hold tenant-scoped
            # copies of these names; never bind another tenant's role.
            role = Role.objects.filter(name=name, tenant__isnull=True, is_system=True).first()
            if role is None:
                raise CommandError(f"System role {name!r} is missing. Run migrations first.")
            roles.append(role)

        user = get_user_model().objects.filter(email=email).first()
        with transaction.atomic():
            if user is None:
                env = options["password_env"]
                password = os.environ.get(env, "") if env else ""
                if not password:
                    raise CommandError(
                        "A new user needs --password-env naming a set environment variable."
                    )
                try:
                    validate_password(password)
                except ValidationError as exc:
                    raise CommandError("Password rejected: " + " ".join(exc.messages)) from exc
                user = get_user_model().objects.create_user(
                    email=email, password=password, full_name=options["full_name"]
                )
                self.stdout.write(f"Created user {email}.")
            else:
                self.stdout.write(f"User {email} exists; password unchanged.")

            membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
            if not membership.is_active:
                membership.is_active = True
                membership.save(update_fields=["is_active"])
            for role in roles:
                MembershipRole.objects.get_or_create(membership=membership, role=role)

        names = ", ".join(r.name for r in roles)
        self.stdout.write(self.style.SUCCESS(f"{email} in {tenant.slug} with role(s): {names}."))
