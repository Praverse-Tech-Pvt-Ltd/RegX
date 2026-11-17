/**
 * A signed-out request and a refused one both arrive as HTTP 403 under session
 * authentication. `apiRequest` must turn the first into a 401 (go to sign-in)
 * and keep the second a 403 (say "not allowed"). Found on the real stack: a
 * signed-in Doer opening Terminology Mappings landed on the sign-in page.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, isSignedOut, loadError } from "@/lib/api";

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })),
  );
}

async function failure(): Promise<ApiError> {
  try {
    await apiRequest("/api/regx/v1/fda-data/mappings/");
  } catch (err) {
    return err as ApiError;
  }
  throw new Error("expected a failure");
}

afterEach(() => vi.unstubAllGlobals());

describe("signed out vs refused", () => {
  it("a 403 coded not_authenticated becomes a 401: signed out", async () => {
    respond(403, {
      error: { status: 403, code: "not_authenticated", detail: { detail: "Authentication credentials were not provided." } },
    });
    const err = await failure();
    expect(err.status).toBe(401);
    expect(err.code).toBe("not_authenticated");
    expect(isSignedOut(err)).toBe(true);
  });

  it("a 403 coded permission_denied stays a 403: signed in, not allowed", async () => {
    respond(403, {
      error: { status: 403, code: "permission_denied", detail: { detail: "You do not have permission to perform this action." } },
    });
    const err = await failure();
    expect(err.status).toBe(403);
    expect(isSignedOut(err)).toBe(false);
    expect(loadError(err, "Failed to load.")).toBe("You do not have permission to perform this action.");
  });

  it("a 403 without a code is treated as refused, never as signed out", async () => {
    respond(403, { detail: "Tenant access denied." });
    const err = await failure();
    expect(isSignedOut(err)).toBe(false);
  });

  it("other failures keep the page's own fallback text", () => {
    expect(loadError(new ApiError(500, "x"), "Failed to load.")).toBe("Failed to load.");
    expect(loadError(new Error("boom"), "Failed to load.")).toBe("Failed to load.");
  });
});
