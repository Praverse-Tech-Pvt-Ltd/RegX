/**
 * Wire-level coverage for the governed response update helper.
 *
 * These tests deliberately do NOT mock `@/lib/api` — the behaviour under test is
 * the helper itself, so only `fetch` is stubbed and the real request is
 * inspected. Mocking the helper would assert nothing about what actually
 * reaches the backend.
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

/** Stub the CSRF preflight `apiRequest` performs before any write. */
function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
    const href = String(url);
    if (href.includes("/auth/csrf/")) {
      return new Response(JSON.stringify({ csrfToken: "csrf-token-value" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
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

describe("responses.update — governed expected_version transport", () => {
  it("sends expected_version in the PATCH body", async () => {
    const fetchMock = stubFetch(
      () =>
        new Response(JSON.stringify(responseDTO({ version: 5 })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );

    await iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
      expected_version: 4,
      raw_value: "updated",
    });

    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH"
    );
    expect(patchCall).toBeDefined();
    const body = bodyOf(patchCall?.[1] as RequestInit | undefined);
    expect(body).toHaveProperty("expected_version", 4);
  });

  it("sends the exact version taken from the loaded response, not a default", async () => {
    const loaded = responseDTO({ version: 17 });
    const fetchMock = stubFetch(
      () =>
        new Response(JSON.stringify(responseDTO({ version: 18 })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );

    await iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
      expected_version: loaded.version,
      raw_value: "updated",
    });

    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH"
    );
    const body = bodyOf(patchCall?.[1] as RequestInit | undefined);
    // Not 1, not 0, not absent — the version the server last reported.
    expect(body.expected_version).toBe(17);
  });

  it("PATCHes the governed per-response URL and nothing else", async () => {
    const fetchMock = stubFetch(
      () =>
        new Response(JSON.stringify(responseDTO()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );

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
    stubFetch(
      () =>
        new Response(JSON.stringify({ error_code: "stale_version", detail: "stale" }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        })
    );

    await expect(
      iigChecklists.executions.responses.update(TENANT, EXECUTION, RESPONSE, {
        expected_version: 2,
        raw_value: "x",
      })
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("maps the returned response through the mapper, exposing the new version", async () => {
    stubFetch(
      () =>
        new Response(JSON.stringify(responseDTO({ version: 9 })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );

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
