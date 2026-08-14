import type { Metadata } from "next";
import "./globals.css";

/*
 * Two Next lint rules are switched off for this file, both deliberately:
 *
 *   no-page-custom-font  — a Pages-Router rule that asks for a
 *     pages/_document.js, which does not exist in the App Router.
 *   google-font-display  — it prefers display=swap or optional. The company
 *     navbar specifies display=block, and swapping it would let the REGX
 *     shell paint in a fallback face before the real one arrives, which is
 *     exactly the visual drift this integration exists to avoid.
 */
/* eslint-disable @next/next/no-page-custom-font, @next/next/google-font-display */

export const metadata: Metadata = {
  title: "RegX",
  description: "Regulatory workflow management",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        {/*
          The company design system names these families literally
          (font-family: "DM Sans" / "Inter" / "Syne"), so they are loaded the
          same way company_site/templates/navbar.html loads them rather than
          through next/font, which would rewrite the family to a hashed name
          and silently drop the shell back to sans-serif.
        */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&family=Syne:wght@600;700;800&display=block"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
