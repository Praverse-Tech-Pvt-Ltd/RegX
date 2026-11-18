/**
 * Every REGX page, as each demo role, on the real stack.
 *
 * Opens the sidebar pages and the "new" pages, then follows links from them to
 * one example of every detail route the seeded data reaches. For each page it
 * records: HTTP status of the document, browser console errors, uncaught page
 * errors, API calls that failed (status >= 400 or no response), any error text
 * the page shows, and a full-page screenshot. One JSON line per page goes to
 * `$REAL_STACK_OUT/pages.jsonl`.
 *
 * A page "loads" when the document is < 400, nothing was thrown in the page, no
 * error boundary or error text is shown and it renders a heading. A refused
 * API call (403) for a role that may not see the data is recorded, not failed:
 * the page must show a refusal message rather than break.
 */
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";
import { OUT, ROLES, TENANT, record, signIn, type RoleName } from "./helpers";

const SIDEBAR = [
  "/dashboard",
  "/documents",
  "/fda-data/releases",
  "/fda-data/mappings",
  "/fda-data/orange-book",
  "/formulations",
  "/iid-assessments/preview",
  "/iig-checklists",
  "/iig-checklists/executions",
  "/regulatory-cases",
  "/workflows",
  "/migration-batches",
  "/dossier-blueprints",
  "/submission-operations",
  "/external-integrations",
  "/templates",
  "/template-sources",
  "/tenants",
];
const NEW_PAGES = [
  "/formulations/new",
  "/iig-checklists/new",
  "/iig-checklists/executions/new",
  "/workflows/new",
  "/fda-data/releases/new",
];

// Detail routes (one per page.tsx under src/app/(regx)), as patterns to follow.
const DETAIL_ROUTES: [string, RegExp][] = [
  ["documents/[id]", /^\/documents\/[0-9a-f-]{36}$/],
  ["dossier-blueprints/[id]", /^\/dossier-blueprints\/[0-9a-f-]{36}$/],
  ["dossier-blueprints/[id]/versions/[id]", /^\/dossier-blueprints\/[0-9a-f-]{36}\/versions\/[0-9a-f-]{36}$/],
  ["external-integrations/[id]", /^\/external-integrations\/[0-9a-f-]{36}$/],
  ["fda-data/mappings/[id]", /^\/fda-data\/mappings\/[0-9a-f-]{36}$/],
  ["fda-data/orange-book/[id]", /^\/fda-data\/orange-book\/[0-9a-f-]{36}$/],
  ["fda-data/releases/[id]", /^\/fda-data\/releases\/[0-9a-f-]{36}$/],
  ["fda-data/releases/[id]/reconciliation", /^\/fda-data\/releases\/[0-9a-f-]{36}\/reconciliation$/],
  ["formulations/[id]", /^\/formulations\/[0-9a-f-]{36}$/],
  ["formulations/[id]/versions/[id]", /^\/formulations\/[0-9a-f-]{36}\/versions\/[0-9a-f-]{36}$/],
  ["iid-assessments/[id]", /^\/iid-assessments\/[0-9a-f-]{36}$/],
  ["iig-checklists/[id]", /^\/iig-checklists\/[0-9a-f-]{36}$/],
  ["iig-checklists/versions/[id]", /^\/iig-checklists\/versions\/[0-9a-f-]{36}$/],
  ["iig-checklists/executions/[id]", /^\/iig-checklists\/executions\/[0-9a-f-]{36}$/],
  ["migration-batches/[id]", /^\/migration-batches\/[0-9a-f-]{36}$/],
  ["regulatory-cases/[id]", /^\/regulatory-cases\/[0-9a-f-]{36}$/],
  ["submission-dossiers/[id]", /^\/submission-dossiers\/[0-9a-f-]{36}$/],
  ["submission-packages/[id]", /^\/submission-packages\/[0-9a-f-]{36}$/],
  ["templates/[id]", /^\/templates\/[0-9a-f-]{36}$/],
  ["workflows/[id]", /^\/workflows\/[0-9a-f-]{36}$/],
];

const ERROR_TEXT =
  /application error|something went wrong|unhandled runtime error|internal server error|could not be loaded|failed to load|unexpected error/i;

type PageResult = {
  role: RoleName;
  path: string;
  route: string;
  status: number | null;
  loads: boolean;
  heading: string | null;
  consoleErrors: string[];
  pageErrors: string[];
  failedApi: string[];
  errorText: string | null;
  refusal: boolean;
  screenshot: string;
};

async function visit(page: Page, role: RoleName, path: string, route: string): Promise<PageResult> {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedApi: string[] = [];
  const onConsole = (m: { type(): string; text(): string }) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300));
  };
  const onPageError = (e: Error) => pageErrors.push(String(e.message).slice(0, 300));
  const onResponse = (r: { url(): string; status(): number; request(): { method(): string } }) => {
    if (r.url().includes("/api/") && r.status() >= 400) {
      failedApi.push(`${r.request().method()} ${new URL(r.url()).pathname} -> ${r.status()}`);
    }
  };
  const onRequestFailed = (r: { url(): string; method(): string; failure(): { errorText: string } | null }) => {
    if (r.url().includes("/api/")) {
      failedApi.push(`${r.method()} ${new URL(r.url()).pathname} -> ${r.failure()?.errorText ?? "failed"}`);
    }
  };
  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  page.on("response", onResponse);
  page.on("requestfailed", onRequestFailed);

  let status: number | null = null;
  try {
    const res = await page.goto(path, { waitUntil: "networkidle", timeout: 45_000 });
    status = res?.status() ?? null;
  } catch (e) {
    pageErrors.push(`navigation: ${String(e).slice(0, 200)}`);
  }
  await page.waitForTimeout(400);
  const main = page.locator("main");
  const text = (await main.count()) ? await main.innerText().catch(() => "") : await page.innerText("body");
  const errorMatch = text.match(ERROR_TEXT);
  const heading = await page
    .locator("main h1, main h2")
    .first()
    .innerText({ timeout: 2000 })
    .catch(() => null);
  const refusal = /permission|not allowed|not authori[sz]ed|do not have access|access denied/i.test(text);
  const shot = join(OUT, "screenshots", `${role}__${path.replace(/[^a-z0-9]+/gi, "_")}.png`);
  await page.screenshot({ path: shot, fullPage: true }).catch(() => undefined);

  page.off("console", onConsole);
  page.off("pageerror", onPageError);
  page.off("response", onResponse);
  page.off("requestfailed", onRequestFailed);

  const result: PageResult = {
    role,
    path,
    route,
    status,
    loads: status !== null && status < 400 && pageErrors.length === 0 && !errorMatch && !!heading,
    heading,
    consoleErrors,
    pageErrors,
    failedApi,
    errorText: errorMatch ? errorMatch[0] : null,
    refusal,
    screenshot: shot,
  };
  record("pages.jsonl", result);
  return result;
}

async function detailLinks(page: Page): Promise<string[]> {
  const hrefs = await page.locator("main a[href^='/']").evaluateAll((as) =>
    as.map((a) => (a as HTMLAnchorElement).getAttribute("href") ?? ""),
  );
  return [...new Set(hrefs)];
}

const withTenant = (path: string) => `${path}?tenant=${encodeURIComponent(TENANT)}`;

for (const role of ROLES) {
  test(`every page loads for ${role}`, async ({ page }) => {
    await signIn(page, role);
    const results: PageResult[] = [];
    const seenRoutes = new Set<string>();
    // A user reaches every page through the sidebar, which carries ?tenant=.
    const queue: [string, string][] = [...SIDEBAR, ...NEW_PAGES].map((p) => [withTenant(p), p]);
    const droppedTenant: string[] = [];
    const visited = new Set<string>();
    while (queue.length) {
      const [path, route] = queue.shift()!;
      if (visited.has(path)) continue;
      visited.add(path);
      results.push(await visit(page, role, path, route));
      for (const href of await detailLinks(page)) {
        const [hrefPath, query = ""] = href.split("?");
        for (const [name, re] of DETAIL_ROUTES) {
          if (re.test(hrefPath!) && !seenRoutes.has(name)) {
            seenRoutes.add(name);
            if (!new URLSearchParams(query).get("tenant")) {
              // A link that loses the workspace strands the user on the chooser.
              droppedTenant.push(`${path} -> ${href}`);
              record("pages.jsonl", { role, route: name, from: path, href, droppedTenant: true });
            }
            queue.push([href, name]);
          }
        }
      }
    }
    for (const [name] of DETAIL_ROUTES) {
      if (!seenRoutes.has(name)) record("pages.jsonl", { role, route: name, unreached: true });
    }
    const broken = results.filter((r) => !r.loads);
    expect(broken.map((r) => `${r.path}: ${r.errorText ?? r.pageErrors[0] ?? `status ${r.status}`}`)).toEqual([]);
    expect(droppedTenant).toEqual([]);
  });
}
