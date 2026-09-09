"""Create one admin and one regular user for the company_site app.

Both need an `AssignChecker` row: several views call
`AssignChecker.objects.get(user=...)` with no `try/except` and return 500
without one. That is why the row is created here rather than left to the admin UI.

`internal_team` is left False. It bypasses the production device-token lock in
`AdminMaster.views.login`, and a demo account should not carry that.

    docker compose exec -T company_site python create_demo_users.py
"""

import datetime
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "RAAI.settings_integration")
django.setup()

from django.db import transaction  # noqa: E402

from AdminMaster.models import AssignChecker, CustomUser  # noqa: E402

ADMIN_PASSWORD = "RegxAdmin#2026"
USER_PASSWORD = "RegxUser#2026"

ALL_REPORTS = [choice[0] for choice in AssignChecker.REPORT_CHOICES]
ALL_SAMPLES = [choice[0] for choice in AssignChecker.VIEW_SAMPLE_CHOICES]


def make(username, role, password, staff=False):
    user, _ = CustomUser.objects.get_or_create(username=username)
    user.role = role
    user.set_password(password)
    user.is_active = True
    user.is_staff = staff
    user.is_superuser = staff
    user.internal_team = False
    user.subscription_end_date = datetime.date(2030, 12, 31)
    user.fda_deficiency_database = True
    user.complete_response_database = True
    user.company_name = "Praverse Demo"
    user.first_name = username.replace("_", " ").title()
    user.save()

    assignment, _ = AssignChecker.objects.get_or_create(user=user)
    assignment.assigned_report = ALL_REPORTS
    assignment.view_sample_reports = ALL_SAMPLES
    assignment.save()
    return user, assignment


with transaction.atomic():
    admin, admin_assignment = make("regx_admin", "admin", ADMIN_PASSWORD, staff=True)
    doer, doer_assignment = make("regx_user", "company_user", USER_PASSWORD)
    checker, _ = make("regx_checker", "company_checker", USER_PASSWORD)

    # The checker has to be attached to the doer's assignment or submitted work
    # reaches no reviewer.
    for level in range(1, 8):
        getattr(doer_assignment, "assigned_checker_level_%d" % level).add(checker)
    doer_assignment.save()

for user in (admin, doer, checker):
    print(
        "  %-14s role=%-16s reports=%d staff=%s"
        % (
            user.username,
            user.role,
            len(AssignChecker.objects.get(user=user).assigned_report),
            user.is_staff,
        )
    )
