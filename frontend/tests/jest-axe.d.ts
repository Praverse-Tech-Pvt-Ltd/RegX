// Ambient module declaration for jest-axe, which ships no types of its own
// (its package.json declares no "types"/"typings" field). We deliberately
// avoid @types/jest-axe because it references the global `jest` namespace,
// which this Vitest-based project doesn't have.
//
// This file has no top-level import/export, so TypeScript treats it as a
// global script and `declare module` here introduces a brand-new ambient
// module rather than trying to augment one that doesn't already have types.
declare module "jest-axe" {
  import type { AxeResults, RunOptions } from "axe-core";

  export function axe(
    html: Element | Document | string,
    options?: RunOptions,
  ): Promise<AxeResults>;

  export function configureAxe(
    options?: RunOptions,
  ): (html: Element | Document | string, options?: RunOptions) => Promise<AxeResults>;

  export const toHaveNoViolations: {
    toHaveNoViolations(results: AxeResults): {
      pass: boolean;
      message(): string;
    };
  };
}
