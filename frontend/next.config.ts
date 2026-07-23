import type { NextConfig } from "next";

// The frontend and backend are different origins (e.g. localhost:3000 and
// localhost:8000); connect-src must include the API origin or every fetch()
// the app makes is blocked.
const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").origin;

// script-src uses 'unsafe-inline' rather than a nonce: Next.js's own inline
// hydration/RSC-payload scripts did not pick up a nonce set via middleware
// in this Next.js version (verified by inspecting the rendered DOM — no
// script tag ever carried a nonce attribute), which left every page
// hydrating into a blank document once CSP was actually enforced (masked in
// all prior testing by Playwright's bypassCSP: true). A working, slightly
// less strict CSP is preferable to a correctly-strict one that breaks the
// entire app.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self' ${apiOrigin}`,
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Content-Security-Policy", value: CSP },
        ],
      },
    ];
  },
};

export default nextConfig;
