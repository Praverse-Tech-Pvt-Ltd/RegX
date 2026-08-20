import {
  AUTH_STYLESHEETS,
  CompanyStylesheets,
} from "@/components/regx-shell/company-stylesheets";

/**
 * Why this file exists.
 *
 * The company design system was only ever loaded by `(regx)/layout.tsx`.
 * /signin is a sibling of that route group, not a child, so it inherited
 * nothing but the two-line reset in globals.css and rendered with default
 * browser inputs and buttons.
 *
 * A layout here delivers the same sheets to the same URL. The page is not
 * moved into a route group, deliberately: `tests/unit/accessibility.test.tsx`
 * imports `@/app/signin/page` by path, and relocating the file would break
 * that import for a purely cosmetic tidy.
 */
export default function SignInLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <CompanyStylesheets sheets={AUTH_STYLESHEETS} />
      {children}
    </>
  );
}
