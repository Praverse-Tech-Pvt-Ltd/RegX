import { test, expect } from "@playwright/test";

/**
 * Generic workflow lifecycle E2E.
 *
 * API responses are mocked with page.route, as every other spec in this suite
 * does, so the test exercises the UI contract rather than a live backend.
 *
 * The property under test is the one that matters for security posture:
 * **the UI renders controls from the backend's `available_actions`**. It does
 * not compute permissions client-side, and hiding a button is presentation
 * only -- the backend re-checks every action.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const ITEM_ID = "11111111-2222-3333-4444-555555555555";

function jsonRoute(body: unknown, status = 200) {
  return async (route: import("@playwright/test").Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    public_id: ITEM_ID,
    title: "Synthetic workflow item",
    description: "Synthetic description",
    state: "draft",
    created_by: { public_id: "u-1", email: "doer@example.com", full_name: "Doer" },
    assigned_to: null,
    assigned_at: null,
    due_at: null,
    is_overdue: false,
    is_terminal: false,
    available_actions: ["submit", "cancel"],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

async function mockCsrf(page: import("@playwright/test").Page) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
}

test.describe("Workflow list", () => {
  test("lists items with state badges", async ({ page }) => {
    await mockCsrf(page);
    await page.route(/\/api\/regx\/v1\/workflows\/(\?.*)?$/, jsonRoute({
      count: 2,
      next: null,
      previous: null,
      results: [
        item(),
        item({
          public_id: "99999999-2222-3333-4444-555555555555",
          title: "Second item",
          state: "in_review",
          available_actions: ["approve", "reject", "cancel"],
        }),
      ],
    }));

    await page.goto(`/workflows?tenant=${TENANT}`);

    await expect(page.getByRole("link", { name: "Synthetic workflow item" })).toBeVisible();
    const badges = page.getByTestId("workflow-state-badge");
    await expect(badges.first()).toHaveAttribute("data-state", "draft");
    await expect(badges.nth(1)).toHaveAttribute("data-state", "in_review");
  });
});

test.describe("Workflow detail and transitions", () => {
  test("renders only the actions the backend permits", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`),
      jsonRoute(item({ available_actions: ["submit"] })),
    );
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`), jsonRoute([]));

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    await expect(page.getByTestId("action-submit")).toBeVisible();
    // Not rendered because the backend did not offer it -- the UI must not
    // invent an action the caller is not permitted to take.
    await expect(page.getByTestId("action-approve")).toHaveCount(0);
    await expect(page.getByTestId("action-cancel")).toHaveCount(0);
  });

  test("a terminal item offers no actions", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`),
      jsonRoute(item({ state: "approved", is_terminal: true, available_actions: [] })),
    );
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`), jsonRoute([]));

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    await expect(page.getByTestId("workflow-state-badge")).toHaveAttribute(
      "data-state",
      "approved",
    );
    await expect(page.getByTestId("no-actions")).toBeVisible();
  });

  test("a governed action requires a reason before it can be confirmed", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`),
      jsonRoute(item({ state: "in_review", available_actions: ["approve", "reject"] })),
    );
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`), jsonRoute([]));

    let rejectBody: string | null = null;
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/reject/$`), async (route) => {
      rejectBody = route.request().postData();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(item({ state: "rejected", available_actions: ["cancel"] })),
      });
    });

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);
    await page.getByTestId("action-reject").click();

    // The form appears and Confirm stays disabled while the reason is blank.
    await expect(page.getByTestId("reason-form")).toBeVisible();
    await expect(page.getByTestId("reason-confirm")).toBeDisabled();

    await page.getByTestId("reason-input").fill("Insufficient detail");
    await expect(page.getByTestId("reason-confirm")).toBeEnabled();
    await page.getByTestId("reason-confirm").click();

    await expect.poll(() => rejectBody).toContain("Insufficient detail");
  });

  test("approve does not require a reason", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`),
      jsonRoute(item({ state: "in_review", available_actions: ["approve"] })),
    );
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`), jsonRoute([]));

    let approveCalled = false;
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/approve/$`), async (route) => {
      approveCalled = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(item({ state: "approved", is_terminal: true, available_actions: [] })),
      });
    });

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);
    await page.getByTestId("action-approve").click();

    // No reason form for approve -- it goes straight through.
    await expect(page.getByTestId("reason-form")).toHaveCount(0);
    await expect.poll(() => approveCalled).toBe(true);
  });

  test("a 409 conflict surfaces and reloads rather than guessing", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`),
      jsonRoute(item({ state: "in_review", available_actions: ["approve"] })),
    );
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`), jsonRoute([]));
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/approve/$`),
      jsonRoute({ detail: "Cannot approve a WorkflowItem while it is 'rejected'.", current_state: "rejected" }, 409),
    );

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);
    await page.getByTestId("action-approve").click();

    // Not getByRole("alert"): Next.js injects its own
    // <div role="alert" id="__next-route-announcer__">, so the role alone
    // matches two elements and trips strict mode.
    await expect(page.getByTestId("workflow-error")).toContainText(
      "changed while you were viewing it",
    );
  });

  test("history is displayed as a read-only timeline", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`),
      jsonRoute(item({ state: "in_review", available_actions: [] })),
    );
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`),
      jsonRoute([
        {
          public_id: "t-1",
          action: "submit",
          from_state: "draft",
          to_state: "submitted",
          actor: { public_id: "u-1", email: "doer@example.com", full_name: "Doer" },
          reason: "",
          created_at: "2026-01-01T01:00:00Z",
        },
        {
          public_id: "t-2",
          action: "begin_review",
          from_state: "submitted",
          to_state: "in_review",
          actor: { public_id: "u-2", email: "reviewer@example.com", full_name: "Reviewer" },
          reason: "",
          created_at: "2026-01-01T02:00:00Z",
        },
      ]),
    );

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    const table = page.getByTestId("history-table");
    await expect(table).toBeVisible();
    await expect(table).toContainText("draft → submitted");
    await expect(table).toContainText("submitted → in_review");
    await expect(table).toContainText("reviewer@example.com");
  });
});
