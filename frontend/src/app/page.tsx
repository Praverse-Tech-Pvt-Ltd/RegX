import Link from "next/link";
import AuthLayout from "@/components/auth/AuthLayout";
import {
  AUTH_STYLESHEETS,
  CompanyStylesheets,
} from "@/components/regx-shell/company-stylesheets";

/**
 * Behind nginx this route never renders -- `/` is proxied to the company site,
 * and the E2E suite asserts exactly that. It is the entry point when the
 * frontend runs standalone on :3000, which is what the dev server and the
 * non-integrated Playwright project use, so it gets the same treatment as the
 * other pre-authentication screens rather than being left as bare markup.
 */
export default function HomePage() {
  return (
    <>
      <CompanyStylesheets sheets={AUTH_STYLESHEETS} />
      <AuthLayout
        title="RegX"
        subtitle="Regulatory workflow management platform."
      >
        <Link href="/signin" className="regx-auth__button">
          Sign in
        </Link>
      </AuthLayout>
    </>
  );
}
