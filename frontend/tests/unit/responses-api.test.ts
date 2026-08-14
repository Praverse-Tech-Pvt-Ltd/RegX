/**
 * Wire-level coverage for the governed response helpers.
 *
 * These tests deliberately do NOT mock `@/lib/api` - the behaviour under test is
 * the helper itself, so only `fetch` is stubbed and the real request and real
 * mapper are exercised. Mocking the helper would assert nothing about what
 * actually reaches the backend or what comes back.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, iigChecklists } from "@/lib/api";
import type { ChecklistResponseDTO } from "@/lib/api";
import { toPayloadValue } from "@/app/(regx)/iig-checklists/executions/[executionPublicId]/ChecklistResponses";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const RESPONSE = "resp-public-0001";
/** Matches the client's default API base, so `next` links look like DRF's. */
const API_ROOT = "http://localhost:8000";

function responseDTO(overrides: Partial<ChecklistResponseDTO> = {}): ChecklistResponseDTO {
  return {
    public_id: RESPONSE,
    question_public_id: "question-public-0001",
    data_source_type_snapshot: "user_required",
    raw_value: "hello",
    is_not_applicable: false,
    not_applicable_reason: null,
    entered_by_email: "doer@example.com",
    entered_at: "2026-01-01T00:00:00Z",
    confirmed_by_email: null,
    confirmed_at: null,
    override_reason: "",
    system_derived_value: null,
    version: 4,
    ...overrides,
  };
}

/** The list endpoint is paginated - mirror the real envelope, not a bare array. */
function paginate(results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
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
    if (href.includes("/auth/csrf/")) {
      return json({ csrfToken: "csrf-token-value" });
    }
    return handler(href, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function bodyOf(init: RequestInit | undefined): Record<string, unknown> {
  return JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("responses.update - governed expected_version transport", () => {
  it("sends expected_version in the PATCH body", async () => {
    const fetchMock = stubFetch(() => json(responseDTO({ version: 5 })));

    await iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
      expected_version: 4,
      raw_value: "updated",
    });

    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH"
    );
    expect(patchCall).toBeDefined();
    expect(bodyOf(patchCall?.[1] as RequestInit | undefined)).toHaveProperty(
      "expected_version",
      4
    );
  });

  it("sends the exact version taken from the loaded response, not a default", async () => {
    const loaded = responseDTO({ version: 17 });
    const fetchMock = stubFetch(() => json(responseDTO({ version: 18 })));

    await iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
      expected_version: loaded.version,
      raw_value: "updated",
    });

    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH"
    );
    // Not 1, not 0, not absent - the version the server last reported.
    expect(bodyOf(patchCall?.[1] as RequestInit | undefined).expected_version).toBe(17);
  });

  it("PATCHes the governed per-response URL and nothing else", async () => {
    const fetchMock = stubFetch(() => json(responseDTO()));

    await iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
      expected_version: 4,
      raw_value: "x",
    });

    const writeCalls = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH"
    );
    // Exactly one governed write. There is no follow-up "recalculate" call:
    // the cascade is a backend consequence of this PATCH.
    expect(writeCalls).toHaveLength(1);
    expect(String(writeCalls[0]?.[0])).toContain(
      `/api/regx/v1/iig-checklists/executions/${EXECUTION}/responses/${RESPONSE}/`
    );
  });

  it("surfaces a stale version as ApiError 409 so callers can refetch", async () => {
    stubFetch(() => json({ error_code: "stale_version", detail: "stale" }, 409));

    await expect(
      iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
        expected_version: 2,
        raw_value: "x",
      })
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("maps the returned response through the mapper, exposing the new version", async () => {
    stubFetch(() => json(responseDTO({ version: 9 })));

    const updated = await iigChecklists.executions.responses.update(
      TENANT,
      EXECUTION,
      RESPONSE,
      { expected_version: 8, raw_value: "x" }
    );

    expect(updated.version).toBe(9);
    expect(updated.dataSourceTypeSnapshot).toBe("user_required");
  });
});

describe("raw_value wire contract - real serializer, real request body", () => {
  // These deliberately do NOT mock responses.update(). The defect this covers
  // escaped precisely because earlier tests mocked past the wire: the helper was
  // asserted to have been *called*, never inspected for what it actually sent.
  // Here the real toPayloadValue() feeds the real update() and the request body
  // is read back off the stubbed fetch.
  //
  // Shapes mirror backend/iig_checklist/response_validation.py exactly.

  async function sentRawValue(answerType: string, text: string) {
    const fetchMock = stubFetch(() => json(responseDTO({ version: 5 })));
    await iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
      expected_version: 4,
      raw_value: toPayloadValue(answerType, text),
    });
    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH"
    );
    return bodyOf(patchCall?.[1] as RequestInit | undefined).raw_value;
  }

  it("short_text sends an enveloped string", async () => {
    expect(await sentRawValue("short_text", "abc")).toEqual({ value: "abc" });
  });

  it("long_narrative sends an enveloped string", async () => {
    expect(await sentRawValue("long_narrative", "a longer answer")).toEqual({
      value: "a longer answer",
    });
  });

  it("integer sends an enveloped JSON integer, not a string", async () => {
    const sent = await sentRawValue("integer", "12");
    expect(sent).toEqual({ value: 12 });
    expect(typeof (sent as { value: unknown }).value).toBe("number");
  });

  it("decimal sends an enveloped decimal string, never a JS number", async () => {
    // A regulated figure must not round-trip through a float.
    const sent = await sentRawValue("decimal", "12.5000000000");
    expect(sent).toEqual({ value: "12.5000000000" });
    expect(typeof (sent as { value: unknown }).value).toBe("string");
  });

  it("percentage sends an enveloped decimal string", async () => {
    const sent = await sentRawValue("percentage", "99.9");
    expect(sent).toEqual({ value: "99.9" });
    expect(typeof (sent as { value: unknown }).value).toBe("string");
  });

  it("date sends an enveloped ISO-8601 date string", async () => {
    expect(await sentRawValue("date", "2026-08-11")).toEqual({ value: "2026-08-11" });
  });

  it("yes_no sends an enveloped JSON boolean", async () => {
    const yes = await sentRawValue("yes_no", "true");
    expect(yes).toEqual({ value: true });
    expect(typeof (yes as { value: unknown }).value).toBe("boolean");
    expect(await sentRawValue("yes_no", "false")).toEqual({ value: false });
  });

  it("yes_no_na sends the closed string vocabulary, not a boolean", async () => {
    expect(await sentRawValue("yes_no_na", "yes")).toEqual({ value: "yes" });
    expect(await sentRawValue("yes_no_na", "no")).toEqual({ value: "no" });
    expect(await sentRawValue("yes_no_na", "not_applicable")).toEqual({
      value: "not_applicable",
    });
  });

  it("yes_no_na 'no' is a string, never the boolean false", async () => {
    // The old helper mapped these through booleans; the backend refuses that.
    const sent = await sentRawValue("yes_no_na", "no");
    expect(typeof (sent as { value: unknown }).value).toBe("string");
    expect((sent as { value: unknown }).value).not.toBe(false);
  });

  it("an empty edit clears the answer with a bare null, not an envelope", async () => {
    expect(await sentRawValue("short_text", "")).toBeNull();
  });

  it("an unparseable integer is forwarded verbatim for the backend to refuse", async () => {
    // Better a clear server-side type error than a client-invented number.
    expect(await sentRawValue("integer", "not-a-number")).toEqual({ value: "not-a-number" });
  });
});

describe("responses.list - paginated envelope and calculation projection", () => {
  it("unwraps the paginated envelope the endpoint actually returns", async () => {
    // The endpoint is PageNumberPagination, so the payload is
    // {count, next, previous, results}. Treating it as a bare array threw.
    stubFetch(() => json(paginate([responseDTO(), responseDTO({ public_id: "resp-2" })])));

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);

    expect(rows).toHaveLength(2);
    expect(rows[0]?.publicId).toBe(RESPONSE);
    expect(rows[1]?.publicId).toBe("resp-2");
  });

  it("maps the calculation projection from the wire into the UI model", async () => {
    stubFetch(() =>
      json(
        paginate([
          responseDTO({
            public_id: "resp-calc-1",
            data_source_type_snapshot: "system_calculated",
            raw_value: null,
            system_derived_value: null,
            calculation: {
              outcome_public_id: "outcome-1",
              status: "complete",
              value: "0.2500000000",
              unit: "gram",
              reason_code: null,
            },
          }),
        ])
      )
    );

    const [row] = await iigChecklists.executions.responses.list(TENANT, EXECUTION);

    expect(row?.calculation).toEqual({
      outcomePublicId: "outcome-1",
      status: "complete",
      // Kept as the exact decimal string, never a lossy JS number.
      value: "0.2500000000",
      unit: "gram",
      reasonCode: null,
    });
    // Neither of these is the result carrier.
    expect(row?.rawValue).toBeNull();
    expect(row?.systemDerivedValue).toBeNull();
  });

  it("maps a manual response to a null calculation", async () => {
    stubFetch(() => json(paginate([responseDTO({ calculation: null })])));

    const [row] = await iigChecklists.executions.responses.list(TENANT, EXECUTION);
    expect(row?.calculation).toBeNull();
  });

  it("keeps a non-complete outcome free of any value", async () => {
    stubFetch(() =>
      json(
        paginate([
          responseDTO({
            data_source_type_snapshot: "system_calculated",
            calculation: {
              outcome_public_id: "outcome-3",
              status: "error",
              value: null,
              unit: null,
              reason_code: "NOT_COMPARABLE",
            },
          }),
        ])
      )
    );

    const [row] = await iigChecklists.executions.responses.list(TENANT, EXECUTION);
    expect(row?.calculation?.status).toBe("error");
    expect(row?.calculation?.reasonCode).toBe("NOT_COMPARABLE");
    expect(row?.calculation?.value).toBeNull();
  });

  it("returns a single page unchanged and issues no second request", async () => {
    const fetchMock = stubFetch(() => json(paginate([responseDTO()])));

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);

    expect(rows).toHaveLength(1);
    const listCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/responses/")
    );
    // next was null, so the walk stopped immediately.
    expect(listCalls).toHaveLength(1);
  });

  it("follows next and returns both pages", async () => {
    const page2 = `${API_ROOT}/api/regx/v1/iig-checklists/executions/${EXECUTION}/responses/?page=2`;
    const fetchMock = stubFetch((url) => {
      if (url.includes("page=2")) {
        return json({
          count: 4,
          next: null,
          previous: null,
          results: [responseDTO({ public_id: "r3" }), responseDTO({ public_id: "r4" })],
        });
      }
      return json({
        count: 4,
        next: page2,
        previous: null,
        results: [responseDTO({ public_id: "r1" }), responseDTO({ public_id: "r2" })],
      });
    });

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);

    expect(rows.map((r) => r.publicId)).toEqual(["r1", "r2", "r3", "r4"]);
    const listCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/responses/")
    );
    expect(listCalls).toHaveLength(2);
    // The cursor was carried over, and the tenant header with it.
    expect(String(listCalls[1]?.[0])).toContain("page=2");
    const headers = (listCalls[1]?.[1] as RequestInit | undefined)?.headers as Record<
      string,
      string
    >;
    expect(headers["X-Tenant-Slug"]).toBe(TENANT);
  });

  it("preserves server order across pages", async () => {
    const page2 = `${API_ROOT}/api/regx/v1/iig-checklists/executions/${EXECUTION}/responses/?page=2`;
    stubFetch((url) =>
      url.includes("page=2")
        ? json({
            count: 4,
            next: null,
            previous: null,
            results: [responseDTO({ public_id: "c" }), responseDTO({ public_id: "d" })],
          })
        : json({
            count: 4,
            next: page2,
            previous: null,
            results: [responseDTO({ public_id: "a" }), responseDTO({ public_id: "b" })],
          })
    );

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);
    // Ordering is the server's (created_at); pages are appended, never sorted.
    expect(rows.map((r) => r.publicId)).toEqual(["a", "b", "c", "d"]);
  });

  it("handles an empty collection", async () => {
    stubFetch(() => json(paginate([])));

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);
    expect(rows).toEqual([]);
  });

  it("does not duplicate rows or loop when the server keeps returning the same link", async () => {
    const same = `${API_ROOT}/api/regx/v1/iig-checklists/executions/${EXECUTION}/responses/`;
    const fetchMock = stubFetch(() =>
      // A misbehaving paginator whose `next` points back at the current page.
      json({ count: 1, next: same, previous: null, results: [responseDTO({ public_id: "r1" })] })
    );

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);

    expect(rows.map((r) => r.publicId)).toEqual(["r1"]);
    const listCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/responses/")
    );
    expect(listCalls).toHaveLength(1);
  });

  it("walks past 25 rows, the page size that would otherwise truncate", async () => {
    const page2 = `${API_ROOT}/api/regx/v1/iig-checklists/executions/${EXECUTION}/responses/?page=2`;
    const first = Array.from({ length: 25 }, (_, i) =>
      responseDTO({ public_id: `r${i + 1}` })
    );
    stubFetch((url) =>
      url.includes("page=2")
        ? json({ count: 26, next: null, previous: null, results: [responseDTO({ public_id: "r26" })] })
        : json({ count: 26, next: page2, previous: null, results: first })
    );

    const rows = await iigChecklists.executions.responses.list(TENANT, EXECUTION);
    expect(rows).toHaveLength(26);
    expect(rows[25]?.publicId).toBe("r26");
  });

  it("treats an unrecognised status as no result rather than rendering it", async () => {
    stubFetch(() =>
      json(
        paginate([
          responseDTO({
            calculation: {
              outcome_public_id: "outcome-2",
              status: "some_future_status",
              value: "1.0",
              unit: "gram",
              reason_code: null,
            },
          }),
        ])
      )
    );

    const [row] = await iigChecklists.executions.responses.list(TENANT, EXECUTION);
    // Better to show nothing than a regulated value under an unexplained status.
    expect(row?.calculation).toBeNull();
  });
});
