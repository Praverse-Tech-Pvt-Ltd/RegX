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
