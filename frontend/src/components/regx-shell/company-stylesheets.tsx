/**
 * The company design system, as a single ordered list.
 *
 * This used to live inline in `(regx)/layout.tsx`, which meant the
 * authenticated area was styled and the sign-in and MFA pages -- siblings of
 * that route group rather than children of it -- inherited nothing but the
 * two-line reset in `globals.css` and rendered as raw browser HTML.
 *
 * One exported list, imported by every layout that needs the design system,
 * so the two can no longer drift apart.
 *
 * The stylesheets are <link>ed rather than imported so their order is
 * explicit and byte-for-byte the order RAToolsBase.html uses. Bundled CSS
 * imports are emitted in module-graph order, which is not guaranteed to keep
 * a 743 KB theme ahead of the shell overrides that are meant to win.
 *
 * They are served from /regx-shell/ (the frontend's own public dir) rather
 * than from the company site's /static/, so these pages render correctly both
 * behind nginx and standalone on :3000 -- which is what the dev server and the
 * Playwright suite use.
 */
export const COMPANY_STYLESHEETS = [
  "/regx-shell/vendors/mdi/css/materialdesignicons.min.css",
  "/regx-shell/vendors/ti-icons/css/themify-icons.css",
  "/regx-shell/vendors/css/vendor.bundle.base.css",
  "/regx-shell/vendors/font-awesome/css/font-awesome.min.css",
  "/regx-shell/css/style.css",
  "/regx-shell/regx/regx-shell.css",
  // Last on purpose. In RAToolsBase.html the navbar's <style> block arrives
  // later in the document than the template's own, because navbar.html is
  // included inside <body> -- so its `body { font-family: 'Inter' }` beats the
  // head block's DM Sans. Loading these the other way round made /documents
  // render in DM Sans while /ratools/ rendered in Inter, a visible drift
  // between two pages that sit next to each other in the same shell.
  "/regx-shell/regx/company-navbar.css",
];

/**
 * The unauthenticated pages additionally load the auth sheet, which styles the
 * sign-in and MFA screens using the same tokens the shell already defines. It
 * comes last so it can override the 743 KB theme where the two disagree.
 */
export const AUTH_STYLESHEETS = [
  ...COMPANY_STYLESHEETS,
  "/regx-shell/regx/regx-auth.css",
];

export function CompanyStylesheets({ sheets }: { sheets: string[] }) {
  return (
    <>
      {sheets.map((href) => (
        <link rel="stylesheet" href={href} key={href} />
      ))}
    </>
  );
}
