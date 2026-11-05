"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { auth, ApiError } from "@/lib/api";
import AuthLayout from "@/components/auth/AuthLayout";
import { safeReturnTarget } from "@/lib/returnTarget";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await auth.login(email, password);
      if ("mfa_pending" in result && result.mfa_pending) {
        // Enrolled in MFA: the password alone opened no session. The code
        // step at /mfa finishes the sign-in; carry ?next along.
        const next = new URLSearchParams(window.location.search).get("next");
        router.push(next ? `/mfa?next=${encodeURIComponent(next)}` : "/mfa");
        return;
      }
      router.push(safeReturnTarget());
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred.");
      }
    } finally {
      setLoading(false);
    }
  }

  /*
   * Presentation only. The markup keeps every contract the suites rely on:
   * an <h1> matching /sign in/i, labels reading exactly "Email" and
   * "Password", the form's accessible name "Sign in form", role="alert" on
   * the error, and the button label "Sign in" / "Signing in...".
   */
  return (
    <AuthLayout
      title="Sign in to RegX"
      subtitle="Use your organisation account to continue."
      footer={
        <>
          Access is granted by your organisation administrator.
          <br />
          Need an account? <a href="/ratools/requestdemo">Request access</a>
        </>
      }
    >
      <form onSubmit={handleSubmit} aria-label="Sign in form">
        {/* Rendered above the fields so it is adjacent to the control that
            failed, and announced before the user re-reaches the inputs. */}
        {error && (
          <p role="alert" className="regx-auth__error">
            {error}
          </p>
        )}

        <div className="regx-auth__field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@company.com"
            disabled={loading}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="regx-auth__field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="••••••••"
            disabled={loading}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button type="submit" className="regx-auth__button" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </AuthLayout>
  );
}
