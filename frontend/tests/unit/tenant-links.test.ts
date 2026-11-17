/**
 * Every in-app link or navigation to a REGX page must carry ?tenant=.
 *
 * Every REGX page reads its organisation from ?tenant=; a link without it lands
 * the user on a page that waits forever ("Loading...") or on the chooser. Found
 * on the real stack (2026-11-17): the External Integrations list linked to each
 * connector without the tenant, so the detail page never loaded.
 *
 * A source check, deliberately: it covers links on pages no unit test renders.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "..", "src");
const REGX = join(SRC, "app", "(regx)");

// Pages that are deliberately tenant-less: the chooser itself.
const TENANT_LESS = new Set(["tenants"]);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

const prefixes = readdirSync(REGX).filter(
  (name) => statSync(join(REGX, name)).isDirectory() && !TENANT_LESS.has(name),
);
// href="/x...", href={`/x...`}, push("/x..."), push(`/x...`), replace(...)
const LINK = /(?:href=\{?|push\(|replace\()\s*(["`])(\/[^"`]*)\1/g;

describe("in-app links keep the tenant", () => {
  it("finds the REGX route prefixes", () => {
    expect(prefixes).toContain("external-integrations");
    expect(prefixes).toContain("formulations");
  });

  it("every link to a REGX page carries ?tenant=", () => {
    const offenders: string[] = [];
    for (const file of files(SRC)) {
      const text = readFileSync(file, "utf-8");
      for (const match of text.matchAll(LINK)) {
        const target = match[2]!;
        const top = target.split(/[/?#$]/)[1] ?? "";
        if (!prefixes.includes(top)) continue;
        if (!/tenant/.test(target)) {
          const line = text.slice(0, match.index).split("\n").length;
          offenders.push(`${relative(SRC, file)}:${line} ${target}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
