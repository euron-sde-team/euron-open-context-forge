import { describe, expect, it } from "vitest";

import { ApiError, errorMessage, isErrorEnvelope, parseApiError, validationMessages } from "@/lib/api/errors";

describe("parseApiError", () => {
  it("reads the gateway envelope with structured details", () => {
    const err = parseApiError(402, {
      error: { code: "budget_exceeded", type: "budget_error", message: "Budget 'x' cannot cover this request", details: { budget: "x" } },
    });
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(402);
    expect(err.code).toBe("budget_exceeded");
    expect(err.details).toEqual({ budget: "x" });
    expect(errorMessage(err)).toContain("cannot cover");
  });

  it("falls back to an actionable message for non-envelope bodies", () => {
    expect(parseApiError(500, "<html>").message).toMatch(/Retry/);
    expect(parseApiError(403, null).isForbidden).toBe(true);
    expect(parseApiError(0, null).isNetwork).toBe(true);
  });

  it("understands FastAPI's raw validation shape", () => {
    const err = parseApiError(422, { detail: [{ loc: ["body", "limit_usd"], msg: "must be positive" }] });
    expect(err.code).toBe("validation_error");
    expect(errorMessage(err)).toBe("limit_usd: must be positive");
  });
});

describe("validation and messages", () => {
  it("drops the location prefix and joins fields", () => {
    expect(validationMessages({ errors: [{ loc: ["body", "name"], msg: "required" }, { loc: [], msg: "bad" }] })).toEqual([
      "name: required",
      "bad",
    ]);
    expect(validationMessages({})).toEqual([]);
  });

  it("tells people to sign in again on 401, except for wrong credentials", () => {
    expect(errorMessage(new ApiError({ status: 401, code: "session_expired", message: "x" }))).toMatch(/Sign in again/);
    expect(errorMessage(new ApiError({ status: 401, code: "invalid_credentials", message: "Email or password is incorrect" }))).toBe(
      "Email or password is incorrect",
    );
  });

  it("maps network failures and unknown throwables", () => {
    expect(errorMessage(new TypeError("fetch failed"))).toMatch(/Cannot reach/);
    expect(errorMessage(new Error("boom"))).toBe("boom");
    expect(isErrorEnvelope({ error: { code: "x" } })).toBe(false);
  });
});
