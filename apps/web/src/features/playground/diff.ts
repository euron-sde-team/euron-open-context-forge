import type { ChatMessage } from "@/lib/api/types";

export type MessageStatus = "kept" | "shortened" | "removed" | "summary" | "added";

function body(m: ChatMessage): string {
  if (typeof m.content === "string") return m.content;
  if (Array.isArray(m.content)) return m.content.map((p) => p.text ?? "").join("\n");
  return "";
}

function identity(m: ChatMessage): string {
  return JSON.stringify([m.role, body(m), m.tool_call_id ?? null, (m.tool_calls ?? []).map((c) => c.id)]);
}

export function isSummary(m: ChatMessage): boolean {
  return body(m).startsWith("[ContextForge summary of");
}

/**
 * Line up the input and output message lists for the before/after view.
 *
 * The engine never reorders messages, so a single forward walk is enough: an output
 * message identical to the next unmatched input is "kept"; one with the same role (and
 * tool call id) but different text is "shortened"; the summary is its own kind; inputs
 * passed over are "removed".
 */
export function messageStatuses(
  before: ChatMessage[],
  after: ChatMessage[],
): { before: MessageStatus[]; after: MessageStatus[] } {
  const b: MessageStatus[] = before.map(() => "removed");
  const a: MessageStatus[] = after.map(() => "added");
  let i = 0;
  after.forEach((out, j) => {
    if (isSummary(out)) {
      a[j] = "summary";
      return;
    }
    for (let k = i; k < before.length; k++) {
      const inp = before[k];
      if (!inp) continue;
      if (identity(inp) === identity(out)) {
        b[k] = "kept";
        a[j] = "kept";
        i = k + 1;
        return;
      }
      const sameSlot =
        inp.role === out.role &&
        (inp.tool_call_id ?? null) === (out.tool_call_id ?? null) &&
        JSON.stringify((inp.tool_calls ?? []).map((c) => c.id)) === JSON.stringify((out.tool_calls ?? []).map((c) => c.id));
      const related = sameSlot && (body(inp).includes(body(out).split("[...]")[0]?.slice(0, 40) ?? "") || inp.tool_call_id != null || (inp.tool_calls?.length ?? 0) > 0);
      if (related) {
        b[k] = "shortened";
        a[j] = "shortened";
        i = k + 1;
        return;
      }
    }
  });
  return { before: b, after: a };
}
