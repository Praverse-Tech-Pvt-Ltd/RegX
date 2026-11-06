"""Which accounts must enrol in MFA before they can act (SOW 4.3).

A user holding the Reviewer or VP role in any active tenant membership must
have a verified MFA device. Until they do, `MFAEnrolmentMiddleware` refuses
their state-changing API requests; reading stays open so they can still see
their work and reach the enrolment screen. Other roles may enrol but need not.

The rule is per account, not per tenant, because the MFA device is per account:
one enrolment satisfies every tenant the person belongs to.
"""

from identity.models import MFADevice

from .models import MembershipRole, Role

#: Roles that cannot act without a verified MFA device.
MFA_REQUIRED_ROLES: frozenset[str] = frozenset({Role.BuiltIn.REVIEWER, Role.BuiltIn.VP})

ERROR_CODE = "mfa_enrolment_required"
ERROR_DETAIL = (
    "Your Reviewer or VP role requires two-step sign-in (MFA). "
    "Set it up at /mfa/setup, then try again."
)


def holds_mfa_required_role(user) -> bool:
    return MembershipRole.objects.filter(
        membership__user=user,
        membership__is_active=True,
        role__name__in=MFA_REQUIRED_ROLES,
    ).exists()


def is_enrolled(user) -> bool:
    return MFADevice.objects.filter(user=user, is_verified=True).exists()


def requires_mfa_enrolment(user) -> bool:
    """True if this account must enrol before it may change anything."""
    if user is None or not user.is_authenticated:
        return False
    return holds_mfa_required_role(user) and not is_enrolled(user)
