import {
  AUTH_STYLESHEETS,
  CompanyStylesheets,
} from "@/components/regx-shell/company-stylesheets";

/**
 * /mfa sits outside the `(regx)` route group for the same reason /signin does
 * -- the application shell does not exist until the user is through both
 * screens -- and it was unstyled for the same reason too. Same sheets, so the
 * second step of sign-in looks like the first.
 */
export default function MfaLayout({
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
