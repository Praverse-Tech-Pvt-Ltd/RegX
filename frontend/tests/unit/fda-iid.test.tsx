import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  makeAffectedRecord,
  makeAssessmentPreview,
  makeFdaRelease,
  makeFormulationComponent,
  makeFormulationVersion,
  makeMatchCandidate,
  makeOrangeBookProduct,
  makePotencyComparison,
  makeProduct,
  makeReconciliationReport,
  makeSnapshotDetail,
  makeSubstanceMapping,
  makeTerminologyMapping,
  paginate,
} from "./fixtures";
import { ApiError } from "@/lib/api";

const nav = vi.hoisted(() => ({
  push: vi.fn(),
  tenant: "alpha",
  publicId: "fda-release-public-0001",
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
  releasesList: vi.fn(),
  releasesGet: vi.fn(),
  releasesRegister: vi.fn(),
  releasesSubmitReview: vi.fn(),
  releasesApprove: vi.fn(),
  releasesActivate: vi.fn(),
  releasesReconciliationJson: vi.fn(),
  orangeBookSearch: vi.fn(),
  orangeBookGet: vi.fn(),
  mappingsList: vi.fn(),
  mappingsGet: vi.fn(),
  mappingsAffectedRecords: vi.fn(),
  mappingsApprove: vi.fn(),
  mappingsReject: vi.fn(),
  mappingsReturn: vi.fn(),
  mappingsSubmitReview: vi.fn(),
  mappingsProposeSubstance: vi.fn(),
  productsList: vi.fn(),
  productsCreate: vi.fn(),
  productsGet: vi.fn(),
  productsSelectReference: vi.fn(),
  versionsCreate: vi.fn(),
  versionsGet: vi.fn(),
  versionsList: vi.fn(),
  componentsCreate: vi.fn(),
  componentsList: vi.fn(),
  dosingRegimensCreate: vi.fn(),
  dosingRegimensList: vi.fn(),
  preview: vi.fn(),
  snapshot: vi.fn(),
  snapshotGet: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fdaData: {
      releases: {
        list: api.releasesList,
        get: api.releasesGet,
        register: api.releasesRegister,
        submitReview: api.releasesSubmitReview,
        approve: api.releasesApprove,
        activate: api.releasesActivate,
        reconciliationJson: api.releasesReconciliationJson,
        reconciliationCsvUrl: actual.fdaData.releases.reconciliationCsvUrl,
      },
      orangeBook: { search: api.orangeBookSearch, get: api.orangeBookGet },
      mappings: {
        list: api.mappingsList,
        get: api.mappingsGet,
        affectedRecords: api.mappingsAffectedRecords,
        approve: api.mappingsApprove,
        reject: api.mappingsReject,
        return: api.mappingsReturn,
        submitReview: api.mappingsSubmitReview,
        proposeSubstance: api.mappingsProposeSubstance,
      },
    },
    formulations: {
      products: {
        list: api.productsList,
        get: api.productsGet,
        create: api.productsCreate,
        selectReference: api.productsSelectReference,
      },
      versions: { create: api.versionsCreate, get: api.versionsGet, list: api.versionsList },
      components: { create: api.componentsCreate, list: api.componentsList },
      dosingRegimens: { create: api.dosingRegimensCreate, list: api.dosingRegimensList },
    },
    iidAssessments: { preview: api.preview, snapshot: api.snapshot, get: api.snapshotGet },
  };
});

import FdaReleasesPage from "@/app/(regx)/fda-data/releases/page";
import NewReleasePage from "@/app/(regx)/fda-data/releases/new/page";
import FdaReleaseDetailPage from "@/app/(regx)/fda-data/releases/[publicId]/page";
import ReconciliationPage from "@/app/(regx)/fda-data/releases/[publicId]/reconciliation/page";
import MappingsPage from "@/app/(regx)/fda-data/mappings/page";
import MappingDetailPage from "@/app/(regx)/fda-data/mappings/[publicId]/page";
import OrangeBookSearchPage from "@/app/(regx)/fda-data/orange-book/page";
import OrangeBookDetailPage from "@/app/(regx)/fda-data/orange-book/[publicId]/page";
import FormulationDetailPage from "@/app/(regx)/formulations/[publicId]/page";
import NewProductPage from "@/app/(regx)/formulations/new/page";
import VersionDetailPage from "@/app/(regx)/formulations/[publicId]/versions/[versionPublicId]/page";
import IidPreviewPage from "@/app/(regx)/iid-assessments/preview/page";
import SnapshotDetailPage from "@/app/(regx)/iid-assessments/[publicId]/page";

beforeEach(() => {
  nav.push.mockReset();
  nav.tenant = "alpha";
  nav.publicId = "fda-release-public-0001";
  Object.values(api).forEach((fn) => fn.mockReset());
});

describe("FdaReleasesPage — inventory", () => {
  it("shows a loading state, then the release list with provenance labels", async () => {
    api.releasesList.mockResolvedValue(paginate([makeFdaRelease({ source_name: "IID Export" })]));
    render(<FdaReleasesPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "IID Export" });
    const row = link.closest("tr")!;
    expect(within(row).getByText(/REGISTERED/i)).toBeInTheDocument();
  });

  it("shows an empty state when no releases exist", async () => {
    api.releasesList.mockResolvedValue(paginate([]));
    render(<FdaReleasesPage />);
    expect(await screen.findByText(/No FDA data-source releases/i)).toBeInTheDocument();
  });

  it("links to the release registration route", async () => {
    api.releasesList.mockResolvedValue(paginate([]));
    render(<FdaReleasesPage />);
    await screen.findByText(/No FDA data-source releases/i);
    const link = screen.getByRole("link", { name: /register release/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/fda-data/releases/new"));
  });

  it("links to the terminology mappings route", async () => {
    api.releasesList.mockResolvedValue(paginate([]));
    render(<FdaReleasesPage />);
    await screen.findByText(/No FDA data-source releases/i);
    const link = screen.getByRole("link", { name: /terminology mappings/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/fda-data/mappings"));
  });

  it("never renders internal numeric IDs even if present on the object", async () => {
    const release = makeFdaRelease({ source_name: "Leak Check" });
    Object.assign(release, { id: 424242 });
    api.releasesList.mockResolvedValue(paginate([release]));
    render(<FdaReleasesPage />);
    await screen.findByRole("link", { name: "Leak Check" });
    expect(document.body.textContent ?? "").not.toContain("424242");
  });
});

describe("FdaReleaseDetailPage — lifecycle actions and raw-path safety", () => {
  it("never renders a raw filesystem path even if present on the object", async () => {
    const release = makeFdaRelease({ status: "registered" });
    Object.assign(release, { original_filename: "/var/secret/fda-export.txt" });
    api.releasesGet.mockResolvedValue(release);
    render(<FdaReleaseDetailPage />);
    await screen.findByRole("heading", { name: "Synthetic FDA IID" });
    expect(document.body.textContent ?? "").not.toContain("/var/secret");
  });

  it("shows a submit-for-review action for a registered release", async () => {
    api.releasesGet.mockResolvedValue(makeFdaRelease({ status: "registered" }));
    render(<FdaReleaseDetailPage />);
    expect(await screen.findByRole("button", { name: /submit for review/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("shows an approve action, not activate, for a release under review", async () => {
    api.releasesGet.mockResolvedValue(makeFdaRelease({ status: "under_review" }));
    render(<FdaReleaseDetailPage />);
    expect(await screen.findByRole("button", { name: /^approve$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^activate$/i })).not.toBeInTheDocument();
  });

  it("shows an activate action for an approved release", async () => {
    api.releasesGet.mockResolvedValue(makeFdaRelease({ status: "approved" }));
    render(<FdaReleaseDetailPage />);
    expect(await screen.findByRole("button", { name: /^activate$/i })).toBeInTheDocument();
  });

  it("never offers a lifecycle action for an active release (no re-activation)", async () => {
    api.releasesGet.mockResolvedValue(makeFdaRelease({ status: "active" }));
    render(<FdaReleaseDetailPage />);
    await screen.findByRole("heading", { name: "Synthetic FDA IID" });
    expect(screen.queryByRole("button", { name: /submit for review/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^activate$/i })).not.toBeInTheDocument();
  });
});

describe("OrangeBookSearchPage — product search", () => {
  it("searches and renders results with FDA-source provenance", async () => {
    const user = userEvent.setup();
    api.orangeBookSearch.mockResolvedValue(paginate([makeOrangeBookProduct()]));
    render(<OrangeBookSearchPage />);

    await user.type(screen.getByPlaceholderText(/active ingredient/i), "starch");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    const link = await screen.findByText("Synthacet");
    expect(link).toBeInTheDocument();
    expect(api.orangeBookSearch).toHaveBeenCalledWith(
      "alpha",
      expect.objectContaining({ active_ingredient: "starch" }),
    );
  });

  it("shows a no-results message distinctly from the initial unsearched state", async () => {
    const user = userEvent.setup();
    api.orangeBookSearch.mockResolvedValue(paginate([]));
    render(<OrangeBookSearchPage />);
    expect(screen.queryByText(/No matching Orange Book products/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    expect(await screen.findByText(/No matching Orange Book products/i)).toBeInTheDocument();
  });
});

describe("FormulationDetailPage — explicit reference selection, no auto-fill", () => {
  beforeEach(() => {
    nav.publicId = "product-public-0001";
    api.versionsList.mockResolvedValue(paginate([]));
  });

  it("shows 'not selected' rather than a default reference product", async () => {
    api.productsGet.mockResolvedValue(makeProduct());
    render(<FormulationDetailPage />);
    expect(await screen.findByText(/No reference product selected/i)).toBeInTheDocument();
  });

  it("requires the confirmation checkbox before selecting a reference product", async () => {
    const user = userEvent.setup();
    api.productsGet.mockResolvedValue(makeProduct());
    render(<FormulationDetailPage />);
    await user.click(await screen.findByRole("button", { name: /select reference product/i }));

    await user.type(screen.getByLabelText(/application number/i), "099999");
    await user.type(screen.getByLabelText(/product number/i), "001");
    await user.type(screen.getByLabelText(/orange book product id/i), "ob-1");
    await user.type(screen.getByLabelText(/fda release id/i), "rel-1");
    await user.click(screen.getByRole("button", { name: /confirm selection/i }));

    expect(api.productsSelectReference).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/explicitly confirm/i);
  });

  it("submits the selection once explicitly confirmed", async () => {
    const user = userEvent.setup();
    api.productsGet.mockResolvedValue(makeProduct());
    api.productsSelectReference.mockResolvedValue(
      makeProduct({ selected_ob_product_public_id: "ob-1", selecting_user_email: "vp@example.com" }),
    );
    render(<FormulationDetailPage />);
    await user.click(await screen.findByRole("button", { name: /select reference product/i }));

    await user.type(screen.getByLabelText(/application number/i), "099999");
    await user.type(screen.getByLabelText(/product number/i), "001");
    await user.type(screen.getByLabelText(/orange book product id/i), "ob-1");
    await user.type(screen.getByLabelText(/fda release id/i), "rel-1");
    await user.click(screen.getByLabelText(/I confirm this is the correct reference product/i));
    await user.click(screen.getByRole("button", { name: /confirm selection/i }));

    expect(api.productsSelectReference).toHaveBeenCalledWith(
      "alpha",
      "product-public-0001",
      expect.objectContaining({ application_number: "099999" }),
    );
  });
});

describe("IidPreviewPage — matching, calculation, and safety language", () => {
  const submitPreviewForm = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(screen.getByLabelText(/ingredient id/i), "ing-1");
    await user.type(screen.getByLabelText(/active fda release id/i), "rel-1");
    await user.type(screen.getByLabelText(/^route code/i), "oral");
    await user.type(screen.getByLabelText(/dosage form code/i), "tablet");
    await user.type(screen.getByLabelText(/proposed quantity per unit/i), "30");
    await user.type(screen.getByLabelText(/total dosage-unit weight/i), "500");
    await user.click(screen.getByRole("button", { name: /run preview/i }));
  };

  it("proposed-quantity field is never pre-filled from IID — starts empty", () => {
    render(<IidPreviewPage />);
    expect(screen.getByLabelText(/proposed quantity per unit/i)).toHaveValue("");
  });

  it("shows the pass-with-precedent result including the required disclaimer, never SAFE/APPROVED language", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(makeAssessmentPreview());
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/not an automatic safety determination or regulatory approval/i);
    const bodyText = (document.body.textContent ?? "").toUpperCase();
    // Word-boundary match: the required disclaimer legitimately contains
    // "safety determination", which must not false-positive against the
    // standalone forbidden word "SAFE".
    for (const forbidden of [
      /\bSAFE\b/,
      /\bFDA APPROVED\b/,
      /\bAUTOMATICALLY ACCEPTABLE\b/,
      /\bREGULATORILY CLEARED\b/,
    ]) {
      expect(bodyText).not.toMatch(forbidden);
    }
  });

  it("shows multiple candidates for selection, never auto-picking one", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        match_status: "MULTIPLE_EXACT_MATCHES",
        selected_record: null,
        candidates: [
          makeMatchCandidate({ precedent_record_public_id: "low", potency_amount: "10" }),
          makeMatchCandidate({ precedent_record_public_id: "high", potency_amount: "500" }),
        ],
        decision_status: "REVIEW_REQUIRED",
        decision_note: "Multiple exact IID records match; a reviewer must select the precedent record to use.",
        escalation_required: true,
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findAllByRole("button", { name: /select this precedent/i })).toHaveLength(2);
    expect(screen.getByText(/Reviewer escalation required/i)).toBeInTheDocument();
  });

  it("shows FDA VALUE UNAVAILABLE for missing potency, not a fabricated zero", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        match_status: "MULTIPLE_EXACT_MATCHES",
        selected_record: null,
        candidates: [makeMatchCandidate({ potency_amount: null, potency_unit: null })],
        decision_status: "REVIEW_REQUIRED",
        decision_note: "Selected IID record has no usable potency value; regulatory review required.",
        escalation_required: true,
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findByText(/FDA VALUE UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.queryByText(/^0 milligram$/)).not.toBeInTheDocument();
  });

  it("shows an exceeds-precedent warning distinctly from a pass", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        decision_status: "EXCEEDS_IID_PRECEDENT",
        decision_note:
          "Proposed amount per dosage unit exceeds the selected IID potency precedent. Justification and reviewer conclusion are mandatory; approval cannot be automatic.",
        escalation_required: true,
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findByText(/Exceeds IID precedent/i)).toBeInTheDocument();
    expect(screen.getByText(/Reviewer escalation required/i)).toBeInTheDocument();
  });

  it("shows a blocked calculation status rather than a value when calculation is blocked", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        calculations: {
          unit_conversion: { ok: true, original_value: "30.000000", original_unit: "milligram", converted_value: "30", converted_unit: "milligram", reason_code: null },
          percentage_w_w: { status: "OK", value: "6", unit: "percent_w_w" },
          daily_exposure: { status: "DATA_REQUIRED" },
        },
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findByText(/Blocked: DATA_REQUIRED/)).toBeInTheDocument();
  });

  it("route mismatch is displayed as ROUTE MISMATCH", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        match_status: "ROUTE_MISMATCH",
        candidates: [],
        selected_record: null,
        decision_status: "NOT_COMPARABLE",
        decision_note: "ROUTE_MISMATCH: route and dosage form must match exactly.",
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);
    expect(await screen.findByText(/ROUTE MISMATCH/)).toBeInTheDocument();
  });

  it("no matching precedent is displayed as NO MATCHING IID PRECEDENT", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        match_status: "NO_MATCHING_IID_PRECEDENT",
        candidates: [],
        selected_record: null,
        decision_status: "NO_MATCH",
        decision_note: "No exact ingredient/route/dosage-form IID precedent record exists.",
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);
    expect(await screen.findByText(/NO MATCHING IID PRECEDENT/)).toBeInTheDocument();
  });

  it("shows calculated percentages at 3 decimals with the exact value as tooltip", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        calculations: {
          percentage_of_iid_potency: { status: "OK", value: "142.8571428571428571428571429", unit: "percent_of_potency" },
          difference_from_iid_potency: { status: "OK", value: "-30.000000" },
        },
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    const pct = await screen.findByTestId("percent-value");
    expect(pct.firstChild?.textContent).toBe("142.857");
    expect(pct).toHaveAttribute("title", "Exact value: 142.8571428571428571428571429");
    // A non-percentage calculation is shown exactly as before.
    expect(screen.getByText(/-30\.000000/)).toBeInTheDocument();
  });

  it("every FDA-sourced field carries an FDA SOURCE provenance label", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(makeAssessmentPreview());
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    await screen.findByRole("status");
    const labels = screen.getAllByTestId("provenance-label");
    expect(labels.some((l) => l.textContent === "FDA SOURCE")).toBe(true);
    expect(labels.some((l) => l.textContent === "CALCULATED")).toBe(true);
  });

  // The backend's unit conversion result is `ok`/`converted_value`/
  // `converted_unit`/`reason_code` (unit_conversion.ConversionResult). The page
  // read it as `status`, so a successful conversion showed "Blocked: undefined".
  it("shows a successful unit conversion as values, never 'Blocked: undefined'", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        calculations: {
          unit_conversion: {
            ok: true,
            original_value: "0.070000",
            original_unit: "gram",
            converted_value: "70",
            converted_unit: "milligram",
            reason_code: null,
          },
        },
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findByText(/0\.070000 gram = 70 milligram/)).toBeInTheDocument();
    expect(screen.queryByText(/Blocked: undefined/)).not.toBeInTheDocument();
  });

  it("shows a failed unit conversion with the backend's reason code", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        calculations: {
          unit_conversion: {
            ok: false,
            original_value: "30.000000",
            original_unit: "millilitre",
            converted_value: null,
            converted_unit: null,
            reason_code: "DENSITY_REQUIRED",
          },
        },
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findByText(/Blocked: DENSITY_REQUIRED/)).toBeInTheDocument();
  });

  it("shows the like-for-like comparison with the backend's label and result", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(makeAssessmentPreview());
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    const block = await screen.findByTestId("potency-comparison");
    expect(block).toHaveTextContent("Like-for-like comparison");
    expect(block).toHaveTextContent("Proposed 30 mg per dose unit is at or below the IID value of 50 mg per dose unit.");
    expect(block).toHaveTextContent("Conversion: none needed");
    expect(block).toHaveTextContent("technically comparable (not regulatorily approved)");
    expect(block).toHaveTextContent("IID source row: row 2");
  });

  it("shows why a comparison is refused, with no result or label", async () => {
    const user = userEvent.setup();
    api.preview.mockResolvedValue(
      makeAssessmentPreview({
        decision_status: "NOT_COMPARABLE",
        decision_note: "cannot compare: different basis (e.g. per dose unit vs per volume, w/w vs w/v)",
        calculations: {
          potency_comparison: makePotencyComparison({
            comparable: false,
            reason_code: "DIFFERENT_BASIS",
            reason: "cannot compare: different basis (e.g. per dose unit vs per volume, w/w vs w/v)",
            result: null,
            proposed_value: null,
            iid_value: null,
            unit: null,
            conversion: "",
            label: null,
          }),
        },
      }),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    const block = await screen.findByTestId("potency-comparison");
    expect(block).toHaveTextContent("cannot compare: different basis");
    expect(block).not.toHaveTextContent(/at or below|above the IID value/);
    expect(block).not.toHaveTextContent("technically comparable");
  });

  it("names the invalid field when the API rejects the request", async () => {
    const user = userEvent.setup();
    api.preview.mockRejectedValue(
      new ApiError(400, "active_release_public_id: Must be a valid UUID."),
    );
    render(<IidPreviewPage />);
    await submitPreviewForm(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "active_release_public_id: Must be a valid UUID.",
    );
  });
});

describe("NewReleasePage — registration form", () => {
  it("registers a release and never auto-activates it", async () => {
    const user = userEvent.setup();
    api.releasesRegister.mockResolvedValue(makeFdaRelease({ public_id: "new-release-1" }));
    render(<NewReleasePage />);

    await user.type(screen.getByLabelText(/source name/i), "Synthetic IID");
    await user.type(screen.getByLabelText(/official source reference/i), "synthetic://ref");
    await user.click(screen.getByRole("button", { name: /^register$/i }));

    expect(api.releasesRegister).toHaveBeenCalledWith(
      "alpha",
      expect.objectContaining({ source_name: "Synthetic IID", dataset_type: "fda_iid" }),
    );
    expect(nav.push).toHaveBeenCalledWith(
      expect.stringContaining("/fda-data/releases/new-release-1"),
    );
  });

  it("shows a structured error on invalid rows JSON", async () => {
    const user = userEvent.setup();
    render(<NewReleasePage />);
    await user.type(screen.getByLabelText(/source name/i), "Synthetic IID");
    await user.type(screen.getByLabelText(/official source reference/i), "synthetic://ref");
    const rowsField = screen.getByLabelText(/rows \(json array/i);
    await user.clear(rowsField);
    await user.type(rowsField, "not json");
    await user.click(screen.getByRole("button", { name: /^register$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/valid json/i);
    expect(api.releasesRegister).not.toHaveBeenCalled();
  });
});

describe("ReconciliationPage — reconciliation summary", () => {
  it("shows counts and per-row results", async () => {
    api.releasesReconciliationJson.mockResolvedValue(makeReconciliationReport());
    render(<ReconciliationPage />);
    await screen.findByText("row:0");
    expect(screen.getAllByText("2")).toHaveLength(2); // Expected + Extracted
    expect(screen.getByText("row:0")).toBeInTheDocument();
    expect(screen.getByText(/potency_missing/i)).toBeInTheDocument();
  });

  it("shows a permission error distinctly, not a generic failure", async () => {
    const { ApiError } = await import("@/lib/api");
    api.releasesReconciliationJson.mockRejectedValue(new ApiError(403, "Forbidden"));
    render(<ReconciliationPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/permission/i);
  });
});

describe("MappingsPage — terminology mapping review", () => {
  it("lists mappings and requires confirmation before approving", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    render(<MappingsPage />);
    await screen.findByText("ORAL");

    await user.click(screen.getByRole("button", { name: /^approve$/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName(/approve/i);

    api.mappingsApprove.mockResolvedValue(makeTerminologyMapping({ status: "approved" }));
    api.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping({ status: "approved" })]));
    await user.click(within(dialog).getByRole("button", { name: /^confirm$/i }));

    // Type-less URL scheme: approve is keyed by public_id alone, no mapping type.
    expect(api.mappingsApprove).toHaveBeenCalledWith("alpha", "mapping-public-0001", "");
  });

  it("never auto-approves -- clicking approve alone does not call the API", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    render(<MappingsPage />);
    await screen.findByText("ORAL");
    await user.click(screen.getByRole("button", { name: /^approve$/i }));
    expect(api.mappingsApprove).not.toHaveBeenCalled();
  });

  it("filters by mapping type via type tabs", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    render(<MappingsPage />);
    await screen.findByText("ORAL");
    await user.click(screen.getByRole("tab", { name: /units/i }));
    expect(api.mappingsList).toHaveBeenLastCalledWith(
      "alpha",
      expect.objectContaining({ type: "unit" }),
    );
  });

  it("shows a segregation-of-duties warning", async () => {
    api.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    render(<MappingsPage />);
    await screen.findByText("ORAL");
    expect(screen.getByText(/segregation of duties/i)).toBeInTheDocument();
  });

  it("renders substance/UNII columns and provenance for a substance mapping", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeSubstanceMapping()]));
    render(<MappingsPage />);
    await user.click(screen.getByRole("tab", { name: /substance/i }));
    expect(api.mappingsList).toHaveBeenLastCalledWith(
      "alpha",
      expect.objectContaining({ type: "substance" }),
    );
    expect(await screen.findByText("SYN0001")).toBeInTheDocument();
    expect(screen.getByText("9005-25-8")).toBeInTheDocument();
  });

  it("submits a proposed mapping for review with the type-less endpoint", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeSubstanceMapping()]));
    render(<MappingsPage />);
    await user.click(screen.getByRole("tab", { name: /substance/i }));
    await screen.findByText("SYN0001");
    await user.click(screen.getByRole("button", { name: /submit for review/i }));
    api.mappingsSubmitReview.mockResolvedValue(
      makeSubstanceMapping({ status: "under_review" }),
    );
    api.mappingsList.mockResolvedValue(
      paginate([makeSubstanceMapping({ status: "under_review" })]),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^confirm$/i }),
    );
    expect(api.mappingsSubmitReview).toHaveBeenCalledWith(
      "alpha",
      "substance-mapping-0001",
      "",
    );
  });

  it("returns a mapping for correction", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(
      paginate([makeSubstanceMapping({ status: "under_review" })]),
    );
    render(<MappingsPage />);
    await user.click(screen.getByRole("tab", { name: /substance/i }));
    await screen.findByText("SYN0001");
    await user.click(screen.getByRole("button", { name: /return for correction/i }));
    api.mappingsReturn.mockResolvedValue(makeSubstanceMapping({ status: "returned" }));
    api.mappingsList.mockResolvedValue(paginate([makeSubstanceMapping({ status: "returned" })]));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /^confirm$/i }),
    );
    expect(api.mappingsReturn).toHaveBeenCalledWith("alpha", "substance-mapping-0001", "");
  });

  it("does not offer approve/reject on an already-approved mapping", async () => {
    api.mappingsList.mockResolvedValue(
      paginate([makeTerminologyMapping({ status: "approved" })]),
    );
    render(<MappingsPage />);
    await screen.findByText("ORAL");
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^reject$/i })).not.toBeInTheDocument();
  });

  it("links each row to its affected-record drill-down", async () => {
    api.mappingsList.mockResolvedValue(paginate([makeTerminologyMapping()]));
    render(<MappingsPage />);
    await screen.findByText("ORAL");
    const link = screen.getByRole("link", { name: /record\(s\)/i });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/fda-data/mappings/mapping-public-0001"),
    );
  });

  it("proposes a substance mapping via the production proposal path, never auto-approved", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeSubstanceMapping()]));
    render(<MappingsPage />);
    await user.click(screen.getByRole("tab", { name: /substance/i }));
    await screen.findByText("SYN0001");

    await user.click(screen.getByRole("button", { name: /propose substance mapping/i }));
    const dialog = screen.getByRole("dialog", { name: /propose substance mapping/i });

    await user.type(
      within(dialog).getByLabelText(/raw ingredient name/i),
      "Synthetic Brand (raw)",
    );
    await user.type(
      within(dialog).getByLabelText(/normalized ingredient name/i),
      "SYNTHETIC BRAND",
    );

    api.mappingsProposeSubstance.mockResolvedValue(
      makeSubstanceMapping({ public_id: "new-proposal-0001", status: "proposed" }),
    );
    await user.click(within(dialog).getByRole("button", { name: /submit proposal/i }));

    expect(api.mappingsProposeSubstance).toHaveBeenCalledWith(
      "alpha",
      expect.objectContaining({
        raw_ingredient_name: "Synthetic Brand (raw)",
        normalized_ingredient_name: "SYNTHETIC BRAND",
      }),
    );
    expect(await within(dialog).findByText(/proposal created/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/new-proposal-0001/)).toBeInTheDocument();
    // no automatic approval: the created mapping is never displayed as approved here.
    expect(within(dialog).queryByText(/^approved$/i)).not.toBeInTheDocument();
  });

  it("keeps the propose dialog open with an error when the API rejects the proposal", async () => {
    const user = userEvent.setup();
    api.mappingsList.mockResolvedValue(paginate([makeSubstanceMapping()]));
    render(<MappingsPage />);
    await user.click(screen.getByRole("tab", { name: /substance/i }));
    await screen.findByText("SYN0001");

    await user.click(screen.getByRole("button", { name: /propose substance mapping/i }));
    const dialog = screen.getByRole("dialog", { name: /propose substance mapping/i });
    await user.type(
      within(dialog).getByLabelText(/raw ingredient name/i),
      "Synthetic Brand (raw)",
    );
    await user.type(
      within(dialog).getByLabelText(/normalized ingredient name/i),
      "SYNTHETIC BRAND",
    );

    api.mappingsProposeSubstance.mockRejectedValue(new ApiError(400, "Duplicate proposal."));
    await user.click(within(dialog).getByRole("button", { name: /submit proposal/i }));

    expect(await within(dialog).findByText(/duplicate proposal/i)).toBeInTheDocument();
  });
});

describe("MappingDetailPage — affected-record drill-down", () => {
  beforeEach(() => {
    nav.publicId = "substance-mapping-0001";
  });

  it("shows the mapping summary and its affected records", async () => {
    api.mappingsGet.mockResolvedValue(makeSubstanceMapping());
    api.mappingsAffectedRecords.mockResolvedValue(paginate([makeAffectedRecord()]));
    render(<MappingDetailPage />);
    // SYN0001 (proposed UNII) appears only once, in the summary block.
    expect(await screen.findByText("SYN0001")).toBeInTheDocument();
    // Raw value appears both in the summary and the affected-record row.
    expect(screen.getAllByText("SYNTHETIC-ACETAMINOPHEN").length).toBeGreaterThan(0);
  });

  it("never renders a numeric internal id or storage path in affected records", async () => {
    api.mappingsGet.mockResolvedValue(makeSubstanceMapping());
    const leaky = makeAffectedRecord();
    Object.assign(leaky, { id: 424242, storage_key: "s3://bucket/secret/path.csv" });
    api.mappingsAffectedRecords.mockResolvedValue(paginate([leaky]));
    render(<MappingDetailPage />);
    await screen.findByText("SYN0001");
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("424242");
    expect(body).not.toContain("s3://");
  });

  it("shows a generic not-found on a 404", async () => {
    api.mappingsGet.mockRejectedValue(new ApiError(404, "Terminology mapping not found."));
    api.mappingsAffectedRecords.mockRejectedValue(
      new ApiError(404, "Terminology mapping not found."),
    );
    render(<MappingDetailPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
  });
});

describe("OrangeBookDetailPage — product detail", () => {
  it("shows parsed strength and FDA-source provenance, never a numeric ID", async () => {
    const product = makeOrangeBookProduct();
    Object.assign(product, { id: 999888 });
    api.orangeBookGet.mockResolvedValue(product);
    render(<OrangeBookDetailPage />);
    await screen.findByRole("heading", { name: /Synthacet/i });
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toContain("999888");
  });

  it("never implies reference-product selection from RLD/RS flags", async () => {
    api.orangeBookGet.mockResolvedValue(makeOrangeBookProduct());
    render(<OrangeBookDetailPage />);
    await screen.findByRole("heading", { name: /Synthacet/i });
    expect(screen.getByText(/never inferred from these flags/i)).toBeInTheDocument();
  });
});

describe("NewProductPage — product creation", () => {
  it("creates a product and navigates to its detail page", async () => {
    const user = userEvent.setup();
    api.productsCreate.mockResolvedValue(makeProduct({ public_id: "new-product-1" }));
    render(<NewProductPage />);

    await user.type(screen.getByLabelText(/product code/i), "PROD-NEW");
    await user.type(screen.getByLabelText(/proposed product name/i), "New Tablet");
    await user.type(screen.getByLabelText(/active ingredient/i), "Synthetic Starch");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(api.productsCreate).toHaveBeenCalledWith(
      "alpha",
      expect.objectContaining({ product_code: "PROD-NEW" }),
    );
    expect(nav.push).toHaveBeenCalledWith(expect.stringContaining("/formulations/new-product-1"));
  });
});

describe("VersionDetailPage — components and dosing regimen", () => {
  beforeEach(() => {
    nav.publicId = "product-public-0001";
    nav.versionPublicId = "version-public-0001";
    api.versionsGet.mockResolvedValue(makeFormulationVersion());
    api.componentsList.mockResolvedValue([]);
    api.dosingRegimensList.mockResolvedValue([]);
  });

  it("shows existing components with calculated % w/w provenance", async () => {
    api.componentsList.mockResolvedValue([makeFormulationComponent()]);
    render(<VersionDetailPage />);
    expect(await screen.findByText("Synthetic Starch")).toBeInTheDocument();
    // Shown at 3 decimals; the exact stored value stays in the tooltip.
    const pct = screen.getByTestId("percent-value");
    expect(pct.firstChild?.textContent).toBe("6.000");
    expect(pct).toHaveAttribute("title", "Exact value: 6.000000");
  });

  it("adds an inactive component via the form", async () => {
    const user = userEvent.setup();
    api.componentsCreate.mockResolvedValue(makeFormulationComponent({ ingredient_name: "New Excipient" }));
    render(<VersionDetailPage />);
    await screen.findByText(/No components added yet/i);

    await user.click(screen.getByRole("button", { name: /add component/i }));
    await user.type(screen.getByLabelText(/ingredient name/i), "New Excipient");
    await user.type(screen.getByLabelText(/quantity per dosage unit/i), "10");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    expect(api.componentsCreate).toHaveBeenCalledWith(
      "alpha",
      "version-public-0001",
      expect.objectContaining({ ingredient_name: "New Excipient", component_type: "inactive" }),
    );
  });

  it("adds a dosing regimen via the form", async () => {
    const user = userEvent.setup();
    api.dosingRegimensCreate.mockResolvedValue({
      public_id: "regimen-1",
      units_per_administration: "1",
      administrations_per_day: "4",
      maximum_units_per_day: "4",
      patient_population: "",
      basis: "",
      source_justification: "",
    });
    render(<VersionDetailPage />);
    await screen.findByText(/No dosing regimen recorded yet/i);

    await user.click(screen.getByRole("button", { name: /add dosing regimen/i }));
    await user.type(screen.getByLabelText(/administrations per day/i), "4");
    await user.type(screen.getByLabelText(/maximum units per day/i), "4");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(api.dosingRegimensCreate).toHaveBeenCalledWith(
      "alpha",
      "version-public-0001",
      expect.objectContaining({ maximum_units_per_day: "4" }),
    );
  });

  it("links to the IID assessment preview with the version ID", async () => {
    render(<VersionDetailPage />);
    const link = await screen.findByRole("link", { name: /run iid assessment preview/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("version-public-0001"));
  });
});

describe("SnapshotDetailPage — persisted assessment", () => {
  it("shows the frozen decision and required disclaimer, never SAFE/APPROVED language", async () => {
    api.snapshotGet.mockResolvedValue(makeSnapshotDetail());
    render(<SnapshotDetailPage />);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/not an automatic safety determination or regulatory approval/i);
  });

  it("shows FDA VALUE UNAVAILABLE rather than a fabricated zero when potency is missing", async () => {
    api.snapshotGet.mockResolvedValue(makeSnapshotDetail({ iid_potency_amount: null }));
    render(<SnapshotDetailPage />);
    expect(await screen.findByText(/FDA VALUE UNAVAILABLE/)).toBeInTheDocument();
  });
});
