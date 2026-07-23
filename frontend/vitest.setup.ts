import "@testing-library/jest-dom/vitest";
import { afterEach, expect } from "vitest";
import { cleanup } from "@testing-library/react";
import { toHaveNoViolations } from "jest-axe";

// jest-axe ships a matcher that works with any expect.extend-compatible runner.
expect.extend(toHaveNoViolations);

afterEach(() => {
  cleanup();
});
