"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { auth, ApiError } from "@/lib/api";
import AuthLayout from "@/components/auth/AuthLayout";
import { safeReturnTarget } from "@/lib/returnTarget";

export default function MFAPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // Second sign-in step: the password step at /signin left a pending
      // login; a valid code turns it into a session.
      await auth.loginMfa(code);
      router.push(safeReturnTarget());
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Verification failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  /*
   * Presentation only. The heading text, the "OTP Code" label, the form's
   * accessible name, role="alert", the numeric pattern and the button labels
   * are all unchanged -- only the surrounding markup and classes are new.
   */
  return (
    <AuthLayout
      title="Two-factor authentication"
      subtitle="Enter the 6-digit code from your authenticator app."
    >
      <form onSubmit={handleVerify} aria-label="MFA verification form">
        {error && (
          <p role="alert" className="regx-auth__error">
            {error}
          </p>
        )}

        <div className="regx-auth__field regx-auth__field--otp">
          <label htmlFor="otp">OTP Code</label>
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
          {loading ? "Verifying..." : "Verify"}
        </button>
      </form>
    </AuthLayout>
  );
}
