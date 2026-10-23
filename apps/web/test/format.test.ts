import { describe, expect, it } from "vitest";

import {
  computeDelta,
  formatBytes,
  formatDelta,
  formatDuration,
  formatLatency,
  formatNumber,
  formatPercent,
  formatRatio,
  formatTokens,
  formatUsd,
  formatUsdAxis,
  formatUsdCompact,
} from "@/lib/format";

describe("formatUsd", () => {
  it("formats normal amounts with cents and grouping", () => {
    expect(formatUsd(1234.5)).toBe("$1,234.50");
    expect(formatUsd(0)).toBe("$0.00");
  });
  it("keeps three significant digits for tiny per-request costs", () => {
    expect(formatUsd(0.000412)).toBe("$0.000412");
    expect(formatUsd(0.0307)).toBe("$0.0307");
    expect(formatUsd(0.5)).toBe("$0.50");
  });
  it("handles negatives, sub-micro amounts and missing values", () => {
    expect(formatUsd(-0.000412)).toBe("-$0.000412");
    expect(formatUsd(0.0000001)).toBe("<$0.000001");
    expect(formatUsd(null)).toBe("n/a");
    expect(formatUsd(Number.NaN)).toBe("n/a");
  });
});

describe("compact and axis money", () => {
  it("compacts large amounts only", () => {
    expect(formatUsdCompact(12_345)).toBe("$12.3K");
    expect(formatUsdCompact(2_500_000)).toBe("$2.5M");
    expect(formatUsdCompact(950)).toBe("$950.00");
  });
  it("keeps axis ticks short", () => {
    expect(formatUsdAxis(0)).toBe("$0");
    expect(formatUsdAxis(8)).toBe("$8");
    expect(formatUsdAxis(0.45)).toBe("$0.45");
    expect(formatUsdAxis(1500)).toBe("$1,500.00");
  });
});

describe("counts, ratios and durations", () => {
  it("abbreviates tokens", () => {
    expect(formatTokens(845)).toBe("845");
    expect(formatTokens(12_400)).toBe("12.4K");
    expect(formatTokens(13_951_478)).toBe("14M");
    expect(formatTokens(1_200_000_000)).toBe("1.2B");
  });
  it("formats numbers, ratios and percents", () => {
    expect(formatNumber(14923)).toBe("14,923");
    expect(formatRatio(0.2462)).toBe("24.6%");
    expect(formatPercent(60)).toBe("60%");
    expect(formatPercent(60.44)).toBe("60.4%");
  });
  it("formats latency, durations and bytes", () => {
    expect(formatLatency(610.4)).toBe("610 ms");
    expect(formatLatency(1240)).toBe("1.24 s");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(900)).toBe("15 min");
    expect(formatDuration(86_400 * 7)).toBe("7 d");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
  });
});

describe("deltas", () => {
  it("computes signed change against the previous period", () => {
    expect(computeDelta(150, 100)).toEqual({ pct: 50, direction: "up" });
    expect(computeDelta(75, 100)?.direction).toBe("down");
    expect(computeDelta(100, 100)?.direction).toBe("flat");
  });
  it("returns null without a baseline", () => {
    expect(computeDelta(10, 0)).toBeNull();
    expect(computeDelta(10, null)).toBeNull();
  });
  it("formats deltas compactly", () => {
    expect(formatDelta({ pct: 36.64, direction: "up" })).toBe("+36.6%");
    expect(formatDelta({ pct: -14.9, direction: "down" })).toBe("-14.9%");
    expect(formatDelta({ pct: 250, direction: "up" })).toBe("+250%");
    expect(formatDelta({ pct: 0.01, direction: "flat" })).toBe("0%");
  });
});
