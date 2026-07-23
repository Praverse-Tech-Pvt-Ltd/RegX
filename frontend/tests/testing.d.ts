// Augments Vitest's Assertion with the toHaveNoViolations matcher that
// vitest.setup.ts registers via expect.extend(toHaveNoViolations).
interface AxeMatchers<R = unknown> {
  toHaveNoViolations(): R;
}

declare module "vitest" {
  interface Assertion<T = unknown> extends AxeMatchers<T> {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}

export {};
