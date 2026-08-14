import RegxShell from "@/components/regx-shell/RegxShell";

/**
 * Route-group layout for the REGX operational modules.
 *
 * `(regx)` is a Next.js route group, so it wraps these pages in the company
 * shell WITHOUT changing any URL: /documents stays /documents. That keeps
 * every existing link, API call and E2E selector valid while the pages gain
 * the original /ratools/ chrome.
 *
 * The stylesheets are <link>ed rather than imported so their order is
 * explicit and byte-for-byte the order RAToolsBase.html uses. Bundled CSS
 * imports are emitted in module-graph order, which is not guaranteed to keep
 * a 743 KB theme ahead of the shell overrides that are meant to win.
 *
 * They are served from /company/ (the frontend's own public dir) rather than
 * from the company site's /static/, so these pages render correctly both
 * behind nginx and standalone on :3000 — which is what the dev server and the
 * Playwright suite use.
 */

const COMPANY_STYLESHEETS = [
  "/company/vendors/mdi/css/materialdesignicons.min.css",
  "/company/vendors/ti-icons/css/themify-icons.css",
  "/company/vendors/css/vendor.bundle.base.css",
  "/company/vendors/font-awesome/css/font-awesome.min.css",
  "/company/css/style.css",
  "/company/regx/company-navbar.css",
  "/company/regx/regx-shell.css",
];

export default function RegxAreaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      {COMPANY_STYLESHEETS.map((href) => (
        <link rel="stylesheet" href={href} key={href} />
      ))}
      <RegxShell>{children}</RegxShell>
    </>
  );
}
