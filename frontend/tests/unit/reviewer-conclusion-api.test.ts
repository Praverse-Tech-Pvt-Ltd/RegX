/**
 * Milestone 4D-4 — wire-level contract for the governed per-response
 * reviewer-conclusion action.
 *
 * `@/lib/api` is deliberately NOT mocked: what is under test is exactly what
 * reaches the backend, so only `fetch` is stubbed and the real request and real
 * mapper run. Mocking the helper would assert nothing about the payload.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, iigChecklists } from "@/lib/api";
import type { ChecklistCapabilities, ChecklistResponseDTO } from "@/lib/api";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const RESPONSE = "resp-conclusion-0001";

const CONCLUSION_URL =
  `/api/regx/v1/iig-checklists/executions/${EXECUTION}` +
  `/responses/${RESPONSE}/reviewer-conclusion/`;

function responseDTO(overrides: Partial<ChecklistResponseDTO> = {}): ChecklistResponseDTO {
  return {
    public_id: RESPONSE,
    question_public_id: "question-conclusion-0001",
    data_source_type_snapshot: "reviewer_confirmed",
    raw_value: { value: "Conclusion text" },
    is_not_applicable: false,
    not_applicable_reason: null,
    entered_by_email: "reviewer@example.com",
    entered_at: "2026-01-01T00:00:00Z",
    confirmed_by_email: null,
    confirmed_at: null,
    override_reason: "",
    system_derived_value: null,
    version: 4,
    ...overrides,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Stub the CSRF preflight `apiRequest` performs before any write. */
function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
    const href = String(url);
    if (href.includes("/auth/csrf/")) return json({ csrfToken: "csrf-token-value" });
    return handler(href, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function postCall(fetchMock: ReturnType<typeof stubFetch>) {
  return fetchMock.mock.calls.find(
    ([, init]) => (init as RequestInit | undefined)?.method === "POST"
  );
}

function bodyOf(init: RequestInit | undefined): Record<string, unknown> {
  return JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("capabilities — 4D4-DEC-012 extension is typed", () => {
  it("exposes can_enter_reviewer_conclusion alongside can_override_response", async () => {
    stubFetch(() => json({ can_override_response: false, can_enter_reviewer_conclusion: true }));

    const caps = await iigChecklists.capabilities(TENANT);

    expect(caps.can_enter_reviewer_conclusion).toBe(true);
    expect(caps.can_override_response).toBe(false);
    // The type carries exactly the approved flags — a compile-time assertion
    // that mirrors the backend's exact-capability-set contract test.
    const exact: ChecklistCapabilities = {
      can_override_response: false,
      can_enter_reviewer_conclusion: true,
    };
    expect(Object.keys(exact).sort()).toEqual([
      "can_enter_reviewer_conclusion",
      "can_override_response",
    ]);
  });
});

describe("responses.reviewerConclusion — exact governed payload", () => {
  it("POSTs exactly raw_value and expected_version on first entry", async () => {
    const fetchMock = stubFetch(() => json(responseDTO({ version: 5 })));

    await iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
      raw_value: { value: "Reviewed and acceptable." },
      expected_version: 4,
    });

    const body = bodyOf(postCall(fetchMock)?.[1] as RequestInit | undefined);
    // Exact set — not a superset. The serializer refuses any unknown field.
    expect(Object.keys(body).sort()).toEqual(["expected_version", "raw_value"]);
    expect(body.raw_value).toEqual({ value: "Reviewed and acceptable." });
    expect(body.expected_version).toBe(4);
  });

  it("carries correction_reason only when amending", async () => {
    const fetchMock = stubFetch(() => json(responseDTO({ version: 6 })));

    await iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
      raw_value: { value: "Amended conclusion." },
      expected_version: 5,
      correction_reason: "Corrected the cited section.",
    });

    const body = bodyOf(postCall(fetchMock)?.[1] as RequestInit | undefined);
    expect(Object.keys(body).sort()).toEqual([
      "correction_reason",
      "expected_version",
      "raw_value",
    ]);
    expect(body.correction_reason).toBe("Corrected the cited section.");
  });

  it("sends expected_version as a JSON integer, never a string or float", async () => {
    const fetchMock = stubFetch(() => json(responseDTO()));

    await iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
      raw_value: { value: "x" },
      expected_version: 3,
    });

    const raw = String((postCall(fetchMock)?.[1] as RequestInit | undefined)?.body);
    const value = bodyOf(postCall(fetchMock)?.[1] as RequestInit | undefined).expected_version;
    expect(typeof value).toBe("number");
    expect(Number.isInteger(value)).toBe(true);
    // `4D4-DEC-013`: "3" and 3.0 are refused by the backend, so neither may
    // appear on the wire. JSON.stringify renders an integer without a decimal.
    expect(raw).toContain('"expected_version":3');
    expect(raw).not.toContain('"expected_version":"3"');
    expect(raw).not.toContain('"expected_version":3.0');
  });

  it("never sends reviewer identity, timestamps, provenance or history", async () => {
    const fetchMock = stubFetch(() => json(responseDTO()));

    await iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
      raw_value: { value: "x" },
      expected_version: 1,
      correction_reason: "r",
    });

    const body = bodyOf(postCall(fetchMock)?.[1] as RequestInit | undefined);
    for (const serverOwned of [
      "entered_by",
      "entered_by_email",
      "entered_at",
      "confirmed_by",
      "confirmed_by_email",
      "confirmed_at",
      "reviewer",
      "reviewer_email",
      "version",
      "history",
      "data_source_type_snapshot",
      "override_reason",
      "system_derived_value",
    ]) {
      expect(body).not.toHaveProperty(serverOwned);
    }
  });

  it("targets the dedicated per-response endpoint, not approve() and not the PATCH", async () => {
    const fetchMock = stubFetch(() => json(responseDTO()));

    await iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
      raw_value: { value: "x" },
      expected_version: 1,
    });

    const writes = fetchMock.mock.calls.filter(([url, init]) => {
      const method = (init as RequestInit | undefined)?.method;
      return (method === "POST" || method === "PATCH") && !String(url).includes("/auth/csrf/");
    });
    expect(writes).toHaveLength(1);
    const url = String(writes[0]?.[0]);
    expect(url).toContain(CONCLUSION_URL);
    expect(url).not.toContain("/approve/");
    expect((writes[0]?.[1] as RequestInit | undefined)?.method).toBe("POST");
  });

  it("sends the tenant header, so the write stays tenant-scoped", async () => {
    const fetchMock = stubFetch(() => json(responseDTO()));

    await iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
      raw_value: { value: "x" },
      expected_version: 1,
    });

    const headers = (postCall(fetchMock)?.[1] as RequestInit | undefined)?.headers as Record<
      string,
      string
    >;
    expect(headers["X-Tenant-Slug"]).toBe(TENANT);
  });

  it("maps the governed response back, exposing the server's new version", async () => {
    stubFetch(() => json(responseDTO({ version: 9, raw_value: { value: "final" } })));

    const updated = await iigChecklists.executions.responses.reviewerConclusion(
      TENANT,
      EXECUTION,
      RESPONSE,
      { raw_value: { value: "final" }, expected_version: 8 }
    );

    expect(updated.version).toBe(9);
    expect(updated.rawValue).toEqual({ value: "final" });
  });

  it("surfaces a stale version as ApiError 409 so the caller refetches", async () => {
    stubFetch(() =>
      json(
        {
          error_code: "reviewer_conclusion_stale_version",
          detail: "expected_version does not match current version. Reload and retry.",
        },
        409
      )
    );

    await expect(
      iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
        raw_value: { value: "x" },
        expected_version: 2,
      })
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("surfaces a governed 400 with the server's detail", async () => {
    stubFetch(() =>
      json(
        { error_code: "invalid_expected_version", detail: "expected_version must be a positive integer." },
        400
      )
    );

    await expect(
      iigChecklists.executions.responses.reviewerConclusion(TENANT, EXECUTION, RESPONSE, {
        raw_value: { value: "x" },
        expected_version: 1,
      })
    ).rejects.toMatchObject({
      status: 400,
      message: "expected_version must be a positive integer.",
    });
  });
});
