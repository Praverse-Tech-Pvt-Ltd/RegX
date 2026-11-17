import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/*
 * The navbar's "Login" used to go to the company site's own login
 * (/adminmaster/login/). On a REGX page, where the user is already signed in
 * to REGX, that read as a second REGX login leading to different pages.
 */

const nav = vi.hoisted(() => ({ pathname: "/documents" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

const authApi = vi.hoisted(() => ({ me: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  auth: authApi,
}));

import CompanyNavbar from "@/components/regx-shell/CompanyNavbar";

beforeEach(() => {
  nav.pathname = "/documents";
  authApi.me.mockReset();
});

describe("CompanyNavbar — Login", () => {
  it("shows no Login when signed in to REGX", async () => {
    authApi.me.mockResolvedValue({ email: "doer@example.com" });
    render(<CompanyNavbar />);
    await waitFor(() => expect(authApi.me).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("link", { name: "Login" })).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/adminmaster/login/"]')).toBeNull();
  });

  it("links Login to REGX's /signin when not signed in", async () => {
    authApi.me.mockRejectedValue(new Error("403"));
    render(<CompanyNavbar />);
    expect(await screen.findByRole("link", { name: "Login" })).toHaveAttribute("href", "/signin");
    expect(document.querySelector('a[href="/adminmaster/login/"]')).toBeNull();
  });

  it("shows nothing while the sign-in state is unknown (no flash of a Login button)", () => {
    authApi.me.mockReturnValue(new Promise(() => {}));
    render(<CompanyNavbar />);
    expect(screen.queryByRole("link", { name: "Login" })).not.toBeInTheDocument();
  });

  it("does not offer Login on the sign-in screens themselves", async () => {
    nav.pathname = "/signin";
    authApi.me.mockRejectedValue(new Error("403"));
    render(<CompanyNavbar />);
    await waitFor(() => expect(authApi.me).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("link", { name: "Login" })).not.toBeInTheDocument();
  });

  it("keeps the company destinations and Schedule Consultation", async () => {
    authApi.me.mockResolvedValue({});
    render(<CompanyNavbar />);
    expect(screen.getByRole("link", { name: /Audit IQ/ })).toHaveAttribute("href", "/aidatabase/auditiq/");
    expect(screen.getByRole("link", { name: "Schedule Consultation" })).toHaveAttribute("href", "/ratools/requestdemo");
  });
});
