// Automated accessibility checks (axe-core via jest-axe) at the component level.
//
// This proves the absence of automatically-detectable violations (missing
// labels/names, invalid ARIA usage, contrast on static markup, etc). It does
// NOT establish full WCAG 2.1 AA conformance — axe-core's own documentation
// states automated tools catch roughly 30-50% of WCAG issues. Manual review
// (keyboard-only walkthroughs, screen-reader testing, cognitive/timing
// criteria) is still required for a conformance claim.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeDocument, makeLocator, makeVersion, paginate } from "./fixtures";

const nav = vi.hoisted(() => ({ push: vi.fn(), tenant: "alpha", publicId: "doc-public-0001" }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: nav.push,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(nav.tenant ? `tenant=${nav.tenant}` : ""),
  useParams: () => ({ publicId: nav.publicId }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: unknown }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  get: vi.fn(),
  versions: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
  versionStatus: vi.fn(),
  locators: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    documents: { ...actual.documents, ...api },
  };
});

import SignInPage from "@/app/signin/page";
import DocumentsPage from "@/app/documents/page";
import DocumentDetailPage from "@/app/documents/[publicId]/page";

beforeEach(() => {
  nav.push.mockReset();
  nav.tenant = "alpha";
  nav.publicId = "doc-public-0001";
  Object.values(api).forEach((fn) => fn.mockReset());
  api.versionStatus.mockResolvedValue({ scan_status: "clean", processing_status: "complete" });
});

describe("Accessibility — /signin", () => {
  it("has no serious or critical automated violations", async () => {
    const { container } = render(<SignInPage />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("labels both fields and gives the form an accessible name", () => {
    render(<SignInPage />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByRole("form", { name: /sign in form/i })).toBeInTheDocument();
  });
});

describe("Accessibility — /documents", () => {
  it("has no serious or critical automated violations in the list view", async () => {
    api.list.mockResolvedValue(
      paginate([makeDocument(), makeDocument({ public_id: "doc-2", title: "Second Doc" })]),
    );
    const { container } = render(<DocumentsPage />);
    await screen.findByRole("link", { name: "Quarterly Report" });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("has no serious or critical automated violations in the empty state", async () => {
    api.list.mockResolvedValue(paginate([]));
    const { container } = render(<DocumentsPage />);
    await screen.findByText(/No documents yet/i);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("upload dialog has correct dialog semantics, an accessible name, and no violations", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue(paginate([]));
    const { container } = render(<DocumentsPage />);
    await screen.findByText(/No documents yet/i);
    await user.click(screen.getByRole("button", { name: /upload document/i }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName(/upload document/i);

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("associates the upload error message with the form via an assertive live region", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue(paginate([]));
    const { ApiError } = await import("@/lib/api");
    api.create.mockRejectedValue(new ApiError(400, "Unsupported file extension."));

    render(<DocumentsPage />);
    await screen.findByText(/No documents yet/i);
    await user.click(screen.getByRole("button", { name: /upload document/i }));
    const dialog = screen.getByRole("dialog");

    await user.type(within(dialog).getByLabelText("Title"), "Bad File");
    const fileInput = within(dialog).getByLabelText("File") as HTMLInputElement;
    await user.upload(fileInput, new File(["x"], "bad.pdf", { type: "application/pdf" }));

    const { fireEvent } = await import("@testing-library/react");
    fireEvent.submit(fileInput.closest("form")!);

    const alert = await within(dialog).findByRole("alert");
    // role="alert" is an implicit assertive live region (no separate
    // aria-live attribute required); this is the mechanism screen readers
    // use to announce the validation failure without user action.
    expect(alert).toHaveTextContent(/Unsupported file extension\./i);
  });
});

describe("Accessibility — /documents/{public_id}", () => {
  it("has no serious or critical automated violations, including the version list", async () => {
    api.get.mockResolvedValue(makeDocument());
    api.versions.mockResolvedValue(paginate([makeVersion()]));

    const { container } = render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });
    await screen.findByText("Version 1");

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("keeps a single h1 and does not skip heading levels", async () => {
    api.get.mockResolvedValue(makeDocument());
    api.versions.mockResolvedValue(paginate([makeVersion()]));

    render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    // "Versions (n)" and "Upload new version" are the only subsections and
    // must be h2, not skip straight to h3+.
    const h2s = screen.getAllByRole("heading", { level: 2 });
    expect(h2s.length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });

  it("archive/restore controls remain keyboard-focusable and accessibly named", async () => {
    api.get.mockResolvedValue(makeDocument({ status: "active" }));
    api.versions.mockResolvedValue(paginate([makeVersion()]));

    render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });

    const archiveBtn = screen.getByRole("button", { name: /^archive$/i });
    expect(archiveBtn).toHaveAccessibleName();
    archiveBtn.focus();
    expect(archiveBtn).toHaveFocus();
  });

  it("the locator summary toggle and its resulting list have no automated violations", async () => {
    api.get.mockResolvedValue(makeDocument());
    api.versions.mockResolvedValue(
      paginate([makeVersion({ scan_status: "clean", processing_status: "complete" })]),
    );
    api.locators.mockResolvedValue(
      paginate([
        makeLocator({ public_id: "loc-1", display_label: "Page 1" }),
        makeLocator({ public_id: "loc-2", display_label: "Page 2" }),
      ]),
    );

    const user = userEvent.setup();
    const { container } = render(<DocumentDetailPage />);
    await screen.findByText("Version 1");

    const toggle = screen.getByRole("button", { name: /show structure/i });
    expect(toggle).toHaveAccessibleName();
    await user.click(toggle);
    await screen.findByText("Page 1");

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
