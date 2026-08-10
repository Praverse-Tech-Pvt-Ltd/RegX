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

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const RESPONSE = "resp-public-0001";

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
