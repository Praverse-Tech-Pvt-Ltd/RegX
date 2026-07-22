import { test, expect } from "@playwright/test";

test.describe("Sign-in page", () => {
  test("renders the sign-in form", async ({ page }) => {
    await page.goto("/signin");
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  test("shows error on invalid credentials", async ({ page }) => {
    await page.goto("/signin");
    await page.getByLabel("Email").fill("nobody@example.com");
    await page.getByLabel("Password").fill("WrongPass1234!");
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 5000 });
  });
});

test.describe("Accessibility: sign-in page", () => {
  test("form has accessible labels", async ({ page }) => {
    await page.goto("/signin");
    const emailInput = page.getByLabel("Email");
    const passwordInput = page.getByLabel("Password");
    await expect(emailInput).toHaveAttribute("type", "email");
    await expect(passwordInput).toHaveAttribute("type", "password");
    await expect(passwordInput).toHaveAttribute("autocomplete", "current-password");
  });
});
