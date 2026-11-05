import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SignInPage from "@/app/signin/page";
import MFAPage from "@/app/mfa/page";
import { ApiError } from "@/lib/api";

const nav = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: nav.push,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const api = vi.hoisted(() => ({ login: vi.fn(), loginMfa: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, auth: { ...actual.auth, login: api.login, loginMfa: api.loginMfa } };
});

const PROFILE = {
  id: "u-1",
  email: "a@example.com",
  full_name: "A",
  is_active: true,
  mfa_required: false,
  created_at: "2026-11-05T00:00:00Z",
};

function setSearch(search: string) {
  window.history.replaceState({}, "", `/signin${search}`);
}

async function signIn() {
  const user = userEvent.setup();
  render(<SignInPage />);
  await user.type(screen.getByLabelText("Email"), "a@example.com");
  await user.type(screen.getByLabelText("Password"), "pw-123456789");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  nav.push.mockReset();
  api.login.mockReset();
  api.loginMfa.mockReset();
  setSearch("");
});

describe("Sign-in with MFA", () => {
  it("a user without MFA goes straight to the return target", async () => {
    api.login.mockResolvedValue(PROFILE);
    await signIn();
    expect(nav.push).toHaveBeenCalledWith("/tenants");
  });

  it("an enrolled user is sent to the code step, keeping ?next", async () => {
    setSearch("?next=%2Fdocuments");
    api.login.mockResolvedValue({ mfa_required: true, mfa_pending: true, email: "a@example.com" });
    await signIn();
    expect(nav.push).toHaveBeenCalledWith("/mfa?next=%2Fdocuments");
  });

  it("the code step calls the login second step and then returns", async () => {
    window.history.replaceState({}, "", "/mfa?next=%2Fdocuments");
    api.loginMfa.mockResolvedValue({ ...PROFILE, mfa_required: true });
    const user = userEvent.setup();
    render(<MFAPage />);
    await user.type(screen.getByLabelText("OTP Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(api.loginMfa).toHaveBeenCalledWith("123456");
    expect(nav.push).toHaveBeenCalledWith("/documents");
  });

  it("a wrong code shows the error and goes nowhere", async () => {
    api.loginMfa.mockRejectedValue(new ApiError(400, "Invalid code."));
    const user = userEvent.setup();
    render(<MFAPage />);
    await user.type(screen.getByLabelText("OTP Code"), "000000");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid code.");
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("the code step never sends the user back to /mfa or /signin", async () => {
    window.history.replaceState({}, "", "/mfa?next=%2Fmfa");
    api.loginMfa.mockResolvedValue(PROFILE);
    const user = userEvent.setup();
    render(<MFAPage />);
    await user.type(screen.getByLabelText("OTP Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(nav.push).toHaveBeenCalledWith("/tenants");
  });
});
