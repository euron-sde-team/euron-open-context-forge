"""Pipeline stage 6: fit the context to the budget and rebuild the message list.

Selection runs in three passes:

1. **Required** units (they contain a ``must_keep`` string) are always kept.
2. **Per category**: each category (history, tool output, documents) receives its share
   of the budget from the workload profile; units are taken best score first. A unit that
   no longer fits may be kept as an extractive excerpt of its best sentences.
3. **Fill**: whatever a category left unused is offered to the best remaining units of
   any category, keeping room for the summary.

Then the message list is rebuilt in its original order. A tool call and its results are
kept or dropped together, so the structure stays valid. Everything dropped from the
history goes to the summarizer, which writes into exactly the room that is left. If the
exact recount still exceeds the budget (message framing, gap markers), the lowest-scored
units are dropped and the summary regenerated, a few times at most.
"""

from __future__ import annotations

from dataclasses import dataclass

from contextforge.engine.bm25 import BM25
from contextforge.engine.profiles import CATEGORIES, Profile, allocate
from contextforge.engine.state import MsgState, Unit, Work
from contextforge.engine.summarizer import Summarizer, SummaryInput, SummaryOutput, SummaryUnit
from contextforge.engine.text import extract_facts, split_sentences
from contextforge.engine.tokenizers import (
    REPLY_PRIMING,
    document_tokens,
    documents_tokens,
    message_tokens,
    messages_tokens,
)
from contextforge.engine.toolout import NORMAL, reduce_output
from contextforge.engine.types import (
    Allocation,
    Category,
    ContentPart,
    Document,
    Message,
)

GAP = "[...]"
JOIN_COST = 2
MIN_PARTIAL_TOKENS = 24
EXTRACT_VERIFY_ROUNDS = 4
MIN_SUMMARY_TOKENS = 32
SUMMARY_FLOOR = 72
MAX_REPAIR_ROUNDS = 8


@dataclass(slots=True)
class Assembled:
    messages: list[Message]
    documents: list[Document]
    summary: SummaryOutput | None
    allocation: list[Allocation]
    tokens: int
    notes: list[str]


def _overhead(m: MsgState, work: Work) -> int:
    shell = m.message.model_copy(update={"content": ""})
    return message_tokens(shell, work.tok)


def _render(m: MsgState) -> str | None:
    """The rebuilt text of an unprotected, partially kept message (None: nothing kept)."""
    if not m.units:
        return m.current_text() if not m.atomic() else None
    if m.atomic():
        return m.message.text() if m.units[0].keep else None
    parts: list[str] = []
    gap = False
    for u in m.units:
        if u.keep:
            if gap and (not parts or parts[-1] != GAP):
                parts.append(GAP)
            parts.append(u.output_text())
            gap = False
        else:
            gap = True
    if not parts:
        return None
    if gap:
        parts.append(GAP)
    return "\n\n".join(parts)


def _with_text(message: Message, text: str | None) -> Message:
    if text is None:
        return message.model_copy(update={"content": None if message.tool_calls else ""})
    if isinstance(message.content, list):
        return message.model_copy(update={"content": [ContentPart(type="text", text=text)]})
    return message.model_copy(update={"content": text})


def _extract(unit: Unit, limit: int, work: Work, scorer_query: str) -> tuple[str, int] | None:
    """Best sentences of ``unit`` in original order, within ``limit`` tokens."""
    if unit.kind not in ("prose", "list") or limit < MIN_PARTIAL_TOKENS:
        return None
    sentences = split_sentences(unit.text)
    if len(sentences) < 3:
        return None
    rel = BM25(sentences).normalized(scorer_query) if scorer_query else [0.0] * len(sentences)
    must = work.options.must_keep
    scored = sorted(
        range(len(sentences)),
        key=lambda i: (
            -(
                rel[i]
                + 0.25 * min(3, len(extract_facts(sentences[i])))
                + (10.0 if any(s in sentences[i] for s in must) else 0.0)
                + (0.05 if i == 0 else 0.0)
            )
        ),
    )
    # Each sentence is counted once (with its joining space) and the selection is costed
    # arithmetically, then verified with one exact count. Re-counting the joined text per
    # candidate was quadratic in the number of sentences.
    cost = [work.tok.count(" " + s) for s in sentences]
    gap = work.tok.count(" " + GAP)
    target = limit - gap  # room for a trailing marker
    chosen: list[int] = []
    for _ in range(EXTRACT_VERIFY_ROUNDS):
        picked: set[int] = set()
        used = 0
        for i in scored:
            extra = cost[i] + _gap_delta(picked, i) * gap
            if used + extra <= target:
                picked.add(i)
                used += extra
        chosen = sorted(picked)
        if not chosen:
            return None
        text = _join_sentences(sentences, chosen)
        tokens = work.tok.count(text)
        if tokens <= limit:
            break
        # The estimate ran over (token merges across joins): tighten and try again.
        target -= tokens - limit + 1
    else:
        return None
    if tokens >= unit.tokens * 0.9:
        return None
    return text, tokens


def _gap_delta(picked: set[int], i: int) -> int:
    """Upper bound on the gap markers adding sentence ``i`` costs: one unless it extends a run."""
    return 0 if (i - 1 in picked or i + 1 in picked) else 1


def _join_sentences(sentences: list[str], idx: list[int]) -> str:
    out: list[str] = []
    prev = -1
    for i in idx:
        if out and i != prev + 1:
            out.append(GAP)
        out.append(sentences[i])
        prev = i
    if idx and idx[-1] != len(sentences) - 1:
        out.append(GAP)
    return " ".join(out)


class Assembler:
    def __init__(self, work: Work, units: list[Unit], profile: Profile, summarizer: Summarizer):
        self.work = work
        self.units = units
        self.profile = profile
        self.summarizer = summarizer
        self.notes: list[str] = []
        self._overheads: dict[int, int] = {}

    # ── helpers ──
    def overhead(self, m: MsgState) -> int:
        if m.index not in self._overheads:
            self._overheads[m.index] = _overhead(m, self.work)
        return self._overheads[m.index]

    def _unit_cost(self, u: Unit, opened: set[int]) -> int:
        if u.doc_index is not None:
            return (
                document_tokens(self.work.docs[u.doc_index].doc, self.work.tok)
                - u.tokens
                + u.cost()
            )
        cost = u.cost() + JOIN_COST
        if u.msg_index is not None and u.msg_index not in opened:
            cost += self.overhead(self.work.msgs[u.msg_index])
        return cost

    def live_units(self) -> list[Unit]:
        out = []
        for u in self.units:
            if u.doc_index is not None and self.work.docs[u.doc_index].status != "kept":
                continue
            out.append(u)
        return out

    # ── main ──
    def run(self, budget: int | None) -> Assembled:
        work = self.work
        live = self.live_units()
        for u in live:
            u.keep = True
        if budget is None:
            return self._finish(None, {}, want_summary=False)
        everything = self._count(*self._build(None))
        if everything <= budget:
            return self._finish(budget, {}, want_summary=False, counted=everything)
        if work.options.strategy == "aggressive" and work.options.reduce_tool_output:
            self._reduce_protected_tools()
        if work.options.strategy == "conservative":
            self.notes.append("conservative: only duplicates and tool output bulk are removed")
            return self._finish(budget, {}, want_summary=False)

        for u in live:
            u.keep = False
        base = REPLY_PRIMING + sum(
            message_tokens(self._protected_form(m), work.tok)
            for m in work.msgs
            if m.protected and not m.dropped
        )
        base += documents_tokens(
            (d.doc for d in work.docs if d.protected and d.status == "kept"), work.tok
        )
        opened: set[int] = set()
        required_cost = 0
        for u in live:
            if u.required:
                required_cost += self._unit_cost(u, opened)
                u.keep = True
                if u.msg_index is not None:
                    opened.add(u.msg_index)
        available = budget - base - required_cost
        want_summary = work.options.summarize_history
        demand: dict[Category, int] = dict.fromkeys(CATEGORIES, 0)
        demand_open: set[int] = set(opened)
        for u in live:
            if not u.keep:
                demand[u.category] += self._unit_cost(u, demand_open)
                if u.msg_index is not None:
                    demand_open.add(u.msg_index)
        if want_summary:
            history_demand = demand["history"] + demand["tool"]
            demand["summary"] = min(4000, max(200, int(0.35 * history_demand)))
        weights = self.profile.normalized()
        if not want_summary:
            weights["summary"] = 0.0
        alloc = allocate(max(0, available), demand, weights)
        # A summary carries the key sentences of many dropped messages in the room one of
        # them would take, so it gets a floor whenever there is room for it at all.
        floor = min(SUMMARY_FLOOR, available // 2)
        if want_summary and alloc["summary"] < floor and floor >= MIN_SUMMARY_TOKENS:
            need = floor - alloc["summary"]
            donor: Category = max(("history", "tool", "documents"), key=lambda c: alloc[c])
            moved = min(need, alloc[donor])
            alloc[donor] -= moved
            alloc["summary"] += moved
        used: dict[Category, int] = dict.fromkeys(CATEGORIES, 0)

        query = work.query
        categories: tuple[Category, ...] = ("history", "tool", "documents")
        for category in categories:
            cands = sorted(
                (u for u in live if u.category == category and not u.keep),
                key=lambda x: (-x.score, x.uid),
            )
            for u in cands:
                left = alloc[category] - used[category]
                cost = self._unit_cost(u, opened)
                if cost <= left:
                    self._keep(u, opened)
                    used[category] += cost
                    continue
                part = _extract(u, left - (cost - u.tokens), work, query)
                if part is not None:
                    u.partial_text, u.partial_tokens = part
                    cost = self._unit_cost(u, opened)
                    if cost <= left:
                        self._keep(u, opened)
                        used[category] += cost
                    else:
                        u.partial_text, u.partial_tokens = None, 0

        spare = max(0, available - alloc["summary"] - sum(used.values()))
        for u in sorted((x for x in live if not x.keep), key=lambda x: (-x.score, x.uid)):
            cost = self._unit_cost(u, opened)
            if cost > spare:
                part = _extract(u, spare - (cost - u.tokens), work, query)
                if part is None:
                    continue
                u.partial_text, u.partial_tokens = part
                cost = self._unit_cost(u, opened)
                if cost > spare:
                    u.partial_text, u.partial_tokens = None, 0
                    continue
            self._keep(u, opened)
            used[u.category] += cost
            spare -= cost
        return self._finish(budget, alloc, want_summary=want_summary)

    def _keep(self, u: Unit, opened: set[int]) -> None:
        u.keep = True
        if u.msg_index is not None:
            opened.add(u.msg_index)

    def _protected_form(self, m: MsgState) -> Message:
        return _with_text(m.message, m.override) if m.override is not None else m.message

    def _reduce_protected_tools(self) -> None:
        from contextforge.engine.text import terms

        q = set(terms(self.work.query))
        n = 0
        for m in self.work.msgs:
            if m.protected and m.message.role == "tool" and not m.atomic():
                reduced = reduce_output(m.message.text(), NORMAL, q)
                if reduced is not None:
                    m.override = reduced
                    n += 1
        if n:
            self.notes.append(f"aggressive: reduced {n} recent tool output(s), errors kept")

    # ── rebuild ──
    def _retained_groups(self) -> set[int]:
        groups: set[int] = set()
        for m in self.work.msgs:
            if m.dropped or m.group is None:
                continue
            if m.protected or any(u.keep for u in m.units):
                groups.add(m.group)
        return groups

    def _build(self, summary: SummaryOutput | None) -> tuple[list[Message], list[Document]]:
        work = self.work
        groups = self._retained_groups()
        out: list[Message] = []
        lead = 0
        for m in work.msgs:
            if m.dropped:
                continue
            if m.protected:
                out.append(self._protected_form(m))
                if m.message.role in ("system", "developer") and len(out) == lead + 1:
                    lead = len(out)
                continue
            text = _render(m)
            if m.group is not None:
                if m.group not in groups:
                    continue
                if text is None and m.message.role == "tool":
                    tokens = work.tok.count(m.message.text())
                    text = (
                        f"[tool output omitted by ContextForge ({tokens:,} tokens); "
                        "key lines are in the summary]"
                    )
            elif text is None:
                continue
            if m.clear_content and not any(u.keep for u in m.units):
                text = None
            out.append(_with_text(m.message, text))
        if summary is not None and summary.text:
            role = work.options.summary_role
            out.insert(lead, Message(role=role, content=summary.text))
        docs: list[Document] = []
        ranked = sorted(
            (d for d in work.docs if d.status == "kept"),
            key=lambda d: (
                0 if d.protected else 1,
                -(d.unit.score if d.unit and work.options.rank_documents else 0.0),
                d.index,
            ),
        )
        for d in ranked:
            if d.protected or d.unit is None or d.unit.keep:
                text = d.unit.output_text() if d.unit is not None else d.doc.text
                docs.append(d.doc.model_copy(update={"text": text}))
        return out, docs

    def _count(self, msgs: list[Message], docs: list[Document]) -> int:
        return messages_tokens(msgs, self.work.tok) + documents_tokens(docs, self.work.tok)

    def _summary_units(self) -> tuple[list[SummaryUnit], int, int]:
        units: list[SummaryUnit] = []
        dropped_msgs = 0
        tokens = 0
        groups = self._retained_groups()
        for m in self.work.msgs:
            if m.dropped or m.protected:
                continue
            gone = [u for u in m.units if not u.keep]
            if not gone:
                continue
            whole = not any(u.keep for u in m.units) and not (
                m.group is not None and m.group in groups
            )
            dropped_msgs += int(whole)
            for u in gone:
                tokens += u.tokens
                units.append(SummaryUnit(m.message.role, m.index, u.text, u.kind))
        return units, dropped_msgs, tokens

    def _summarize(self, room: int) -> SummaryOutput | None:
        units, dropped_msgs, tokens = self._summary_units()
        if not units or room < MIN_SUMMARY_TOKENS:
            return None
        later = (
            "\n".join(u.output_text() for u in self.units if u.keep and u.msg_index is not None)
            + "\n"
            + "\n".join(m.message.text() for m in self.work.msgs if m.protected)
        )
        data = SummaryInput(
            units=units,
            query=self.work.query,
            budget_tokens=room,
            count=self.work.tok.count,
            later_text=later,
            messages_dropped=max(1, dropped_msgs),
            tokens_dropped=tokens,
        )
        out = self.summarizer.summarize(data)
        return out if out.text else None

    def _finish(
        self,
        budget: int | None,
        alloc: dict[Category, int],
        *,
        want_summary: bool,
        counted: int | None = None,
    ) -> Assembled:
        summary: SummaryOutput | None = None
        msgs, docs = self._build(None)
        total = counted if counted is not None else self._count(msgs, docs)
        for _ in range(MAX_REPAIR_ROUNDS):
            summary = None
            if want_summary and budget is not None:
                shell = Message(role=self.work.options.summary_role, content="")
                room = budget - total - message_tokens(shell, self.work.tok) - 2
                summary = self._summarize(room)
                if summary is not None:
                    msgs, docs = self._build(summary)
                    total = self._count(msgs, docs)
            if budget is None or total <= budget:
                break
            if self.work.options.strategy == "conservative":
                break
            deficit = total - budget
            victims = sorted(
                (u for u in self.live_units() if u.keep and not u.required),
                key=lambda x: (x.score, -x.uid),
            )
            if not victims:
                break
            freed = 0
            for u in victims:
                u.keep = False
                freed += u.cost() + JOIN_COST
                if freed >= deficit:
                    break
            msgs, docs = self._build(None)
            total = self._count(msgs, docs)
        allocation = self._allocation(alloc, summary)
        return Assembled(msgs, docs, summary, allocation, total, self.notes)

    def _allocation(
        self, alloc: dict[Category, int], summary: SummaryOutput | None
    ) -> list[Allocation]:
        weights = self.profile.normalized()
        used: dict[Category, int] = dict.fromkeys(CATEGORIES, 0)
        for u in self.live_units():
            if u.keep:
                used[u.category] += u.cost()
        used["summary"] = summary.tokens if summary else 0
        return [
            Allocation(
                category=c, weight=round(weights[c], 4), budget=alloc.get(c, 0), used=used[c]
            )
            for c in CATEGORIES
        ]
