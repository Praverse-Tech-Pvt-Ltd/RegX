import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeDocument, makeVersion, paginate } from "./fixtures";

const nav = vi.hoisted(() => ({ push: vi.fn(), tenant: "alpha" }));

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
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: unknown }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    documents: { ...actual.documents, list: api.list, create: api.create },
  };
});

import DocumentsPage from "@/app/(regx)/documents/page";

beforeEach(() => {
  nav.push.mockReset();
  nav.tenant = "alpha";
  api.list.mockReset();
  api.create.mockReset();
});

describe("DocumentsPage — loading and empty states", () => {
  it("shows a loading indicator while the list request is pending", () => {
    api.list.mockReturnValue(new Promise(() => {})); // never resolves
    render(<DocumentsPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("signed out: goes to sign-in and never says 'No documents yet' (4e, 2026-11-26)", async () => {
    const { ApiError } = await import("@/lib/api");
    api.list.mockRejectedValue(new ApiError(401, "Authentication credentials were not provided.", "not_authenticated"));
    render(<DocumentsPage />);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(expect.stringMatching(/^\/signin\?next=/)));
    expect(screen.queryByText(/No documents yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed to load documents/i)).not.toBeInTheDocument();
  });

  it("refused (403): shows the refusal and no empty-state text", async () => {
    const { ApiError } = await import("@/lib/api");
    api.list.mockRejectedValue(new ApiError(403, "You do not have permission to perform this action.", "permission_denied"));
    render(<DocumentsPage />);
    expect(await screen.findByText("You do not have permission to perform this action.")).toBeInTheDocument();
    expect(screen.queryByText(/No documents yet/i)).not.toBeInTheDocument();
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("shows an empty state when no documents exist", async () => {
    api.list.mockResolvedValue(paginate([]));
    render(<DocumentsPage />);
    expect(
      await screen.findByText(/No documents yet\. Upload one to get started\./i),
    ).toBeInTheDocument();
  });

  it("redirects to tenant selection when no tenant slug is present", () => {
    nav.tenant = "";
    api.list.mockResolvedValue(paginate([]));
    render(<DocumentsPage />);
    expect(nav.push).toHaveBeenCalledWith("/tenants");
  });
});

describe("DocumentsPage — rows and status badges", () => {
  it("renders a document row with its scan and processing status", async () => {
    api.list.mockResolvedValue(
      paginate([
        makeDocument({
          title: "Stability Study",
          current_version: makeVersion({
            scan_status: "clean",
            processing_status: "processing",
          }),
        }),
      ]),
    );
    render(<DocumentsPage />);

    const link = await screen.findByRole("link", { name: "Stability Study" });
    const row = link.closest("tr")!;
    expect(within(row).getByText(/clean/i)).toBeInTheDocument();
    // processing_status "processing" maps to the label "processing…"
    expect(within(row).getByText(/processing…/i)).toBeInTheDocument();
  });

  it("renders a quarantined badge distinctly from a clean badge", async () => {
    api.list.mockResolvedValue(
      paginate([
        makeDocument({
          title: "Suspicious Upload",
          current_version: makeVersion({ scan_status: "quarantined", processing_status: "skipped" }),
        }),
      ]),
    );
    render(<DocumentsPage />);
    const link = await screen.findByRole("link", { name: "Suspicious Upload" });
    const row = link.closest("tr")!;
    expect(within(row).getByText(/quarantined/i)).toBeInTheDocument();
  });
});

describe("DocumentsPage — upload dialog", () => {
  it("opens and closes the upload dialog", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue(paginate([]));
    render(<DocumentsPage />);
    await screen.findByText(/No documents yet/i);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /upload document/i }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: /upload document/i })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("displays a validation error returned by the upload API", async () => {
    const user = userEvent.setup();
    api.list.mockResolvedValue(paginate([]));
    const { ApiError } = await import("@/lib/api");
    api.create.mockRejectedValue(new ApiError(400, "Unsupported file extension."));

    render(<DocumentsPage />);
    await screen.findByText(/No documents yet/i);
    await user.click(screen.getByRole("button", { name: /upload document/i }));

    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Title"), "Bad File");
    // MIME type matches the dialog's accept filter (as a real file picker would
    // enforce client-side); the mismatch this test exercises is caught server-side.
    const fileInput = within(dialog).getByLabelText("File") as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(["not really a pdf"], "malware.pdf", { type: "application/pdf" }),
    );
    // jsdom does not correctly compute constraint-validation validity for a
    // `required` file input even once `files` is populated, so a real click
    // on the submit button never fires the submit event here. The equivalent
    // real-browser flow is covered by the Playwright document-flow suite;
    // dispatch the submit event directly to exercise handleUpload in jsdom.
    fireEvent.submit(fileInput.closest("form")!);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /Unsupported file extension\./i,
    );
    // Failed upload keeps the dialog open so the user can correct it.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("DocumentsPage — no sensitive internal fields leak into the DOM", () => {
  it("never renders storage keys, filesystem paths, or internal numeric IDs", async () => {
    const doc = makeDocument({ title: "Report" });
    // Simulate a backend response that (wrongly) carried internal fields:
    // the UI must not surface them even if present on the object.
    Object.assign(doc, { id: 424242, storage_key: "tenant/9/secret-object-key" });
    Object.assign(doc.current_version as object, {
      id: 999777,
      storage_key: "tenant/9/secret-object-key",
      storage_path: "/var/lib/regx/media/tenant/9/secret-object-key",
    });
    api.list.mockResolvedValue(paginate([doc]));

    render(<DocumentsPage />);
    await screen.findByRole("link", { name: "Report" });

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("secret-object-key");
    expect(body).not.toContain("/var/lib/regx/media");
    expect(body).not.toContain("424242");
    expect(body).not.toContain("999777");
  });
});
