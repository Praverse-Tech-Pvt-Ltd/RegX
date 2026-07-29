import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  makeChecklistDefinition,
  makeChecklistSection,
  makeChecklistVersion,
  paginate,
} from "./fixtures";
import { ApiError } from "@/lib/api";

const nav = vi.hoisted(() => ({
  push: vi.fn(),
  tenant: "alpha",
  publicId: "checklist-def-public-0001",
  versionPublicId: "checklist-version-public-0001",
}));

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
  useParams: () => ({ publicId: nav.publicId, versionPublicId: nav.versionPublicId }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: unknown }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

const api = vi.hoisted(() => ({
  definitionsList: vi.fn(),
  definitionsGet: vi.fn(),
  definitionsCreate: vi.fn(),
  definitionsRemove: vi.fn(),
  definitionsClone: vi.fn(),
  versionsListForDefinition: vi.fn(),
  versionsCreate: vi.fn(),
  versionsGet: vi.fn(),
  versionsSubmitReview: vi.fn(),
  versionsApprove: vi.fn(),
  versionsReturn: vi.fn(),
  versionsReject: vi.fn(),
  versionsActivate: vi.fn(),
  versionsSupersede: vi.fn(),
  versionsRetire: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    iigChecklists: {
      definitions: {
        list: api.definitionsList,
        get: api.definitionsGet,
        create: api.definitionsCreate,
        remove: api.definitionsRemove,
        clone: api.definitionsClone,
      },
      versions: {
        listForDefinition: api.versionsListForDefinition,
        create: api.versionsCreate,
        get: api.versionsGet,
        submitReview: api.versionsSubmitReview,
        approve: api.versionsApprove,
        return: api.versionsReturn,
        reject: api.versionsReject,
        activate: api.versionsActivate,
        supersede: api.versionsSupersede,
        retire: api.versionsRetire,
      },
    },
  };
});

import DefinitionsPage from "@/app/iig-checklists/page";
import NewDefinitionPage from "@/app/iig-checklists/new/page";
import DefinitionDetailPage from "@/app/iig-checklists/[publicId]/page";
import VersionDetailPage from "@/app/iig-checklists/versions/[versionPublicId]/page";

beforeEach(() => {
  nav.push.mockReset();
  nav.tenant = "alpha";
  nav.publicId = "checklist-def-public-0001";
  nav.versionPublicId = "checklist-version-public-0001";
  Object.values(api).forEach((fn) => fn.mockReset());
});

describe("DefinitionsPage — list", () => {
  it("shows a loading state, then the definition list", async () => {
    api.definitionsList.mockResolvedValue(paginate([makeChecklistDefinition()]));
    render(<DefinitionsPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "IIG-ORAL-SOLID" });
    const row = link.closest("tr")!;
    expect(within(row).getByText(/tenant/i)).toBeInTheDocument();
  });

  it("shows an empty state when no definitions exist", async () => {
    api.definitionsList.mockResolvedValue(paginate([]));
    render(<DefinitionsPage />);
    expect(await screen.findByText(/No checklist definitions/i)).toBeInTheDocument();
  });

  it("links to the new-definition route", async () => {
    api.definitionsList.mockResolvedValue(paginate([]));
    render(<DefinitionsPage />);
    await screen.findByText(/No checklist definitions/i);
    const link = screen.getByRole("link", { name: /new definition/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/iig-checklists/new"));
  });

  it("redirects to signin on 401/403", async () => {
    api.definitionsList.mockRejectedValue(new ApiError(403, "Forbidden"));
    render(<DefinitionsPage />);
    await vi.waitFor(() => expect(nav.push).toHaveBeenCalledWith("/signin"));
  });
});

describe("NewDefinitionPage — create", () => {
  it("creates a definition and navigates to its detail page", async () => {
    const user = userEvent.setup();
    api.definitionsCreate.mockResolvedValue(makeChecklistDefinition({ public_id: "new-def-1" }));
    render(<NewDefinitionPage />);

    await user.type(screen.getByLabelText(/^Code$/i), "NEW-DEF");
    await user.type(screen.getByLabelText(/^Title$/i), "New Definition");
    await user.click(screen.getByRole("button", { name: /create/i }));

    await vi.waitFor(() =>
      expect(nav.push).toHaveBeenCalledWith(expect.stringContaining("new-def-1"))
    );
  });

  it("shows a form error when creation fails", async () => {
    const user = userEvent.setup();
    api.definitionsCreate.mockRejectedValue(new ApiError(400, "Code already exists."));
    render(<NewDefinitionPage />);

    await user.type(screen.getByLabelText(/^Code$/i), "DUP");
    await user.type(screen.getByLabelText(/^Title$/i), "Dup");
    await user.click(screen.getByRole("button", { name: /create/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Code already exists/i);
  });

  it("shows a warning that platform-master scope requires special authorization", async () => {
    const user = userEvent.setup();
    render(<NewDefinitionPage />);
    await user.selectOptions(screen.getByLabelText(/^Scope$/i), "platform_master");
    expect(screen.getByText(/requires a separate, explicit platform-level authorization/i)).toBeInTheDocument();
  });

  it("shows a clear denial message (not a signin redirect) when platform-master creation is denied", async () => {
    const user = userEvent.setup();
    api.definitionsCreate.mockRejectedValue(new ApiError(403, "Forbidden"));
    render(<NewDefinitionPage />);

    await user.type(screen.getByLabelText(/^Code$/i), "PLATFORM-ATTEMPT");
    await user.type(screen.getByLabelText(/^Title$/i), "Attempt");
    await user.selectOptions(screen.getByLabelText(/^Scope$/i), "platform_master");
    await user.click(screen.getByRole("button", { name: /create/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /requires a separate, explicit platform-level authorization/i
    );
    expect(nav.push).not.toHaveBeenCalledWith("/signin");
  });

  it("redirects to signin on 401 (unauthenticated), not on 403 (unauthorized)", async () => {
    const user = userEvent.setup();
    api.definitionsCreate.mockRejectedValue(new ApiError(401, "Unauthenticated"));
    render(<NewDefinitionPage />);

    await user.type(screen.getByLabelText(/^Code$/i), "X");
    await user.type(screen.getByLabelText(/^Title$/i), "X");
    await user.click(screen.getByRole("button", { name: /create/i }));

    await vi.waitFor(() => expect(nav.push).toHaveBeenCalledWith("/signin"));
  });
});

describe("DefinitionDetailPage — versions", () => {
  it("shows the definition and its versions", async () => {
    api.definitionsGet.mockResolvedValue(makeChecklistDefinition());
    api.versionsListForDefinition.mockResolvedValue(
      paginate([makeChecklistVersion({ version_number: 1, status: "draft" })])
    );
    render(<DefinitionDetailPage />);

    expect(await screen.findByText("IIG Oral Solid (synthetic)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "v1" })).toBeInTheDocument();
    expect(screen.getByText("draft", { exact: true })).toBeInTheDocument();
  });

  it("hides 'create new version' while a draft/returned version already exists", async () => {
    api.definitionsGet.mockResolvedValue(makeChecklistDefinition());
    api.versionsListForDefinition.mockResolvedValue(
      paginate([makeChecklistVersion({ status: "draft" })])
    );
    render(<DefinitionDetailPage />);
    await screen.findByText("IIG Oral Solid (synthetic)");
    expect(screen.queryByRole("button", { name: /create new version/i })).not.toBeInTheDocument();
  });

  it("shows a not-found message on 404", async () => {
    api.definitionsGet.mockRejectedValue(new ApiError(404, "Not found"));
    api.versionsListForDefinition.mockResolvedValue(paginate([]));
    render(<DefinitionDetailPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
  });
});

describe("VersionDetailPage — lifecycle actions", () => {
  it("shows a submit-review action for a draft version", async () => {
    api.versionsGet.mockResolvedValue(makeChecklistVersion({ status: "draft" }));
    render(<VersionDetailPage />);
    expect(await screen.findByRole("button", { name: /submit for review/i })).toBeInTheDocument();
  });

  it("shows approve and reject actions for an under-review version, never execution UI", async () => {
    api.versionsGet.mockResolvedValue(makeChecklistVersion({ status: "under_review" }));
    render(<VersionDetailPage />);
    expect(await screen.findByRole("button", { name: /^approve$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reject$/i })).toBeInTheDocument();
    expect(screen.queryByText(/checklist response/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/calculation outcome/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /answer/i })).not.toBeInTheDocument();
  });

  it("requires a reason before returning a version", async () => {
    const user = userEvent.setup();
    api.versionsGet.mockResolvedValue(makeChecklistVersion({ status: "under_review" }));
    render(<VersionDetailPage />);
    await user.click(await screen.findByRole("button", { name: /return for edits/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/return reason is required/i);
    expect(api.versionsReturn).not.toHaveBeenCalled();
  });

  it("renders sections and questions read-only", async () => {
    api.versionsGet.mockResolvedValue(
      makeChecklistVersion({
        status: "draft",
        sections: [
          makeChecklistSection({
            title: "Section 1",
            questions: [
              {
                public_id: "q1",
                code: "Q-1",
                question_text: "Is this synthetic?",
                display_order: 1,
                answer_type: "yes_no",
                data_source_classification: "user_required",
                criticality: "low",
                required: true,
              },
            ],
          }),
        ],
      })
    );
    render(<VersionDetailPage />);
    expect(await screen.findByText(/Is this synthetic\?/i)).toBeInTheDocument();
  });

  it("shows an activate action for an approved version", async () => {
    api.versionsGet.mockResolvedValue(makeChecklistVersion({ status: "approved" }));
    render(<VersionDetailPage />);
    expect(await screen.findByRole("button", { name: /^activate$/i })).toBeInTheDocument();
  });

  it("shows a platform-master mutation-authorization notice for platform-master content", async () => {
    api.versionsGet.mockResolvedValue(
      makeChecklistVersion({ status: "draft", scope_type: "platform_master" })
    );
    render(<VersionDetailPage />);
    expect(
      await screen.findByText(/requires a separate, explicit platform-level authorization/i)
    ).toBeInTheDocument();
  });

  it("does not show the platform-master notice for tenant-scoped content", async () => {
    api.versionsGet.mockResolvedValue(
      makeChecklistVersion({ status: "draft", scope_type: "tenant" })
    );
    render(<VersionDetailPage />);
    await screen.findByRole("button", { name: /submit for review/i });
    expect(
      screen.queryByText(/requires a separate, explicit platform-level authorization/i)
    ).not.toBeInTheDocument();
  });

  it("shows a lifecycle-action denial inline (not a signin redirect) when mutation is denied", async () => {
    const user = userEvent.setup();
    api.versionsGet.mockResolvedValue(
      makeChecklistVersion({ status: "draft", scope_type: "platform_master" })
    );
    api.versionsSubmitReview.mockRejectedValue(new ApiError(403, "Forbidden"));
    render(<VersionDetailPage />);
    await user.click(await screen.findByRole("button", { name: /submit for review/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/failed|permission|forbidden/i);
    expect(nav.push).not.toHaveBeenCalledWith("/signin");
  });
});
