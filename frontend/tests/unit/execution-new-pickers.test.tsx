/**
 * Starting a checklist execution without knowing any internal ID.
 * Found on the real stack (2026-11-17): the form took only two UUIDs.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ push: vi.fn(), query: "tenant=alpha" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.query),
}));

const api = vi.hoisted(() => ({
  definitions: vi.fn(),
  versions: vi.fn(),
  products: vi.fn(),
  formulationVersions: vi.fn(),
  create: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    iigChecklists: {
      definitions: { list: api.definitions },
      versions: { listForDefinition: api.versions },
      executions: { create: api.create },
    },
    formulations: {
      products: { list: api.products },
      versions: { list: api.formulationVersions },
    },
  };
});

import NewExecutionPage from "@/app/(regx)/iig-checklists/executions/new/page";

const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  nav.push.mockReset();
  nav.query = "tenant=alpha";
  api.definitions.mockResolvedValue(page([{ public_id: "def-1", code: "DEMO-IIG", title: "Demo checklist" }]));
  api.versions.mockResolvedValue(
    page([
      { public_id: "cv-draft", status: "draft", version_number: 2 },
      { public_id: "cv-active", status: "active", version_number: 1 },
    ]),
  );
  api.products.mockResolvedValue(page([{ public_id: "p-1", product_code: "SYN-1", proposed_product_name: "Synthetic Tablet" }]));
  api.formulationVersions.mockResolvedValue(
    page([
      { public_id: "fv-1", version_number: 1, status: "approved" },
      { public_id: "fv-2", version_number: 2, status: "draft" },
    ]),
  );
  api.create.mockResolvedValue({ publicId: "exec-1" });
});

describe("New checklist execution — choose, don't paste IDs", () => {
  it("offers only active checklist versions and the formulation versions, and creates from the choices", async () => {
    const user = userEvent.setup();
    render(<NewExecutionPage />);
    const checklist = await screen.findByLabelText(/choose an active checklist version/i);
    await waitFor(() => expect(screen.getByRole("option", { name: /DEMO-IIG — Demo checklist \(v1\)/ })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: /\(v2\)/ })).not.toBeInTheDocument();
    await user.selectOptions(checklist, "cv-active");
    await waitFor(() => expect(screen.getByRole("option", { name: /SYN-1 — Synthetic Tablet \(v1, approved\)/ })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/choose a formulation version/i), "fv-1");
    expect(screen.getByLabelText(/checklist version public id/i)).toHaveValue("cv-active");
    expect(screen.getByLabelText(/formulation version public id/i)).toHaveValue("fv-1");
    await user.click(screen.getByRole("button", { name: /create execution/i }));
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith("alpha", {
        checklist_version_public_id: "cv-active",
        formulation_version_public_id: "fv-1",
      }),
    );
    expect(nav.push).toHaveBeenCalledWith("/iig-checklists/executions/exec-1?tenant=alpha");
  });

  it("shows a draft formulation version but does not let it be chosen (the API refuses it)", async () => {
    render(<NewExecutionPage />);
    const draft = await screen.findByRole("option", { name: /v2, draft — not approved/ });
    expect(draft).toBeDisabled();
    expect(screen.getByRole("option", { name: /v1, approved/ })).toBeEnabled();
  });

  it("explains when no formulation version is approved", async () => {
    api.formulationVersions.mockResolvedValue(page([{ public_id: "fv-2", version_number: 2, status: "draft" }]));
    render(<NewExecutionPage />);
    expect(await screen.findByText(/No formulation version is approved yet/)).toBeInTheDocument();
  });

  it("arriving from a draft version's link: says it is not approved and does not offer to create", async () => {
    nav.query = "tenant=alpha&formulationVersion=fv-2";
    render(<NewExecutionPage />);
    expect(await screen.findByText(/This formulation version is not approved/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create execution/i })).toBeDisabled();
  });

  it("is pre-filled from the formulation version's link", () => {
    nav.query = "tenant=alpha&formulationVersion=fv-1";
    render(<NewExecutionPage />);
    expect(screen.getByLabelText(/formulation version public id/i)).toHaveValue("fv-1");
  });
});
