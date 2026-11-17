import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/*
 * Editing ?tenant= to an organisation the user does not belong to: the backend
 * refuses with 403 (backend/tenancy/tests/test_tenant_switch_isolation.py),
 * and the shell shows that refusal instead of mounting the page, so the page
 * makes no data request and shows no data.
 */

const nav = vi.hoisted(() => ({ tenant: "", pathname: "/formulations" }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.tenant ? `tenant=${nav.tenant}` : ""),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: unknown }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/regx-shell/MfaEnrolmentBanner", () => ({ default: () => null }));

const tenantsApi = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  tenants: tenantsApi,
}));

import RegxShell from "@/components/regx-shell/RegxShell";

/** Stands in for a page: records that it mounted and would have fetched data. */
const pageFetch = vi.fn();
function FakePage() {
  useEffect(() => {
    pageFetch();
  }, []);
  return <p>PAGE CONTENT: secret product list</p>;
}

function renderShell() {
  return render(
    <RegxShell>
      <FakePage />
    </RegxShell>,
  );
}

beforeEach(() => {
  pageFetch.mockReset();
  tenantsApi.list.mockReset();
});

describe("TenantGate — editing ?tenant= in the URL", () => {
  it("refuses an organisation the user is not a member of, and never mounts the page", async () => {
    nav.tenant = "other-org";
    tenantsApi.list.mockResolvedValue([{ id: "1", name: "Own Org", slug: "own-org", status: "active" }]);
    renderShell();

    expect(await screen.findByRole("heading", { name: "No access to this organisation" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You are not a member of the organisation “other-org”. Nothing from it has been loaded.",
    );
    expect(screen.getByRole("link", { name: /choose one of your organisations/i })).toHaveAttribute(
      "href",
      "/tenants",
    );
    expect(screen.queryByText(/PAGE CONTENT/)).not.toBeInTheDocument();
    expect(pageFetch).not.toHaveBeenCalled();
  });

  it("shows the page for an organisation the user belongs to", async () => {
    nav.tenant = "own-org";
    tenantsApi.list.mockResolvedValue([{ id: "1", name: "Own Org", slug: "own-org", status: "active" }]);
    renderShell();

    expect(await screen.findByText(/PAGE CONTENT/)).toBeInTheDocument();
    expect(pageFetch).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("No access to this organisation")).not.toBeInTheDocument();
  });

  it("does not mount the page while membership is still being checked", async () => {
    nav.tenant = "own-org";
    let resolve: (v: unknown) => void = () => {};
    tenantsApi.list.mockReturnValue(new Promise((r) => (resolve = r)));
    renderShell();

    expect(await screen.findByText("Checking access…")).toBeInTheDocument();
    expect(pageFetch).not.toHaveBeenCalled();
    resolve([{ slug: "own-org" }]);
    expect(await screen.findByText(/PAGE CONTENT/)).toBeInTheDocument();
  });

  it("falls back to the page when the list cannot be read (the backend still refuses)", async () => {
    nav.tenant = "own-org";
    tenantsApi.list.mockRejectedValue(new Error("network"));
    renderShell();
    expect(await screen.findByText(/PAGE CONTENT/)).toBeInTheDocument();
  });

  it("falls back to the page when the answer is not the endpoint's array", async () => {
    nav.tenant = "own-org";
    tenantsApi.list.mockResolvedValue({ results: [] });
    renderShell();
    expect(await screen.findByText(/PAGE CONTENT/)).toBeInTheDocument();
  });

  it("does not check membership on a page with no tenant", async () => {
    nav.tenant = "";
    renderShell();
    expect(await screen.findByText(/PAGE CONTENT/)).toBeInTheDocument();
    await waitFor(() => expect(tenantsApi.list).not.toHaveBeenCalled());
  });
});
