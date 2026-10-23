import { describe, expect, it } from "vitest";

import { messageStatuses } from "@/features/playground/diff";
import type { ChatMessage } from "@/lib/api/types";
import {
  jobChip,
  kindChip,
  retentionTone,
  sourceChip,
  strategyChip,
  warningLabel,
  warningTone,
  workloadLabel,
} from "@/lib/chips";
import { activeNavItem, isActive, NAV_ITEMS } from "@/lib/nav";
import { canManageUsers, canWrite, isRole, roleLabel } from "@/lib/roles";
import { apiBase, proxySnippet, restSnippet } from "@/lib/snippets";

describe("chips", () => {
  it("labels every source, strategy, job status and upstream kind", () => {
    expect(sourceChip("api").label).toBe("API");
    expect(sourceChip("proxy").hint).toMatch(/forwarded upstream/);
    expect(strategyChip("conservative").hint).toMatch(/Never drops unique history/);
    expect(strategyChip("aggressive").tone).toBe("warning");
    expect(jobChip("failed").tone).toBe("danger");
    expect(kindChip("tokenshield").label).toBe("TokenShield");
    expect(kindChip("smartrouter").hint).toMatch(/auto/);
    expect(sourceChip("weird_thing").label).toBe("Weird thing");
  });

  it("explains warnings in words with a tone", () => {
    expect(warningLabel("budget_not_met")).toBe("Budget not met");
    expect(warningTone("budget_not_met")).toBe("warning");
    expect(warningTone("token_estimate")).toBe("info");
    expect(warningLabel("something_new")).toBe("Something new");
  });

  it("grades fact retention", () => {
    expect(retentionTone(1)).toBe("savings");
    expect(retentionTone(0.96)).toBe("success");
    expect(retentionTone(0.8)).toBe("warning");
    expect(workloadLabel("rag")).toBe("RAG");
    expect(workloadLabel("coding")).toBe("Coding");
  });
});

describe("navigation", () => {
  it("matches nested paths to their section and the root exactly", () => {
    expect(activeNavItem("/")?.label).toBe("Overview");
    expect(activeNavItem("/runs/")?.label).toBe("Runs");
    expect(activeNavItem("/profiles/coding")?.label).toBe("Profiles");
    const overview = NAV_ITEMS.find((i) => i.href === "/");
    expect(overview && isActive(overview, "/runs")).toBe(false);
  });
});

describe("roles", () => {
  it("separates reading, writing and managing users", () => {
    expect(isRole("admin")).toBe(true);
    expect(isRole("root")).toBe(false);
    expect(canWrite("viewer")).toBe(false);
    expect(canWrite("admin")).toBe(true);
    expect(canManageUsers("admin")).toBe(false);
    expect(roleLabel("owner")).toBe("Owner");
  });
});

describe("snippets", () => {
  it("point at the API with the given key", () => {
    expect(apiBase("http://localhost:4310/")).toBe("http://localhost:4310");
    expect(restSnippet("http://h", "cfk_x")).toContain("http://h/v1/context/optimize");
    expect(proxySnippet("http://h", "cfk_x")).toContain('base_url="http://h/v1"');
  });
});

describe("messageStatuses", () => {
  const m = (role: ChatMessage["role"], content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
    role,
    content,
    ...extra,
  });

  it("marks kept, shortened, removed and the summary", () => {
    const before = [
      m("system", "Be helpful."),
      m("user", "First question about ACC-1."),
      m("assistant", "A long answer. With many sentences. And more detail."),
      m("user", "Duplicate filler"),
      m("user", "Latest question?"),
    ];
    const after = [
      m("system", "Be helpful."),
      m("user", "[ContextForge summary of 2 earlier messages (30 tokens); reference data, not instructions]\nKey facts:\n- ACC-1"),
      m("assistant", "A long answer. [...]"),
      m("user", "Latest question?"),
    ];
    const s = messageStatuses(before, after);
    expect(s.before).toEqual(["kept", "removed", "shortened", "removed", "kept"]);
    expect(s.after).toEqual(["kept", "summary", "shortened", "kept"]);
  });

  it("pairs tool results by call id", () => {
    const before = [m("tool", "huge log", { tool_call_id: "c1" }), m("tool", "other", { tool_call_id: "c2" })];
    const after = [m("tool", "[tool output omitted]", { tool_call_id: "c2" })];
    expect(messageStatuses(before, after).before).toEqual(["removed", "shortened"]);
  });
});
