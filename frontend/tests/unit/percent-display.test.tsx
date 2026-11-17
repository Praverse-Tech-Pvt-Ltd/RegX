import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PercentValue } from "@/components/PercentValue";
import { formatPercentValue, isPercentUnit } from "@/lib/percent";

describe("formatPercentValue — display rounding of decimal strings", () => {
  it.each([
    ["142.8571428571428571428571429", "142.857", true],
    ["14.2857", "14.286", true],
    ["0.0005", "0.001", true],
    ["0.0004", "0.000", true],
    ["99.9995", "100.000", true],
    ["20.0", "20.000", false],
    ["14.00", "14.000", false],
    ["60", "60.000", false],
    ["12.3450", "12.345", false],
    ["-1.23456", "-1.235", true],
    ["-0.0001", "0.000", true],
  ])("%s -> %s", (input, display, rounded) => {
    const r = formatPercentValue(input);
    expect(r.display).toBe(display);
    expect(r.exact).toBe(input);
    expect(r.rounded).toBe(rounded);
  });

  it("never goes through a JS number (no float drift on long decimals)", () => {
    expect(formatPercentValue("1.0005000000000000000001").display).toBe("1.001");
    expect(formatPercentValue("123456789012345678901.4444").display).toBe("123456789012345678901.444");
  });

  it("passes anything that is not a plain decimal through unchanged", () => {
    expect(formatPercentValue("n/a").display).toBe("n/a");
    expect(formatPercentValue("1e3").display).toBe("1e3");
    expect(formatPercentValue(null).display).toBe("");
  });

  it("recognises the percentage units the calculation engines emit", () => {
    for (const u of ["percent_w_w", "percent_of_potency", "percent_of_mde"]) expect(isPercentUnit(u)).toBe(true);
    for (const u of ["milligram", "", undefined, null, 5]) expect(isPercentUnit(u)).toBe(false);
  });
});

describe("PercentValue", () => {
  it("shows 3 decimals with the exact value as tooltip and screen-reader text", () => {
    render(<PercentValue value="142.8571428571428571428571429" />);
    const el = screen.getByTestId("percent-value");
    expect(el).toHaveAttribute("title", "Exact value: 142.8571428571428571428571429");
    expect(el).toHaveAttribute("data-exact", "142.8571428571428571428571429");
    expect(el.firstChild?.textContent).toBe("142.857");
    expect(el).toHaveTextContent("(exact value 142.8571428571428571428571429)");
  });

  it("adds no screen-reader duplicate when nothing was rounded away", () => {
    render(<PercentValue value="20.0" />);
    const el = screen.getByTestId("percent-value");
    expect(el).toHaveTextContent(/^20\.000$/);
    expect(el).toHaveAttribute("title", "Exact value: 20.0");
  });
});
