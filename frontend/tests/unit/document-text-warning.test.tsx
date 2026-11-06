import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeDocument, makeVersion, paginate } from "./fixtures";
import type { TextExtractionWarning } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams("tenant=alpha"),
  useParams: () => ({ publicId: "doc-public-0001" }),
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
      versionStatus: api.versionStatus,
      locators: api.locators,
    },
  };
});

import DocumentDetailPage from "@/app/(regx)/documents/[publicId]/page";

const NO_TEXT: TextExtractionWarning = {
  level: "warning",
  code: "no_extractable_text",
  message:
    "No extractable text, likely scanned. Text-based features cannot use this document; its extracted text is incomplete: no extractable text.",
};
const PARTIAL: TextExtractionWarning = {
  level: "warning",
  code: "partial_text",
  pages_without_text: 3,
  total_pages: 12,
  message: "3 of 12 pages have no extractable text. Extracted text for this document is incomplete.",
};

function setup(warning: TextExtractionWarning | null) {
  const v = makeVersion({ public_id: "ver-1", processing_status: "complete", text_extraction_warning: warning });
  api.get.mockResolvedValue(makeDocument({ current_version: v }));
  api.versions.mockResolvedValue(paginate([v]));
  api.versionStatus.mockResolvedValue({
    scan_status: "clean",
    processing_status: "complete",
    text_extraction_warning: warning,
  });
  render(<DocumentDetailPage />);
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
});

describe("DocumentDetailPage — text-extraction warning", () => {
  it("shows a full warning banner for a document with no extractable text", async () => {
    setup(NO_TEXT);
    const banners = await screen.findAllByTestId("text-extraction-no_extractable_text");
    // Page-level banner plus the compact note on the version row.
    expect(banners).toHaveLength(2);
    expect(within(banners[0]!).getByText("Warning: no extractable text")).toBeInTheDocument();
    expect(banners[0]).toHaveTextContent("likely scanned");
    expect(banners[0]).toHaveAttribute("role", "status");
    // A warning, not an error: processing still reads as complete.
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a smaller note with the page count when some pages have no text", async () => {
    setup(PARTIAL);
    const notes = await screen.findAllByTestId("text-extraction-partial_text");
    expect(notes[0]).toHaveTextContent("3 of 12 pages have no extractable text.");
    expect(screen.queryByText("Warning: no extractable text")).not.toBeInTheDocument();
  });

  it("shows nothing for a normal text document", async () => {
    setup(null);
    await screen.findByText("Version 1");
    expect(screen.queryByTestId(/text-extraction-/)).not.toBeInTheDocument();
  });
});
