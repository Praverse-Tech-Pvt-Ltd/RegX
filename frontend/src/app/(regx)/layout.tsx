import RegxShell from "@/components/regx-shell/RegxShell";
import {
  COMPANY_STYLESHEETS,
  CompanyStylesheets,
} from "@/components/regx-shell/company-stylesheets";

/**
 * Route-group layout for the REGX operational modules.
 *
 * `(regx)` is a Next.js route group, so it wraps these pages in the company
 * shell WITHOUT changing any URL: /documents stays /documents. That keeps
 * every existing link, API call and E2E selector valid while the pages gain
 * the original /ratools/ chrome.
 *
 * The stylesheet list itself now lives in `company-stylesheets.tsx` and is
 * shared with the pre-authentication screens. It was inline here, which is
 * precisely why /signin and /mfa rendered as raw HTML: they are siblings of
 * this route group, so nothing delivered the design system to them.
 */
export default function RegxAreaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <CompanyStylesheets sheets={COMPANY_STYLESHEETS} />
      <RegxShell>{children}</RegxShell>
    </>
  );
}
