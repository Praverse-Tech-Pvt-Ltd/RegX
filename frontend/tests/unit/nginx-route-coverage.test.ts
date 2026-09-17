/**
 * Every RegX page route must have an nginx location.
 *
 * P14 found six pages — /regulatory-cases, /dossier-blueprints,
 * /submission-operations, /external-integrations, /submission-dossiers and
 * /submission-packages — that worked perfectly on the frontend container's own
 * port and answered 404 through the integrated nginx origin, because they were
 * missing from the location list and fell through to the company site. Four
 * sidebar links pointed into that set.
 *
 * Nothing caught it. Playwright drives its own Next.js server and never crosses
 * nginx; the container workflow checked those routes on `localhost:3000`, which
 * is the one place they were guaranteed to work. The integrated-origin checks
 * that do exist were a hand-written list, and a hand-written list is precisely
 * what drifted — none of the six was on it.
 *
 * So this test derives both sides instead of listing either:
 *
 *   source of truth for "a page exists"  ->  frontend/src/app/(regx)/<segment>/
 *   source of truth for "it is routed"   ->  infra/nginx/nginx.conf
 *
 * Add a page directory without adding its location and this fails, at PR time,
 * with no stack running. `integrated-origin-routing` in the Docker workflow
 * proves the deployed origin actually behaves; this proves the configuration
 * can't silently fall behind the code.
 */

import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../..");
const REGX_APP_DIR = resolve(REPO, "frontend/src/app/(regx)");
const NGINX_CONF = resolve(REPO, "infra/nginx/nginx.conf");

/** Top-level route segments under the `(regx)` route group. */
function routeSegments(): string[] {
  return readdirSync(REGX_APP_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    // Next.js route groups `(x)`, private folders `_x` and dynamic segments
    // `[x]` are not URL prefixes of their own.
    .filter((entry) => !/^[([_]/.test(entry.name))
    .map((entry) => entry.name)
    .sort();
}

/** Path prefixes nginx proxies to the RegX frontend upstream. */
function nginxFrontendPrefixes(): string[] {
  const conf = readFileSync(NGINX_CONF, "utf8");
  const pattern =
    /^\s*location\s+\^~\s+\/([a-z0-9-]+)\/?\s*\{\s*proxy_pass\s+http:\/\/regx_frontend/gm;
  const found = new Set<string>();
  for (const match of conf.matchAll(pattern)) {
    if (match[1]) found.add(match[1]);
  }
  return [...found].sort();
}

describe("nginx route coverage", () => {
  it("finds the route segments and the nginx prefixes at all", () => {
    // Guards the test itself: a rename or a parser change that silently matched
    // nothing would make every assertion below vacuously pass.
    expect(routeSegments().length).toBeGreaterThan(5);
    expect(nginxFrontendPrefixes().length).toBeGreaterThan(5);
  });

  it("routes every RegX page segment through nginx to the frontend", () => {
    const prefixes = new Set(nginxFrontendPrefixes());
    const unrouted = routeSegments().filter((segment) => !prefixes.has(segment));

    expect(
      unrouted,
      `These page directories exist under frontend/src/app/(regx)/ but have no ` +
        `\`location ^~ /<segment> { proxy_pass http://regx_frontend; }\` in ` +
        `infra/nginx/nginx.conf. They will serve on the frontend container's own ` +
        `port and fall through to the company site — a 404 — on the integrated ` +
        `origin. Add the location; do not add a wildcard.`,
    ).toEqual([]);
  });

  it("keeps the two sign-in-adjacent prefixes that have no page directory", () => {
    // `/signin` and `/mfa` are real frontend routes served from outside the
    // `(regx)` group, so the derivation above cannot see them. Asserted
    // explicitly rather than left to look like stale entries somebody may prune.
    const prefixes = new Set(nginxFrontendPrefixes());
    expect(prefixes.has("signin")).toBe(true);
    expect(prefixes.has("mfa")).toBe(true);
  });

  it("does not route the company site's own prefixes to the frontend", () => {
    // The boundary in the other direction: nginx must not hand the company
    // site's paths to Next.js.
    const prefixes = new Set(nginxFrontendPrefixes());
    for (const companyOwned of ["ratools", "adminmaster", "aidatabase", "admin"]) {
      expect(prefixes.has(companyOwned)).toBe(false);
    }
  });
});
