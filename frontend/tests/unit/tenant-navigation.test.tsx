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
import { apiRequest, errorMessage, PERMISSION_MESSAGE, SERVER_ERROR_MESSAGE } from "@/lib/api";

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

  it("shows a list-shaped detail as its sentences, never 'Request failed' (4d, 2026-11-26)", () => {
    expect(
      errorMessage({ error: { status: 400, detail: ["effective_date is required before submitting for review."] } }),
    ).toBe("effective_date is required before submitting for review.");
    expect(errorMessage({ error: { status: 400, detail: ["First problem.", "Second problem."] } })).toBe(
      "First problem. Second problem.",
    );
    expect(errorMessage(["Unwrapped list message."])).toBe("Unwrapped list message.");
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

  // Step 2 of the 2026-11-17 plan: no raw JSON, no internals.
  it("never shows a 500's body, even when it carries a detail", () => {
    const body = {
      error: { status: 500, detail: "Traceback (most recent call last): File /app/iid_assessment/assess.py" },
    };
    expect(errorMessage(body, 500)).toBe(SERVER_ERROR_MESSAGE);
    expect(errorMessage("<html>Server Error (500)</html>", 502)).toBe(SERVER_ERROR_MESSAGE);
    expect(errorMessage({ detail: "Request failed" }, 500)).toBe(SERVER_ERROR_MESSAGE);
  });

  it("shows a permission refusal's sentence, or a plain fallback, never JSON", () => {
    expect(errorMessage({ detail: "User is not a member of this tenant." }, 403)).toBe(
      "User is not a member of this tenant.",
    );
    const structured = { error: { status: 403, detail: { error_code: "x", reasons: ["a"] } } };
    expect(errorMessage(structured, 403)).toBe(PERMISSION_MESSAGE);
    expect(errorMessage({}, 401)).toBe(PERMISSION_MESSAGE);
  });

  it("reports a nested validation value as 'is invalid', never as raw JSON", () => {
    const msg = errorMessage(
      { error: { status: 400, detail: { components: [{ quantity: ["Too large."] }], route_code: ["Required."] } } },
      400,
    );
    expect(msg).toBe("components: is invalid; route_code: Required.");
    expect(msg).not.toMatch(/[{}[\]]/);
  });

  it("caps a very long message", () => {
    expect(errorMessage({ detail: "x".repeat(1000) }, 400)).toHaveLength(300);
  });

  it("apiRequest turns a 500 into the generic message and keeps the middleware's 403 sentence", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { status: 500, detail: "KeyError at /app/x.py line 12" } }), { status: 500 }),
    );
    await expect(apiRequest("/api/regx/v1/x/")).rejects.toMatchObject({ status: 500, message: SERVER_ERROR_MESSAGE });
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "User is not a member of this tenant." }), { status: 403 }),
    );
    await expect(apiRequest("/api/regx/v1/x/")).rejects.toMatchObject({
      status: 403,
      message: "User is not a member of this tenant.",
    });
  });

  it("falls back to 'Request failed' for an empty or unreadable body", () => {
    expect(errorMessage({})).toBe("Request failed");
    expect(errorMessage(null)).toBe("Request failed");
    expect(errorMessage("oops")).toBe("Request failed");
    expect(errorMessage({ error: { status: 500, detail: "" } })).toBe("Request failed");
  });
});
