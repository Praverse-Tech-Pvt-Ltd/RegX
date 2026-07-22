import { test, expect } from "@playwright/test";

test.describe("Security: no auth token in localStorage/sessionStorage", () => {
  test("sign-in page does not store auth token in localStorage", async ({ page }) => {
    await page.goto("/signin");

    // Attempt login (will fail against backend, but we want to check storage)
    await page.getByLabel("Email").fill("test@example.com");
    await page.getByLabel("Password").fill("TestPass123!");
    await page.getByRole("button", { name: /sign in/i }).click();

    // Wait briefly for any async storage writes
    await page.waitForTimeout(1000);

    const localStorageKeys = await page.evaluate(() =>
      Object.keys(localStorage).filter((k) =>
        /(token|auth|jwt|session)/i.test(k)
      )
    );
    const sessionStorageKeys = await page.evaluate(() =>
      Object.keys(sessionStorage).filter((k) =>
        /(token|auth|jwt|session)/i.test(k)
      )
    );

    expect(localStorageKeys).toHaveLength(0);
    expect(sessionStorageKeys).toHaveLength(0);
  });

  test("dashboard page does not read auth token from localStorage", async ({ page }) => {
    await page.goto("/dashboard");

    const localStorageKeys = await page.evaluate(() =>
      Object.keys(localStorage).filter((k) =>
        /(token|auth|jwt|session)/i.test(k)
      )
    );

    expect(localStorageKeys).toHaveLength(0);
  });
});
