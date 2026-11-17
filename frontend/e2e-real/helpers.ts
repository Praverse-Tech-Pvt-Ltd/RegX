/**
 * Shared helpers for the real-stack checks. No mocks: every request goes to
 * the stack at REAL_STACK_URL (default http://localhost:8080).
 */
import { createHmac } from "node:crypto";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page } from "@playwright/test";

export const TENANT = process.env["REAL_STACK_TENANT"] ?? "demo";
export const OUT = process.env["REAL_STACK_OUT"] ?? "test-results/real-stack";
export const ROLES = ["doer", "reviewer", "vp", "tenant_admin"] as const;
export type RoleName = (typeof ROLES)[number];

export function email(role: RoleName): string {
  return `${role}@demo.regx.invalid`;
}

export function password(): string {
  const pw = process.env["REAL_STACK_PASSWORD"];
  if (!pw) throw new Error("Set REAL_STACK_PASSWORD (the demo password); it is never stored in a file.");
  return pw;
}

export function record(file: string, entry: Record<string, unknown>): void {
  mkdirSync(OUT, { recursive: true });
  appendFileSync(join(OUT, file), JSON.stringify(entry) + "\n");
}

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits) from a base32 secret. */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = secret.replace(/=+$/, "").replace(/\s+/g, "").toUpperCase();
  let bits = "";
  for (const ch of clean) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const bytes = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const h = createHmac("sha1", bytes).update(counter).digest();
  const offset = h[h.length - 1]! & 0xf;
  const code = (h.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

/** TOTP secrets of demo users enrolled in MFA (JSON email -> secret), local only. */
function mfaSecret(role: RoleName): string | undefined {
  const file = process.env["REAL_STACK_MFA_FILE"];
  if (!file) return undefined;
  try {
    return (JSON.parse(readFileSync(file, "utf-8")) as Record<string, string>)[email(role)];
  } catch {
    return undefined;
  }
}

export async function signIn(page: Page, role: RoleName): Promise<void> {
  await page.goto("/signin");
  await page.getByLabel("Email").fill(email(role));
  await page.getByLabel("Password").fill(password());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/signin/);
  if (/\/mfa/.test(page.url())) {
    const secret = mfaSecret(role);
    if (!secret) throw new Error(`${role} needs MFA: set REAL_STACK_MFA_FILE`);
    // A code is single-use per 30 s step; if it was just used, try the next step.
    for (let attempt = 0; attempt < 3 && /\/mfa/.test(page.url()); attempt++) {
      await page.getByLabel("OTP Code").fill(totp(secret));
      await page.getByRole("button", { name: "Verify" }).click();
      await page.waitForURL((u) => !/\/mfa/.test(u.pathname), { timeout: 5000 }).catch(() => undefined);
      if (/\/mfa/.test(page.url())) await page.waitForTimeout(31_000 - (Date.now() % 30_000));
    }
    await expect(page).not.toHaveURL(/\/mfa/);
  }
}

/** Calls the API with the browser's session (cookies) and CSRF token. */
export async function api(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; json: unknown }> {
  return page.evaluate(
    async ({ method, path, body, tenant }) => {
      const headers: Record<string, string> = { "X-Tenant-Slug": tenant };
      if (method !== "GET") {
        const csrf = await fetch("/api/regx/v1/auth/csrf/", { credentials: "include" });
        const token = (await csrf.json()).csrfToken ?? document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "";
        headers["X-CSRFToken"] = token;
        headers["Content-Type"] = "application/json";
      }
      const res = await fetch(`/api/regx/v1/${path}`, {
        method,
        headers,
        credentials: "include",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let json: unknown = null;
      try {
        json = await res.json();
      } catch {
        json = null;
      }
      return { status: res.status, json };
    },
    { method, path, body, tenant: TENANT },
  );
}
