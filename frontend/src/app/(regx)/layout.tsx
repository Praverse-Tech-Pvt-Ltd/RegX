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
 * They are served from /regx-shell/ (the frontend's own public dir) rather than
 * from the company site's /static/, so these pages render correctly both
 * behind nginx and standalone on :3000 — which is what the dev server and the
 * Playwright suite use.
 */

const COMPANY_STYLESHEETS = [
  "/regx-shell/vendors/mdi/css/materialdesignicons.min.css",
  "/regx-shell/vendors/ti-icons/css/themify-icons.css",
  "/regx-shell/vendors/css/vendor.bundle.base.css",
  "/regx-shell/vendors/font-awesome/css/font-awesome.min.css",
  "/regx-shell/css/style.css",
  "/regx-shell/regx/regx-shell.css",
  // Last on purpose. In RAToolsBase.html the navbar's <style> block arrives
  // later in the document than the template's own, because navbar.html is
  // included inside <body> — so its `body { font-family: 'Inter' }` beats the
  // head block's DM Sans. Loading these the other way round made /documents
  // render in DM Sans while /ratools/ rendered in Inter, a visible drift
  // between two pages that sit next to each other in the same shell.
  "/regx-shell/regx/company-navbar.css",
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
