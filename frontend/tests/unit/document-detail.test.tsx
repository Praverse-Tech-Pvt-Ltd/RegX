import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    documents: {
      ...actual.documents,
      get: api.get,
      versions: api.versions,
      archive: api.archive,
      restore: api.restore,
      versionStatus: api.versionStatus,
      locators: api.locators,
    },
  };
});

import DocumentDetailPage from "@/app/documents/[publicId]/page";

beforeEach(() => {
  Object.values(nav).forEach((v) => typeof v === "object" && v);
  nav.push.mockReset?.();
  nav.tenant = "alpha";
  nav.publicId = "doc-public-0001";
  Object.values(api).forEach((fn) => fn.mockReset());
  api.versionStatus.mockResolvedValue({ scan_status: "clean", processing_status: "complete" });
});

describe("DocumentDetailPage — rendering", () => {
  it("renders the document title, type, and status", async () => {
    api.get.mockResolvedValue(
      makeDocument({ title: "Method Validation", document_type: "docx", status: "active" }),
    );
    api.versions.mockResolvedValue(paginate([makeVersion()]));

    render(<DocumentDetailPage />);

    expect(await screen.findByRole("heading", { name: "Method Validation" })).toBeInTheDocument();
    expect(screen.getByText("docx")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("renders the version list with each version number", async () => {
    const v1 = makeVersion({ public_id: "ver-1", version_number: 1 });
    const v2 = makeVersion({ public_id: "ver-2", version_number: 2 });
    api.get.mockResolvedValue(makeDocument({ current_version: v2 }));
    api.versions.mockResolvedValue(paginate([v2, v1]));

    render(<DocumentDetailPage />);

    expect(await screen.findByText(/Versions \(2\)/i)).toBeInTheDocument();
    expect(screen.getByText("Version 1")).toBeInTheDocument();
    expect(screen.getByText("Version 2")).toBeInTheDocument();
  });
});

describe("DocumentDetailPage — archive/restore visibility", () => {
  it("shows Archive (not Restore) and the upload-version form for an active document", async () => {
    api.get.mockResolvedValue(makeDocument({ status: "active" }));
    api.versions.mockResolvedValue(paginate([makeVersion()]));

    render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });

    expect(screen.getByRole("button", { name: /^archive$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^restore$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /upload new version/i })).toBeInTheDocument();
  });

  it("shows Restore (not Archive) and hides the upload form for an archived document", async () => {
    api.get.mockResolvedValue(makeDocument({ status: "archived", archived_at: "2026-07-21T00:00:00Z" }));
    api.versions.mockResolvedValue(paginate([makeVersion()]));

    render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });

    expect(screen.getByRole("button", { name: /^restore$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^archive$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /upload new version/i })).not.toBeInTheDocument();
  });

  it("invokes the archive API and reflects the new status", async () => {
    const user = userEvent.setup();
    api.get.mockResolvedValue(makeDocument({ status: "active" }));
    api.versions.mockResolvedValue(paginate([makeVersion()]));
    api.archive.mockResolvedValue(makeDocument({ status: "archived", archived_at: "2026-07-22T00:00:00Z" }));

    render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });

    await user.click(screen.getByRole("button", { name: /^archive$/i }));

    expect(api.archive).toHaveBeenCalledWith("alpha", "doc-public-0001");
    expect(await screen.findByRole("button", { name: /^restore$/i })).toBeInTheDocument();
  });
});

describe("DocumentDetailPage — locator summary", () => {
  it("loads and renders the structure locators on demand", async () => {
    api.get.mockResolvedValue(makeDocument());
    api.versions.mockResolvedValue(
      paginate([makeVersion({ scan_status: "clean", processing_status: "complete" })]),
    );
    api.locators.mockResolvedValue(
      paginate([
        makeLocator({ public_id: "loc-1", locator_type: "page", display_label: "Page 1" }),
        makeLocator({ public_id: "loc-2", locator_type: "page", display_label: "Page 2" }),
      ]),
    );

    const user = userEvent.setup();
    render(<DocumentDetailPage />);
    await screen.findByText("Version 1");

    await user.click(screen.getByRole("button", { name: /show structure/i }));

    expect(await screen.findByText("Page 1")).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(api.locators).toHaveBeenCalledWith("alpha", "doc-public-0001", "ver-public-0001");
  });
});

describe("DocumentDetailPage — no sensitive internal fields leak", () => {
  it("never renders storage keys, filesystem paths, or internal numeric IDs", async () => {
    const version = makeVersion();
    Object.assign(version, {
      id: 555111,
      storage_key: "tenant/3/deep-secret-key",
      storage_path: "/srv/regx/media/tenant/3/deep-secret-key",
    });
    const doc = makeDocument({ current_version: version });
    Object.assign(doc, { id: 222333 });
    api.get.mockResolvedValue(doc);
    api.versions.mockResolvedValue(paginate([version]));

    render(<DocumentDetailPage />);
    await screen.findByRole("heading", { name: /Quarterly Report/i });

    const body = document.body.textContent ?? "";
    expect(body).not.toContain("deep-secret-key");
    expect(body).not.toContain("/srv/regx/media");
    expect(body).not.toContain("555111");
    expect(body).not.toContain("222333");
  });
});
