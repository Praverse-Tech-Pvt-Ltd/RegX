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

import {
  makeAssessmentPreview,
  makeChecklistDefinition,
  makeChecklistVersion,
  makeDocument,
  makeFdaRelease,
  makeFormulationComponent,
  makeFormulationVersion,
  makeLocator,
  makeOrangeBookProduct,
  makeProduct,
  makeAffectedRecord,
  makeReconciliationReport,
  makeSubstanceMapping,
  makeTerminologyMapping,
  makeVersion,
  paginate,
} from "./fixtures";

const nav = vi.hoisted(() => ({
  push: vi.fn(),
  tenant: "alpha",
  publicId: "doc-public-0001",
  versionPublicId: "version-public-0001",
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
  list: vi.fn(),
  create: vi.fn(),
  get: vi.fn(),
  versions: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
  versionStatus: vi.fn(),
  locators: vi.fn(),
}));

const fdaApi = vi.hoisted(() => ({
  releasesList: vi.fn(),
  releasesGet: vi.fn(),
  releasesReconciliationJson: vi.fn(),
  orangeBookSearch: vi.fn(),
  productsGet: vi.fn(),
  versionsGet: vi.fn(),
  versionsList: vi.fn(),
  componentsList: vi.fn(),
  dosingRegimensList: vi.fn(),
  mappingsList: vi.fn(),
  mappingsGet: vi.fn(),
  mappingsAffectedRecords: vi.fn(),
  preview: vi.fn(),
}));

const checklistApi = vi.hoisted(() => ({
  definitionsList: vi.fn(),
  definitionsGet: vi.fn(),
  versionsListForDefinition: vi.fn(),
  versionsGet: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    documents: { ...actual.documents, ...api },
    fdaData: {
      releases: {
        ...actual.fdaData.releases,
        list: fdaApi.releasesList,
        get: fdaApi.releasesGet,
        reconciliationJson: fdaApi.releasesReconciliationJson,
      },
      orangeBook: { ...actual.fdaData.orangeBook, search: fdaApi.orangeBookSearch },
      mappings: {
        ...actual.fdaData.mappings,
        list: fdaApi.mappingsList,
        get: fdaApi.mappingsGet,
        affectedRecords: fdaApi.mappingsAffectedRecords,
      },
    },
    formulations: {
      ...actual.formulations,
      products: { ...actual.formulations.products, get: fdaApi.productsGet },
      versions: {
        ...actual.formulations.versions,
        get: fdaApi.versionsGet,
        list: fdaApi.versionsList,
      },
      components: { ...actual.formulations.components, list: fdaApi.componentsList },
      dosingRegimens: { ...actual.formulations.dosingRegimens, list: fdaApi.dosingRegimensList },
    },
    iidAssessments: { ...actual.iidAssessments, preview: fdaApi.preview },
    iigChecklists: {
      definitions: {
        ...actual.iigChecklists.definitions,
        list: checklistApi.definitionsList,
        get: checklistApi.definitionsGet,
      },
      versions: {
        ...actual.iigChecklists.versions,
        listForDefinition: checklistApi.versionsListForDefinition,
        get: checklistApi.versionsGet,
      },
    },
  };
});

import SignInPage from "@/app/signin/page";
import DocumentsPage from "@/app/documents/page";
import DocumentDetailPage from "@/app/documents/[publicId]/page";
import FdaReleasesPage from "@/app/fda-data/releases/page";
import NewReleasePage from "@/app/fda-data/releases/new/page";
import FdaReleaseDetailPage from "@/app/fda-data/releases/[publicId]/page";
import ReconciliationPage from "@/app/fda-data/releases/[publicId]/reconciliation/page";
import MappingsPage from "@/app/fda-data/mappings/page";
import MappingDetailPage from "@/app/fda-data/mappings/[publicId]/page";
import OrangeBookSearchPage from "@/app/fda-data/orange-book/page";
import FormulationDetailPage from "@/app/formulations/[publicId]/page";
import VersionDetailPage from "@/app/formulations/[publicId]/versions/[versionPublicId]/page";
import IidPreviewPage from "@/app/iid-assessments/preview/page";
import ChecklistDefinitionsPage from "@/app/iig-checklists/page";
import ChecklistDefinitionDetailPage from "@/app/iig-checklists/[publicId]/page";
import ChecklistVersionDetailPage from "@/app/iig-checklists/versions/[versionPublicId]/page";

beforeEach(() => {
  nav.push.mockReset();
  nav.tenant = "alpha";
  nav.publicId = "doc-public-0001";
  nav.versionPublicId = "version-public-0001";
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(fdaApi).forEach((fn) => fn.mockReset());
  Object.values(checklistApi).forEach((fn) => fn.mockReset());
  api.versionStatus.mockResolvedValue({ scan_status: "clean", processing_status: "complete" });
  fdaApi.versionsList.mockResolvedValue(paginate([]));
  fdaApi.componentsList.mockResolvedValue([]);
  fdaApi.dosingRegimensList.mockResolvedValue([]);
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

describe("Accessibility — /fda-data/releases", () => {
  it("has no serious or critical automated violations in the release inventory", async () => {
    fdaApi.releasesList.mockResolvedValue(paginate([makeFdaRelease()]));
    const { container } = render(<FdaReleasesPage />);
    await screen.findByRole("link", { name: "Synthetic FDA IID" });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("has no serious or critical automated violations in the registration form", async () => {
    const { container } = render(<NewReleasePage />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /fda-data/releases/{public_id}", () => {
  it("has no serious or critical automated violations, including lifecycle action buttons", async () => {
    fdaApi.releasesGet.mockResolvedValue(makeFdaRelease({ status: "under_review" }));
    const { container } = render(<FdaReleaseDetailPage />);
    await screen.findByRole("button", { name: /^approve$/i });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /fda-data/orange-book", () => {
  it("has no serious or critical automated violations in the search form and results", async () => {
    const user = userEvent.setup();
    fdaApi.orangeBookSearch.mockResolvedValue(paginate([makeOrangeBookProduct()]));
    const { container } = render(<OrangeBookSearchPage />);
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await screen.findByText("Synthacet");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /formulations/{public_id}", () => {
  it("has no serious or critical automated violations, including the reference-selection form", async () => {
    nav.publicId = "product-public-0001";
    const user = userEvent.setup();
    fdaApi.productsGet.mockResolvedValue(makeProduct());
    const { container } = render(<FormulationDetailPage />);
    await user.click(await screen.findByRole("button", { name: /select reference product/i }));
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /iid-assessments/preview", () => {
  it("has no serious or critical automated violations in the empty form", async () => {
    const { container } = render(<IidPreviewPage />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("has no serious or critical automated violations in the calculation-result view", async () => {
    const user = userEvent.setup();
    fdaApi.preview.mockResolvedValue(makeAssessmentPreview());
    const { container } = render(<IidPreviewPage />);

    await user.type(screen.getByLabelText(/ingredient id/i), "ing-1");
    await user.type(screen.getByLabelText(/active fda release id/i), "rel-1");
    await user.type(screen.getByLabelText(/^route code/i), "oral");
    await user.type(screen.getByLabelText(/dosage form code/i), "tablet");
    await user.type(screen.getByLabelText(/proposed quantity per unit/i), "30");
    await user.type(screen.getByLabelText(/total dosage-unit weight/i), "500");
    await user.click(screen.getByRole("button", { name: /run preview/i }));

    await screen.findByRole("status");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("the warning/error summary uses an accessible live region", async () => {
    const user = userEvent.setup();
    fdaApi.preview.mockResolvedValue(
      makeAssessmentPreview({
        decision_status: "EXCEEDS_IID_PRECEDENT",
        decision_note: "Proposed amount per dosage unit exceeds the selected IID potency precedent.",
        escalation_required: true,
      }),
    );
    render(<IidPreviewPage />);
    await user.type(screen.getByLabelText(/ingredient id/i), "ing-1");
    await user.type(screen.getByLabelText(/active fda release id/i), "rel-1");
    await user.type(screen.getByLabelText(/^route code/i), "oral");
    await user.type(screen.getByLabelText(/dosage form code/i), "tablet");
    await user.type(screen.getByLabelText(/proposed quantity per unit/i), "999");
    await user.type(screen.getByLabelText(/total dosage-unit weight/i), "1500");
    await user.click(screen.getByRole("button", { name: /run preview/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/exceeds/i);
  });
});

describe("Accessibility — /fda-data/releases/{public_id}/reconciliation", () => {
  it("has no serious or critical automated violations, table headers are proper th scope", async () => {
    fdaApi.releasesReconciliationJson.mockResolvedValue(makeReconciliationReport());
    const { container } = render(<ReconciliationPage />);
    await screen.findByText("row:0");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
    for (const header of screen.getAllByRole("columnheader")) {
      expect(header).toHaveAttribute("scope", "col");
    }
  });
});

describe("Accessibility — /fda-data/mappings", () => {
  it("has no serious or critical automated violations in the list view", async () => {
    fdaApi.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    const { container } = render(<MappingsPage />);
    await screen.findByText("ORAL");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("the approve/reject confirmation dialog traps focus semantics and has no violations", async () => {
    const user = userEvent.setup();
    fdaApi.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    const { container } = render(<MappingsPage />);
    await screen.findByText("ORAL");
    await user.click(screen.getByRole("button", { name: /^approve$/i }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName();

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("mapping type tabs expose an accessible tablist and selected state", async () => {
    fdaApi.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    render(<MappingsPage />);
    await screen.findByText("ORAL");
    const tablist = screen.getByRole("tablist", { name: /mapping type/i });
    expect(tablist).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /substance/i })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("the substance mapping table has no violations", async () => {
    fdaApi.mappingsList.mockResolvedValue(paginate([makeSubstanceMapping()]));
    const { container } = render(<MappingsPage />);
    await screen.findByText("SYNTHETIC-ACETAMINOPHEN");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /fda-data/mappings/{public_id}", () => {
  it("the affected-record drill-down has no violations and a data table", async () => {
    nav.publicId = "substance-mapping-0001";
    fdaApi.mappingsGet.mockResolvedValue(makeSubstanceMapping());
    fdaApi.mappingsAffectedRecords.mockResolvedValue(paginate([makeAffectedRecord()]));
    const { container } = render(<MappingDetailPage />);
    await screen.findByText("SYN0001");
    expect(screen.getByRole("table")).toBeInTheDocument();
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /formulations/{public_id}/versions/{version_public_id}", () => {
  it("has no serious or critical automated violations with components and dosing regimen listed", async () => {
    fdaApi.versionsGet.mockResolvedValue(makeFormulationVersion());
    fdaApi.componentsList.mockResolvedValue([makeFormulationComponent()]);
    fdaApi.dosingRegimensList.mockResolvedValue([]);
    const { container } = render(<VersionDetailPage />);
    await screen.findByText("Synthetic Starch");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("the IID preview link is keyboard-focusable and accessibly named", async () => {
    fdaApi.versionsGet.mockResolvedValue(makeFormulationVersion());
    fdaApi.componentsList.mockResolvedValue([]);
    fdaApi.dosingRegimensList.mockResolvedValue([]);
    render(<VersionDetailPage />);
    const link = await screen.findByRole("link", { name: /run iid assessment preview/i });
    expect(link).toHaveAccessibleName();
    link.focus();
    expect(link).toHaveFocus();
  });
});

describe("Accessibility — /iig-checklists", () => {
  it("has no serious or critical automated violations in the definition list", async () => {
    checklistApi.definitionsList.mockResolvedValue(paginate([makeChecklistDefinition()]));
    const { container } = render(<ChecklistDefinitionsPage />);
    await screen.findByRole("link", { name: "IIG-ORAL-SOLID" });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /iig-checklists/{public_id}", () => {
  it("has no serious or critical automated violations in the version list", async () => {
    nav.publicId = "checklist-def-public-0001";
    checklistApi.definitionsGet.mockResolvedValue(makeChecklistDefinition());
    checklistApi.versionsListForDefinition.mockResolvedValue(
      paginate([makeChecklistVersion()]),
    );
    const { container } = render(<ChecklistDefinitionDetailPage />);
    await screen.findByText("IIG Oral Solid (synthetic)");
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("Accessibility — /iig-checklists/versions/{version_public_id}", () => {
  it("has no serious or critical automated violations with lifecycle action buttons shown", async () => {
    checklistApi.versionsGet.mockResolvedValue(
      makeChecklistVersion({ status: "under_review" }),
    );
    const { container } = render(<ChecklistVersionDetailPage />);
    await screen.findByRole("button", { name: /^approve$/i });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
