"""QA-09 (MFA): spending a recovery code and its audit record commit together.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL. On the old code the code was spent by an autocommit UPDATE before the
audit write, so a failed audit left the code used with no record of who used it.
(The admin MFA reset already wrote its record inside its transaction.)
"""

from __future__ import annotations

import pytest

from audit.testing import attempt, audit_writes_fail
from identity.models import RecoveryCode

from .test_mfa_recovery import (  # noqa: F401
    LOGIN_MFA,
    _clean_cache,
    _enrol,
    _password_step,
    make_member,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_recovery_code_is_not_spent_without_its_audit(make_member):  # noqa: F811
    user = make_member("qa09-recovery@example.test", "doer")
    codes = _enrol(user)
    client = _password_step(user.email)
    with audit_writes_fail():
        attempt(client.post, LOGIN_MFA, {"recovery_code": codes[0]}, format="json")
    assert RecoveryCode.objects.filter(device__user=user, used_at__isnull=True).count() == 10
