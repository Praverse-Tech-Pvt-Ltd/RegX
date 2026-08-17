"""Create a LOCAL-ONLY demo login for the company site.

The committed db.sqlite3 seed deliberately contains no usable credential:
every user row carries an unusable password (see
docs/COMPANY_SEED_SANITIZATION.md). Nothing in the integration test suite
needs to log in — the company pages we verify are public — so there is no
demo account in the repository at all.

When a developer does need to click through an authenticated company screen
locally, this command mints one from environment variables, so no password is
ever written down in the repository:

    COMPANY_DEMO_EMAIL=dev@example.invalid \
    COMPANY_DEMO_PASSWORD='<a password you choose>' \
    docker compose exec company_site python manage.py create_demo_user

There is no default password and no fallback. The command refuses to run
without both variables, and refuses to run against a non-DEBUG deployment
unless explicitly forced, so it cannot quietly create a usable account in an
environment that is serving real traffic.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from AdminMaster.models import CustomUser

import os

MIN_PASSWORD_LENGTH = 12


class Command(BaseCommand):
    help = "Create or update a local-only demo user from COMPANY_DEMO_EMAIL / COMPANY_DEMO_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-non-debug",
            action="store_true",
            help=(
                "Permit creation when DEBUG is False. Intended for an isolated "
                "demo host, never for an environment serving real users."
            ),
        )
        parser.add_argument(
            "--role",
            default="company_user",
            help="Role to assign (default: company_user). Use admin only if you need the admin screens.",
        )

    def handle(self, *args, **options):
        email = (os.environ.get("COMPANY_DEMO_EMAIL") or "").strip()
        password = os.environ.get("COMPANY_DEMO_PASSWORD") or ""

        if not email or not password:
            raise CommandError(
                "COMPANY_DEMO_EMAIL and COMPANY_DEMO_PASSWORD must both be set. "
                "This command has no default credential by design."
            )

        if len(password) < MIN_PASSWORD_LENGTH:
            raise CommandError(
                f"COMPANY_DEMO_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters."
            )

        if not settings.DEBUG and not options["allow_non_debug"]:
            raise CommandError(
                "Refusing to create a demo login while DEBUG is False. "
                "Pass --allow-non-debug only on an isolated demo host."
            )

        # username is the login field on this model (CustomUser extends
        # AbstractUser without overriding USERNAME_FIELD), so derive a stable
        # one from the address rather than inventing a second identity.
        username = email.split("@")[0][:150] or "demo"

        with transaction.atomic():
            user, created = CustomUser.objects.get_or_create(
                username=username,
                defaults={"email": email, "role": options["role"], "is_active": True},
            )
            user.email = email
            user.role = options["role"]
            user.is_active = True
            user.set_password(password)
            user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} local demo user "
                f"'{username}' (role={options['role']}). "
                "This account exists only in your local database — never commit it."
            )
        )
