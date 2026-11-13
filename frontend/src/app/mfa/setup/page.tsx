"use client";

import { useState, type FormEvent } from "react";
import { mfa, ApiError } from "@/lib/api";
import AuthLayout from "@/components/auth/AuthLayout";

/**
 * MFA enrolment for a signed-in user (mandatory for Reviewer, VP, Tenant Admin and
 * Platform Support, SOW 4.3; backend setting REGX_MFA_REQUIRED_ROLES).
 *
 * 1. "Start setup" asks the backend for a new authenticator key and 10
 *    single-use recovery codes. They are shown once and kept only in this
 *    page's memory; nothing is written to browser storage.
 * 2. The user adds the key to an authenticator app (manual entry; no QR code
 *    library is bundled) and types the current 6-digit code.
 * 3. A valid code activates MFA. The current session continues; the next
 *    sign-in asks for a code after the password.
 */
export default function MfaSetupPage() {
  const [secret, setSecret] = useState<string | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function start() {
    setError(null);
    setLoading(true);
    try {
      const res = await mfa.setup();
      setUri(res.totp_uri);
      setSecret(new URL(res.totp_uri).searchParams.get("secret"));
      setRecoveryCodes(res.recovery_codes);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDone(true);
      } else if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setError("Sign in first, then come back to this page.");
      } else {
        setError(err instanceof ApiError ? err.message : "Could not start MFA setup.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await mfa.verify(code);
      setDone(true);
      setSecret(null);
      setUri(null);
      setRecoveryCodes([]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verification failed.");
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <AuthLayout title="Two-step sign-in is on" subtitle="MFA is active for your account.">
        <p>From your next sign-in, you will be asked for a code from your authenticator app.</p>
        <p>
          <a href="/dashboard">Continue to the dashboard</a>
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Set up two-step sign-in"
      subtitle="Required for Reviewer, VP, Tenant Admin and Platform Support. Optional for everyone else."
    >
      {error && (
        <p role="alert" className="regx-auth__error">
          {error}
        </p>
      )}

      {!secret ? (
        <button type="button" className="regx-auth__button" onClick={start} disabled={loading}>
          {loading ? "Starting..." : "Start setup"}
        </button>
      ) : (
        <form onSubmit={verify} aria-label="MFA enrolment form">
          <p>
            1. In your authenticator app, add an account by entering this key
            manually (time-based):
          </p>
          <p>
            <code data-testid="mfa-secret" style={{ wordBreak: "break-all" }}>
              {secret}
            </code>
          </p>
          {uri && (
            <p>
              On a phone, you can instead <a href={uri}>open the key in your authenticator app</a>.
            </p>
          )}
          <p>
            2. Save these recovery codes somewhere safe. Each works once if you
            lose your device. They will not be shown again.
          </p>
          <ul data-testid="mfa-recovery-codes">
            {recoveryCodes.map((c) => (
              <li key={c}>
                <code>{c}</code>
              </li>
            ))}
          </ul>
          <div className="regx-auth__field regx-auth__field--otp">
            <label htmlFor="otp">3. Enter the 6-digit code from the app</label>
            <input
              id="otp"
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              autoComplete="one-time-code"
              required
              placeholder="000000"
              disabled={loading}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <button type="submit" className="regx-auth__button" disabled={loading}>
            {loading ? "Verifying..." : "Turn on MFA"}
          </button>
        </form>
      )}
    </AuthLayout>
  );
}
