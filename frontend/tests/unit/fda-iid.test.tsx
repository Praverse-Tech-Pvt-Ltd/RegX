import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  makeAssessmentPreview,
  makeFdaRelease,
  makeFormulationVersion,
  makeMatchCandidate,
  makeOrangeBookProduct,
  makeProduct,
  paginate,
} from "./fixtures";

const nav = vi.hoisted(() => ({
  push: vi.fn(),
  tenant: "alpha",
  publicId: "fda-release-public-0001",
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
  releasesList: vi.fn(),
  releasesGet: vi.fn(),
  releasesRegister: vi.fn(),
  releasesSubmitReview: vi.fn(),
  releasesApprove: vi.fn(),
  releasesActivate: vi.fn(),
  orangeBookSearch: vi.fn(),
  productsList: vi.fn(),
  productsCreate: vi.fn(),
  productsGet: vi.fn(),
  productsSelectReference: vi.fn(),
  versionsCreate: vi.fn(),
  componentsCreate: vi.fn(),
  dosingRegimensCreate: vi.fn(),
  preview: vi.fn(),
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
        reconciliationJson: vi.fn(),
        reconciliationCsvUrl: actual.fdaData.releases.reconciliationCsvUrl,
      },
      orangeBook: { search: api.orangeBookSearch },
    },
    formulations: {
      products: {
        list: api.productsList,
        get: api.productsGet,
        create: api.productsCreate,
        selectReference: api.productsSelectReference,
      },
      versions: { create: api.versionsCreate, get: vi.fn() },
      components: { create: api.componentsCreate },
      dosingRegimens: { create: api.dosingRegimensCreate },
    },
    iidAssessments: { preview: api.preview, snapshot: vi.fn() },
  };
});

import FdaReleasesPage from "@/app/fda-data/releases/page";
import FdaReleaseDetailPage from "@/app/fda-data/releases/[publicId]/page";
import OrangeBookSearchPage from "@/app/fda-data/orange-book/page";
import FormulationDetailPage from "@/app/formulations/[publicId]/page";
import IidPreviewPage from "@/app/iid-assessments/preview/page";

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

  it("registers a new release via the form and reloads the list", async () => {
    const user = userEvent.setup();
    api.releasesList.mockResolvedValue(paginate([]));
    api.releasesRegister.mockResolvedValue(makeFdaRelease());
    render(<FdaReleasesPage />);
    await screen.findByText(/No FDA data-source releases/i);

    await user.click(screen.getByRole("button", { name: /register release/i }));
    await user.type(screen.getByLabelText(/source name/i), "Synthetic IID");
    await user.type(screen.getByLabelText(/official source reference/i), "synthetic://ref");
    await user.click(screen.getByRole("button", { name: /^register$/i }));

    expect(api.releasesRegister).toHaveBeenCalledWith(
      "alpha",
      expect.objectContaining({ source_name: "Synthetic IID" }),
    );
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
          unit_conversion: { status: "OK", ok: true },
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
});
