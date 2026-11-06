import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MfaEnrolmentBanner from "@/components/regx-shell/MfaEnrolmentBanner";
import MfaSetupPage from "@/app/mfa/setup/page";
import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ status: vi.fn(), setup: vi.fn(), verify: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    mfa: { ...actual.mfa, status: api.status, setup: api.setup, verify: api.verify },
  };
});

const SECRET = "JBSWY3DPEHPK3PXP";
const URI = `otpauth://totp/RegX:rv%40example.com?secret=${SECRET}&issuer=RegX`;

beforeEach(() => {
  api.status.mockReset();
  api.setup.mockReset();
  api.verify.mockReset();
});

describe("MFA enrolment banner (SOW 4.3)", () => {
  it("shows for a Reviewer or VP who has not enrolled, linking to setup", async () => {
    api.status.mockResolvedValue({
      mfa_enrolled: false,
      holds_mfa_required_role: true,
      mfa_enrolment_required: true,
    });
    render(<MfaEnrolmentBanner />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("requires two-step sign-in");
    expect(screen.getByRole("link", { name: "set up MFA" })).toHaveAttribute("href", "/mfa/setup");
  });

  it("stays hidden when enrolment is not required", async () => {
    api.status.mockResolvedValue({
      mfa_enrolled: false,
      holds_mfa_required_role: false,
      mfa_enrolment_required: false,
    });
    render(<MfaEnrolmentBanner />);
    await waitFor(() => expect(api.status).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("stays hidden if the status call fails (the backend still enforces)", async () => {
    api.status.mockRejectedValue(new ApiError(500, "boom"));
    render(<MfaEnrolmentBanner />);
    await waitFor(() => expect(api.status).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("MFA setup page", () => {
  it("shows the key and recovery codes, then activates with a code", async () => {
    api.setup.mockResolvedValue({ totp_uri: URI, recovery_codes: ["aaaa-1111", "bbbb-2222"] });
    api.verify.mockResolvedValue({ detail: "MFA activated." });
    const user = userEvent.setup();
    render(<MfaSetupPage />);

    await user.click(screen.getByRole("button", { name: "Start setup" }));
    expect(await screen.findByTestId("mfa-secret")).toHaveTextContent(SECRET);
    expect(screen.getByTestId("mfa-recovery-codes")).toHaveTextContent("aaaa-1111");

    await user.type(screen.getByLabelText(/6-digit code/), "123456");
    await user.click(screen.getByRole("button", { name: "Turn on MFA" }));
    expect(api.verify).toHaveBeenCalledWith("123456");
    expect(await screen.findByText("Two-step sign-in is on")).toBeInTheDocument();
    expect(screen.queryByTestId("mfa-secret")).toBeNull();
  });

  it("a wrong code keeps the form and shows the error", async () => {
    api.setup.mockResolvedValue({ totp_uri: URI, recovery_codes: [] });
    api.verify.mockRejectedValue(new ApiError(400, "Invalid OTP."));
    const user = userEvent.setup();
    render(<MfaSetupPage />);
    await user.click(screen.getByRole("button", { name: "Start setup" }));
    await user.type(await screen.findByLabelText(/6-digit code/), "000000");
    await user.click(screen.getByRole("button", { name: "Turn on MFA" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid OTP.");
    expect(screen.getByTestId("mfa-secret")).toBeInTheDocument();
  });

  it("an already-enrolled user is told MFA is on", async () => {
    api.setup.mockRejectedValue(new ApiError(409, "MFA already active."));
    const user = userEvent.setup();
    render(<MfaSetupPage />);
    await user.click(screen.getByRole("button", { name: "Start setup" }));
    expect(await screen.findByText("Two-step sign-in is on")).toBeInTheDocument();
  });

  it("a signed-out visitor is asked to sign in", async () => {
    api.setup.mockRejectedValue(new ApiError(403, "Authentication credentials were not provided."));
    const user = userEvent.setup();
    render(<MfaSetupPage />);
    await user.click(screen.getByRole("button", { name: "Start setup" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign in first");
  });
});
