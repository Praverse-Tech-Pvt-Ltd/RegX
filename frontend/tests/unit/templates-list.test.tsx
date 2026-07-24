import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeTemplate, paginate } from "./fixtures";

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
  useSearchParams: () =>
    new URLSearchParams(nav.tenant ? `tenant=${nav.tenant}` : ""),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: unknown;
  }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

const api = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    templates: { ...actual.templates, list: api.list },
  };
});

import TemplatesPage from "@/app/templates/page";

beforeEach(() => {
  nav.push.mockReset();
  nav.tenant = "alpha";
  api.list.mockReset();
});

describe("TemplatesPage — loading and empty states", () => {
  it("shows a loading indicator while the list request is pending", () => {
    api.list.mockReturnValue(new Promise(() => {}));
    render(<TemplatesPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows an empty state when no templates exist", async () => {
    api.list.mockResolvedValue(paginate([]));
    render(<TemplatesPage />);
    expect(await screen.findByText(/No templates yet/i)).toBeInTheDocument();
  });

  it("redirects to tenant selection when no tenant slug is present", () => {
    nav.tenant = "";
    api.list.mockResolvedValue(paginate([]));
    render(<TemplatesPage />);
    expect(nav.push).toHaveBeenCalledWith("/tenants");
  });
});

describe("TemplatesPage — rows and lifecycle status badges", () => {
  it("renders a template row with its canonical code and status", async () => {
    api.list.mockResolvedValue(
      paginate([
        makeTemplate({
          canonical_code: "DMF-GENERAL",
          title: "DMF General Information",
          lifecycle_status: "active",
        }),
      ]),
    );
    render(<TemplatesPage />);

    const link = await screen.findByRole("link", { name: "DMF-GENERAL" });
    const row = link.closest("tr")!;
    expect(
      within(row).getByText("DMF General Information"),
    ).toBeInTheDocument();
    expect(within(row).getByText(/active/i)).toBeInTheDocument();
  });

  it("distinguishes an under-review badge from an approved badge", async () => {
    api.list.mockResolvedValue(
      paginate([
        makeTemplate({
          public_id: "tpl-public-a",
          canonical_code: "TPL-A",
          lifecycle_status: "under_review",
        }),
        makeTemplate({
          public_id: "tpl-public-b",
          canonical_code: "TPL-B",
          lifecycle_status: "approved",
        }),
      ]),
    );
    render(<TemplatesPage />);

    const rowA = (await screen.findByRole("link", { name: "TPL-A" })).closest(
      "tr",
    )!;
    const rowB = screen.getByRole("link", { name: "TPL-B" }).closest("tr")!;
    expect(within(rowA).getByText(/under review/i)).toBeInTheDocument();
    expect(within(rowB).getByText(/approved/i)).toBeInTheDocument();
  });
});

describe("TemplatesPage — status filter", () => {
  it("requests a status-filtered list when the dropdown changes", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();
    api.list.mockResolvedValue(paginate([]));
    render(<TemplatesPage />);
    await screen.findByText(/No templates yet/i);

    await user.selectOptions(
      screen.getByLabelText(/filter by status/i),
      "active",
    );
    expect(api.list).toHaveBeenLastCalledWith("alpha", { status: "active" });
  });
});

describe("TemplatesPage — no internal identifiers leak into the DOM", () => {
  it("never renders internal numeric IDs even if present on the object", async () => {
    const template = makeTemplate({ canonical_code: "TPL-LEAK" });
    Object.assign(template, { id: 555444 });
    api.list.mockResolvedValue(paginate([template]));

    render(<TemplatesPage />);
    await screen.findByRole("link", { name: "TPL-LEAK" });

    expect(document.body.textContent ?? "").not.toContain("555444");
  });
});
