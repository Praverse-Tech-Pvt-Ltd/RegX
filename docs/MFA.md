# MFA

## TOTP device

Each user may have one `MFADevice` (TOTP). The TOTP secret is encrypted at rest using Fernet symmetric encryption (`MFA_ENCRYPTION_KEY` env var). The plaintext secret is only accessible via `device.get_secret()` and must never be logged.

## Provisioning flow

1. `POST /api/regx/v1/mfa/setup/` — generates a new secret, returns a provisioning URI (QR code source) and 10 recovery codes.
2. `POST /api/regx/v1/mfa/verify/` — user submits first TOTP code to activate the device.

## Replay prevention

`last_used_counter` stores the 30-second window index of the last accepted OTP. The same window cannot be used twice.

## Lockout

After 5 consecutive failed attempts, the device is locked for 15 minutes.

## Recovery codes

10 single-use codes are generated at provisioning. Codes are stored as SHA-256 hashes; plaintext is shown once. `RecoveryCode.consume()` atomically marks a code as used and returns False if already consumed.

## Who must enrol (SOW 4.3)

**Reviewer, VP, Tenant Admin and Platform Support: mandatory. Everyone else (Doer, users with no role): optional.**

The list is one setting, `REGX_MFA_REQUIRED_ROLES` in `backend/regx/settings/base.py` (Tenant Admin and Platform Support added 2026-11-06, Pratham's direction §10).

- A user holding any of those roles in any active tenant membership, with no *verified* MFA device, can sign in with the password and **read**, but every `POST`/`PUT`/`PATCH`/`DELETE` under `/api/regx/v1/` is refused with **403 `mfa_enrolment_required`** until they enrol. `auth/` (sign in, sign out, CSRF) and `mfa/` (enrol, verify, recovery) stay open so they can.
- Enforced by `authorization.middleware.MFAEnrolmentMiddleware` (rule in `authorization/mfa_policy.py`). It reads the session user, which is the only authentication scheme (`SessionAuthentication`). A test pins that; adding token/JWT auth (e.g. for the Word add-in) must extend the gate.
- The rule is per account, not per tenant: one device covers every tenant. A Doer who is also a Reviewer is gated for all writes.
- `GET /api/regx/v1/permissions/mfa-status/` → `{mfa_enrolled, holds_mfa_required_role, mfa_enrolment_required}`. The app shows a banner when enrolment is required.
- **Enrolment screen: `/mfa/setup`.** Start setup → add the key to an authenticator app (manual entry) and save the 10 recovery codes → enter a code. The current session continues; from the next sign-in the code step (`/mfa`) applies.
- **company_site shared login:** it refuses any account whose REGX login answers `mfa_required` (`company_site/AdminMaster/regx_auth.py`). So once a user with one of these roles enrols, they can no longer sign in to company_site with their REGX password. Before enrolling, they still can, and are mapped to `company_checker` there; the REGX gate does not cover company_site actions.
