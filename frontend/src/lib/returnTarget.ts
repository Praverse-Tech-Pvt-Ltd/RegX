/**
 * Where to land after a successful sign-in (password step, or the MFA code
 * step that follows it for an enrolled user).
 *
 * Operational pages append ?next=<path> when they bounce an unauthenticated
 * visitor to /signin, so the user returns to the page they actually asked for
 * instead of always being dropped on the tenant picker.
 *
 * Read from window.location rather than useSearchParams: the auth pages are
 * statically prerendered, and the hook would force a Suspense boundary and a
 * dynamic render for what is a one-line lookup inside a submit handler.
 *
 * Only same-origin absolute paths are honoured. A value that does not start
 * with "/", or that starts with "//" or "/\" (both of which browsers treat as
 * protocol-relative and would send the user to another host), is discarded —
 * otherwise this is an open redirect hanging off the login screen. Bouncing
 * back to /signin or /mfa is also refused, to avoid a loop.
 */
export function safeReturnTarget(): string {
  const fallback = "/tenants";
  if (typeof window === "undefined") return fallback;
  const raw = new URLSearchParams(window.location.search).get("next");
  if (!raw) return fallback;
  if (!raw.startsWith("/")) return fallback;
  if (raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  if (raw === "/signin" || raw.startsWith("/signin?")) return fallback;
  if (raw === "/mfa" || raw.startsWith("/mfa?")) return fallback;
  return raw;
}
