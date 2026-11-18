/**
 * Every REGX page renders a <main> landmark.
 *
 * The shell gives each page the sidebar and nothing else; the page's own
 * <main> is what centres and pads the content and what screen readers jump to.
 * Found on the real stack (2026-11-17): the three Checklist Execution pages had
 * none, so they sat flush against the sidebar and had no main landmark.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const REGX = join(__dirname, "..", "..", "src", "app", "(regx)");

function pages(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? pages(path) : name === "page.tsx" ? [path] : [];
  });
}

describe("page landmarks", () => {
  it("every (regx) page.tsx renders <main>", () => {
    const all = pages(REGX);
    expect(all.length).toBeGreaterThan(40);
    const missing = all.filter((p) => !/<main[\s>]/.test(readFileSync(p, "utf-8")));
    expect(missing.map((p) => relative(REGX, p))).toEqual([]);
  });
});
