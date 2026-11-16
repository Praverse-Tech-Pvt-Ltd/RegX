import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/*
 * Every REGX page reads its tenant from `?tenant=` and sends the user to
 * /tenants without it. The sidebar dropped the parameter and the organisation
 * list had no links, so after sign-in every sidebar click landed back on
 * "Your organisations".
 */

const nav = vi.hoisted(() => ({ pathname: "/documents", push: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: nav.push, replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: unknown }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

const tenantsApi = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  tenants: tenantsApi,
}));

import RegxSidebar, { withTenant } from "@/components/regx-shell/RegxSidebar";
import TenantsPage from "@/app/(regx)/tenants/page";
import { errorMessage } from "@/lib/api";

beforeEach(() => {
  nav.pathname = "/documents";
});

describe("withTenant", () => {
  it("appends the tenant to a REGX path", () => {
    expect(withTenant("/formulations", "demo")).toBe("/formulations?tenant=demo");
  });

  it("encodes the slug", () => {
    expect(withTenant("/documents", "a b&c")).toBe("/documents?tenant=a%20b%26c");
  });

  it("leaves the path alone when no tenant is selected", () => {
    expect(withTenant("/formulations", "")).toBe("/formulations");
  });

  it("never adds a tenant to /tenants, where one is chosen", () => {
    expect(withTenant("/tenants", "demo")).toBe("/tenants");
  });
});

describe("RegxSidebar", () => {
  it("carries the current tenant on every REGX link", () => {
    render(<RegxSidebar collapsed={false} onToggle={() => {}} tenantSlug="demo" />);
    expect(screen.getByRole("link", { name: "Formulations" })).toHaveAttribute(
      "href",
      "/formulations?tenant=demo",
    );
    expect(screen.getByRole("link", { name: "IID Assessments" })).toHaveAttribute(
      "href",
      "/iid-assessments/preview?tenant=demo",
    );
    // Submenu children too (rendered collapsed, so query the DOM directly).
    const releases = document.querySelector('a[href="/fda-data/releases?tenant=demo"]');
    expect(releases).not.toBeNull();
    const bareRegxLinks = Array.from(document.querySelectorAll("a"))
      .map((a) => a.getAttribute("href") ?? "")
      .filter((h) => h.startsWith("/") && !h.startsWith("/ratools") && h !== "/tenants")
      .filter((h) => !h.endsWith("?tenant=demo"));
    expect(bareRegxLinks).toEqual([]);
  });

  it("keeps legacy company links unchanged: the company site has no tenants", () => {
    render(<RegxSidebar collapsed={false} onToggle={() => {}} tenantSlug="demo" />);
    expect(screen.getByRole("link", { name: "DMF Review Checklist" })).toHaveAttribute(
      "href",
      "/ratools/show_dmf_table",
    );
  });

  it("still marks the active route when links carry the tenant", () => {
    render(<RegxSidebar collapsed={false} onToggle={() => {}} tenantSlug="demo" />);
    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute("aria-current", "page");
  });
});

describe("TenantsPage", () => {
  it("links each organisation into REGX with its tenant set", async () => {
    tenantsApi.list.mockResolvedValue([
      { id: "t-1", name: "DEMO-Tenant (demo)", slug: "demo", status: "active" },
      { id: "t-2", name: "Second Org", slug: "second", status: "active" },
    ]);
    render(<TenantsPage />);

    expect(await screen.findByRole("link", { name: "DEMO-Tenant (demo)" })).toHaveAttribute(
      "href",
      "/dashboard?tenant=demo",
    );
    expect(screen.getByRole("link", { name: "Second Org" })).toHaveAttribute(
      "href",
      "/dashboard?tenant=second",
    );
  });
});

describe("errorMessage", () => {
  // Shapes as sent by common.exceptions.regx_exception_handler.
  it("names each invalid field from a wrapped 400 validation body", () => {
    expect(
      errorMessage({
        error: {
          status: 400,
          detail: {
            route_code: ["This field may not be blank."],
            active_release_public_id: ["Must be a valid UUID."],
          },
        },
      }),
    ).toBe(
      "route_code: This field may not be blank.; active_release_public_id: Must be a valid UUID.",
    );
  });

  it("uses the wrapped DRF detail for a refusal", () => {
    expect(
      errorMessage({ error: { status: 403, detail: { detail: "You do not have permission to perform this action." } } }),
    ).toBe("You do not have permission to perform this action.");
  });

  it("uses a wrapped plain-string detail", () => {
    expect(errorMessage({ error: { status: 400, detail: "Tenant context is required." } })).toBe(
      "Tenant context is required.",
    );
  });

  it("uses an unwrapped detail from a view's own refusal", () => {
    expect(errorMessage({ error_code: "self_registration_disabled", detail: "Self-registration is disabled." })).toBe(
      "Self-registration is disabled.",
    );
  });

  it("falls back to 'Request failed' for an empty or unreadable body", () => {
    expect(errorMessage({})).toBe("Request failed");
    expect(errorMessage(null)).toBe("Request failed");
    expect(errorMessage("oops")).toBe("Request failed");
    expect(errorMessage({ error: { status: 500, detail: "" } })).toBe("Request failed");
  });
});
