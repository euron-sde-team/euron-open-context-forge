"""Adaptive context budgeting: split the budget by what this workload actually needs.

A flat "compress by 60%" treats a coding agent and a research question the same. A coding
turn needs the current task, the files in play and the latest errors; a research question
needs source passages and their citations. A profile names those priorities as category
weights (history, tool output, documents, summary) plus ranking weights (relevance,
recency, importance). The allocator gives each category ``weight * available`` tokens,
then hands whatever a category does not need to the others, in weight order, so no budget
is wasted on a category with little content.

System instructions, recent turns and pinned content are protected before any of this
runs: they are never part of the allocation and never squeezed to make room.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contextforge.engine.types import Category, Document, Message, ResolvedWorkload

CATEGORIES: tuple[Category, ...] = ("history", "tool", "documents", "summary")


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    description: str
    weights: dict[Category, float]
    relevance: float
    recency: float
    importance: float
    builtin: bool = True
    # Free-form notes shown in the dashboard.
    tags: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> dict[Category, float]:
        total = sum(max(0.0, self.weights.get(c, 0.0)) for c in CATEGORIES) or 1.0
        return {c: max(0.0, self.weights.get(c, 0.0)) / total for c in CATEGORIES}


BUILTIN_PROFILES: dict[str, Profile] = {
    p.name: p
    for p in (
        Profile(
            "coding",
            "Current task, files in play and the latest errors first",
            {"history": 0.30, "tool": 0.35, "documents": 0.20, "summary": 0.15},
            relevance=0.40,
            recency=0.30,
            importance=0.30,
            tags=("code", "errors"),
        ),
        Profile(
            "agent",
            "Long-running tool use: results and decisions, not intermediate noise",
            {"history": 0.25, "tool": 0.40, "documents": 0.15, "summary": 0.20},
            relevance=0.35,
            recency=0.35,
            importance=0.30,
            tags=("tools", "memory"),
        ),
        Profile(
            "research",
            "Source passages, citations and conflicting evidence",
            {"history": 0.20, "tool": 0.10, "documents": 0.55, "summary": 0.15},
            relevance=0.60,
            recency=0.10,
            importance=0.30,
            tags=("citations",),
        ),
        Profile(
            "rag",
            "Retrieved chunks relevant to the question, deduplicated and reranked",
            {"history": 0.15, "tool": 0.05, "documents": 0.65, "summary": 0.15},
            relevance=0.65,
            recency=0.10,
            importance=0.25,
            tags=("retrieval", "citations"),
        ),
        Profile(
            "support",
            "The customer's goal, account facts and what was already tried",
            {"history": 0.50, "tool": 0.10, "documents": 0.20, "summary": 0.20},
            relevance=0.35,
            recency=0.30,
            importance=0.35,
            tags=("conversation",),
        ),
        Profile(
            "chat",
            "General conversation: recent turns and the thread's key facts",
            {"history": 0.60, "tool": 0.05, "documents": 0.15, "summary": 0.20},
            relevance=0.35,
            recency=0.40,
            importance=0.25,
            tags=("conversation",),
        ),
    )
}

_RESEARCH_HINTS = (
    "compare",
    "evidence",
    "sources",
    "cite",
    "according to",
    "studies",
    "contradict",
)


def detect_workload(messages: list[Message], documents: list[Document]) -> ResolvedWorkload:
    """Deterministic guess from the shape of the input. Callers can always override it."""
    tool_msgs = sum(1 for m in messages if m.role == "tool")
    calls = sum(len(m.tool_calls or []) for m in messages)
    text = "\n".join(m.text() for m in messages[-12:])
    code_signals = text.count("```") // 2 + text.count("Traceback") + text.count("    at ")
    if documents and tool_msgs < 3:
        last_user = next((m.text().lower() for m in reversed(messages) if m.role == "user"), "")
        if len(documents) >= 3 and any(h in last_user for h in _RESEARCH_HINTS):
            return "research"
        return "rag"
    if tool_msgs + calls >= 6 and code_signals < 2:
        return "agent"
    if code_signals >= 2 or (tool_msgs >= 3 and code_signals >= 1):
        return "coding"
    if tool_msgs >= 3:
        return "agent"
    return "chat"


def allocate(
    available: int,
    demand: dict[Category, int],
    weights: dict[Category, float],
) -> dict[Category, int]:
    """Water-filling: weighted shares, capped by demand, surplus redistributed by weight.

    Deterministic and exact: the shares never sum to more than ``available``.
    """
    alloc: dict[Category, int] = dict.fromkeys(CATEGORIES, 0)
    remaining = max(0, available)
    open_cats = [c for c in CATEGORIES if demand.get(c, 0) > 0 and weights.get(c, 0) > 0]
    # Categories with demand but zero weight still receive surplus after the others.
    zero_weight = [c for c in CATEGORIES if demand.get(c, 0) > 0 and weights.get(c, 0) <= 0]
    while remaining > 0 and open_cats:
        total_w = sum(weights[c] for c in open_cats)
        satisfied: list[Category] = []
        handed = 0
        for c in open_cats:
            share = int(remaining * weights[c] / total_w)
            need = demand[c] - alloc[c]
            give = min(share, need)
            alloc[c] += give
            handed += give
            if alloc[c] >= demand[c]:
                satisfied.append(c)
        remaining -= handed
        if not satisfied:
            # Shares all fell short of demand: distribute the rounding remainder and stop.
            for c in sorted(open_cats, key=lambda x: -weights[x]):
                if remaining <= 0:
                    break
                extra = min(remaining, demand[c] - alloc[c])
                alloc[c] += extra
                remaining -= extra
            break
        open_cats = [c for c in open_cats if c not in satisfied]
    for c in zero_weight:
        extra = min(remaining, demand[c] - alloc[c])
        alloc[c] += extra
        remaining -= extra
    return alloc
