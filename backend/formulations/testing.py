"""Test-fixture helper: approve a formulation version without the API.

Since migration 0004 the database refuses components or dosing regimens on a
version that is not a draft, and refuses any change to an approved one. A
fixture that needs an approved version WITH components therefore creates it as
a draft, adds its rows, then calls `approve_for_tests`, which takes it through
draft -> under_review -> approved the way the database allows (stamps set, the
approver neither the creator nor the submitter). Tests only: application code
goes through `formulations.approval`.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.utils import timezone

from .models import FormulationStatus, FormulationVersion


def _fixture_user(email: str):
    from identity.models import User

    user, _ = User.objects.get_or_create(email=email, defaults={"full_name": email.split("@")[0]})
    return user


def approve_for_tests(version: FormulationVersion, note: str = "Approved in a test fixture."):
    now = timezone.now()
    submitter = version.created_by or _fixture_user("fixture-submitter@example.test")
    approver = _fixture_user("fixture-approver@example.test")
    rows = FormulationVersion.objects.filter(pk=version.pk)
    rows.update(status=FormulationStatus.UNDER_REVIEW, submitted_by=submitter, submitted_at=now)
    rows.update(
        status=FormulationStatus.APPROVED, approved_by=approver, approved_at=now, approval_note=note
    )
    version.refresh_from_db()
    return version


@contextmanager
def formulation_guards_off():
    """Tests only: run the statements inside with the database triggers off
    (`session_replication_role = replica`, which needs the superuser role the
    test database has), then switch them back on.

    Older fixtures build an approved version and then add its rows, and some
    tests change an approved version on purpose (for example to prove a cached
    value is re-read). Application code can never do either: the views refuse
    it and the guards (migration 0004) are on for every other statement.
    `formulations/tests/test_version_approval.py` proves the guards refuse the
    same statements without this helper.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SET session_replication_role = replica")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET session_replication_role = DEFAULT")


def create_on_any_version(model, **kwargs):
    """Tests only: create a component or dosing regimen on any version."""
    if model._meta.db_table not in (
        "formulations_formulationcomponent",
        "formulations_dosingregimen",
    ):
        raise ValueError("create_on_any_version is only for components and dosing regimens.")
    with formulation_guards_off():
        return model.objects.create(**kwargs)
