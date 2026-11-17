"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { tenants } from "@/lib/api";
import CompanyNavbar from "./CompanyNavbar";
import RegxSidebar from "./RegxSidebar";
import MfaEnrolmentBanner from "./MfaEnrolmentBanner";

/**
 * The company /ratools/ shell, reproduced for the REGX operational pages.
 *
 * The element tree mirrors the <body> of
 * company_site/templates/RATools/RAToolsBase.html:
 *
 *   .tt-shell
 *     navbar.html                                  -> <CompanyNavbar/>
 *     .container-fluid.page-body-wrapper
 *      .dashboard-page-body.dashboard-layout       -> collapse target
 *       nav.dashboard-sidebar                      -> <RegxSidebar/>
 *       .main-panel.dashboard-main-panel
 *         .content-wrapper                         -> {children}
 *
 * The inline styles below are copied from the template rather than moved into
 * a stylesheet, because the collapsed rules in regx-shell.css override them
 * with !important exactly as they do in the original — reproducing the same
 * cascade is what makes the 270px -> 96px transition behave identically.
 *
 * Per Phase 10 the marketing hero is deliberately absent here: it belongs to
 * the /ratools/ landing, which the company site still renders itself.
 */
/**
 * The sidebar with the current tenant taken from the URL. `useSearchParams`
 * must sit under a Suspense boundary or Next.js refuses to prerender the
 * page, so the shell renders this inside one, with a tenant-less sidebar as
 * the fallback.
 */
function TenantSidebar(props: { collapsed: boolean; onToggle: () => void }) {
  const tenantSlug = useSearchParams()?.get("tenant") ?? "";
  return <RegxSidebar {...props} tenantSlug={tenantSlug} />;
}

type Access = { slug: string; state: "checking" | "member" | "refused" | "unknown" };

/**
 * Refuses, in the page, an organisation the user does not belong to.
 *
 * Every REGX page sends `?tenant=` as X-Tenant-Slug, and the backend refuses a
 * non-member with 403 (tenancy/middleware.py) -- that is the enforcement. But
 * most pages treat any 403 as "signed out" and redirect to /signin, so a user
 * who edited ?tenant= to another organisation landed on the sign-in page with
 * no explanation. This checks the slug against the user's own organisations
 * (GET /tenants/, memberships only) and, for a slug that is not theirs, shows
 * the refusal and never mounts the page, so the page makes no data request.
 *
 * Fails open to the previous behaviour when the list cannot be read (signed
 * out, network error, or anything that is not the endpoint's array): the
 * backend still refuses, and the page handles sign-in as before.
 */
function TenantGate({ children }: { children: React.ReactNode }) {
  const slug = useSearchParams()?.get("tenant") ?? "";
  const [access, setAccess] = useState<Access>({ slug: "", state: "unknown" });

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setAccess({ slug, state: "checking" });
    tenants
      .list()
      .then((list: unknown) => {
        if (cancelled) return;
        if (!Array.isArray(list)) {
          setAccess({ slug, state: "unknown" });
          return;
        }
        const member = list.some((t) => (t as { slug?: unknown })?.slug === slug);
        setAccess({ slug, state: member ? "member" : "refused" });
      })
      .catch(() => {
        if (!cancelled) setAccess({ slug, state: "unknown" });
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (!slug) return <>{children}</>;
  if (access.slug !== slug || access.state === "checking") {
    return (
      <p role="status" style={{ margin: "2rem auto", maxWidth: 800, padding: "0 1rem" }}>
        Checking access…
      </p>
    );
  }
  if (access.state === "refused") {
    return (
      <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
        <h1>No access to this organisation</h1>
        <p role="alert">
          You are not a member of the organisation &ldquo;{slug}&rdquo;. Nothing from it
          has been loaded.
        </p>
        <p>
          <Link href="/tenants">Choose one of your organisations</Link>
        </p>
      </main>
    );
  }
  return <>{children}</>;
}

export default function RegxShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="tt-shell">
      <CompanyNavbar />

      <div
        className={`container-fluid page-body-wrapper dashboard-page-body dashboard-layout${
          collapsed ? " sidebar-collapsed" : ""
        }`}
        id="dashboardLayout"
      >
        <Suspense
          fallback={
            <RegxSidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
          }
        >
          <TenantSidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
        </Suspense>

        <div
          className="main-panel dashboard-main-panel"
          style={{
            marginLeft: "270px",
            transition: "margin-left 0.3s ease, width 0.3s ease",
          }}
        >
          <div
            className="content-wrapper"
            style={{
              padding: 0,
              background: "transparent",
              display: "flex",
              flexDirection: "column",
              minHeight: "calc(100vh - 70px)",
              flexGrow: 1,
            }}
          >
            <MfaEnrolmentBanner />
            <Suspense
              fallback={
                <p role="status" style={{ margin: "2rem auto", maxWidth: 800, padding: "0 1rem" }}>
                  Checking access…
                </p>
              }
            >
              <TenantGate>{children}</TenantGate>
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  );
}
