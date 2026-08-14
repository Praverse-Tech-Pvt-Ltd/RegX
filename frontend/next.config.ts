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
// The company design system, which the REGX operational shell reuses
// verbatim, names its typefaces literally ("DM Sans" / "Inter" / "Syne") and
// the company site itself loads them from Google Fonts. Self-hosting via
// next/font would rewrite the family names and drop the whole shell back to
// sans-serif, so the two Google Fonts hosts are allow-listed instead — the
// same two the company navbar already preconnects to. Nothing else is
// relaxed: script-src, connect-src and frame-ancestors are unchanged.
const FONT_STYLE_HOST = "https://fonts.googleapis.com";
const FONT_FILE_HOST = "https://fonts.gstatic.com";

const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  `style-src 'self' 'unsafe-inline' ${FONT_STYLE_HOST}`,
  "img-src 'self' data:",
  `font-src 'self' ${FONT_FILE_HOST}`,
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
