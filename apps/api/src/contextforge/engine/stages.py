"""Pipeline stages 3 to 5: protect, clean, rank.

Each stage mutates the shared :class:`Work` state; the orchestrator in ``pipeline.py``
times them and records a trace step for each.
"""

from __future__ import annotations

from contextforge.engine.bm25 import BM25
from contextforge.engine.profiles import Profile
from contextforge.engine.state import DUPLICATE_TOOL_NOTE, DocState, MsgState, Unit, Work
from contextforge.engine.text import (
    containment,
    digest,
    extract_facts,
    identity_facts,
    importance,
    jaccard,
    normalize,
    shingles,
    split_blocks,
    terms,
)
from contextforge.engine.toolout import HARD, LIGHT, NORMAL, ReductionLevel, reduce_output
from contextforge.engine.types import Category
from contextforge.engine.validate import cited_ids

# Blocks shorter than this are never deduplicated ("ok", "Thanks!", a lone heading).
MIN_DEDUP_TOKENS = 8
# Pairwise near-duplicate detection is quadratic; beyond this many documents only exact
# duplicates are merged (documented in docs/architecture/engine.md).
NEAR_DUP_MAX_DOCS = 400
NEAR_DUP_THRESHOLD = {"conservative": 1.01, "balanced": 0.85, "aggressive": 0.7}
FIRST_TASK_BOOST = 0.25
TOOL_LEVEL: dict[str, ReductionLevel] = {
    "conservative": LIGHT,
    "balanced": NORMAL,
    "aggressive": HARD,
}


# ─── Protect ──────────────────────────────────────────────────────────────────────────


def protect(work: Work) -> None:
    opts = work.options
    msgs = work.msgs
    n = len(msgs)
    owner: dict[str, int] = {}
    for m in msgs:
        for call in m.message.tool_calls or []:
            owner[call.id] = m.index
    for m in msgs:
        if m.message.role == "tool" and m.message.tool_call_id in owner:
            m.group = owner[m.message.tool_call_id]
        elif m.message.tool_calls:
            m.group = m.index

    def mark(m: MsgState, reason: str) -> None:
        if not m.protected:
            m.protected, m.reason = True, reason

    for m in msgs:
        if m.message.role in ("system", "developer"):
            mark(m, "system")
    for m in (
        msgs[max(0, n - opts.preserve_recent_messages) :] if opts.preserve_recent_messages else []
    ):
        mark(m, "recent")
    for i in opts.pin_messages:
        mark(msgs[i], "pinned")
    latest_user = next((m for m in reversed(msgs) if m.message.role == "user"), None)
    if latest_user is not None:
        mark(latest_user, "latest_user")
    # A protected tool result needs its call, and a protected call needs its results.
    protected_groups = {m.group for m in msgs if m.protected and m.group is not None}
    for m in msgs:
        if m.group in protected_groups:
            mark(m, "tool_pair")

    known = {d.doc.id for d in work.docs}
    cited = cited_ids((m.message.text() for m in msgs if m.protected), known)
    for d in work.docs:
        if d.doc.id in cited:
            d.protected, d.reason = True, "cited"

    for needle in opts.must_keep:
        found = False
        for m in msgs:
            if needle in m.message.text():
                found = True
        for d in work.docs:
            if needle in d.doc.text:
                d.required = True
                found = True
        if not found:
            work.must_keep_missing_in_input.append(needle)
    if work.must_keep_missing_in_input:
        work.warn(
            "required_content_not_in_input",
            "Some must_keep strings do not occur in the input, so they cannot be preserved",
            missing=work.must_keep_missing_in_input,
        )


# ─── Clean ────────────────────────────────────────────────────────────────────────────


def _empty_out(m: MsgState) -> None:
    """A message whose content was entirely removed: keep what structure requires."""
    if m.message.role == "tool":
        m.override = DUPLICATE_TOOL_NOTE
    elif m.message.tool_calls:
        m.clear_content = True
        m.override = None
    else:
        m.dropped = True


def clean(work: Work) -> int:
    """Remove empty and duplicate content. Returns how many items were removed."""
    opts = work.options
    removed = 0
    level = TOOL_LEVEL[opts.strategy]
    q_terms = set(terms(work.query))

    for m in work.msgs:
        msg = m.message
        if (
            not m.protected
            and msg.role != "tool"
            and not msg.tool_calls
            and not m.atomic()
            and not msg.text().strip()
        ):
            m.dropped = True
            removed += 1

    if opts.deduplicate:
        seen: set[tuple[str, str]] = set()
        for m in reversed(work.msgs):
            if m.dropped:
                continue
            text = m.message.text()
            if not text.strip() or m.atomic():
                continue
            key = (m.message.role, normalize(text))
            if key in seen and not m.protected:
                _empty_out(m)
                removed += 1
            elif key in seen and m.reason == "system" and not opts.preserve_system_instructions:
                m.dropped = True
                removed += 1
            seen.add(key)

    for m in work.msgs:
        if m.dropped or m.protected or m.atomic() or m.override is not None or m.clear_content:
            continue
        text = m.message.text()
        if m.message.role == "tool" and opts.reduce_tool_output:
            reduced = reduce_output(text, level, q_terms)
            if reduced is not None:
                m.override = reduced
                text = reduced
                removed += 1
        m.blocks = split_blocks(text)
        for b in m.blocks:
            b.tokens = work.tok.count(b.text)

    if opts.deduplicate:
        removed += _dedup_blocks(work)

    if opts.deduplicate and opts.strategy != "conservative":
        removed += _near_dup_blocks(work)
    removed += _dedup_documents(work)
    return removed


def _dedup_blocks(work: Work) -> int:
    """Remove blocks repeated later in the conversation; the latest occurrence wins.

    Conversation text must repeat exactly (whitespace aside). Tool output is machine
    written and varies only in measurements from run to run ("collected 156 items",
    "passed in 10.10s"), so its blocks match with digits ignored, but only when the later
    block carries every identity fact (id, path, error class) of the earlier one. Two
    lookups of different orders therefore never collapse into one.
    """
    removed = 0
    exact: set[str] = set()
    fuzzy: dict[str, frozenset[str]] = {}
    for m in reversed(work.msgs):
        if m.dropped:
            continue
        tool = m.message.role == "tool"
        blocks = m.blocks if m.blocks is not None else split_blocks(m.current_text())
        kept = []
        for b in reversed(blocks):
            # Source code is never matched fuzzily: load_user_3 and load_user_24 differ.
            machine = (tool and b.kind != "code") or b.kind == "log"
            # Short conversational replies ("ok", "Thanks!") are never removed; short
            # machine-written lines ("collected 120 items") are.
            floor = 1 if machine else MIN_DEDUP_TOKENS
            big = (b.tokens or work.tok.count(b.text)) >= floor
            ekey = digest(normalize(b.text))
            fkey = digest(normalize(b.text, fuzzy_numbers=True))
            ids = identity_facts(extract_facts(b.text)) if machine else frozenset()
            duplicate = ekey in exact or (machine and fkey in fuzzy and ids <= fuzzy[fkey])
            if m.blocks is not None and big and duplicate:
                removed += 1
                continue
            if big:
                exact.add(ekey)
                if machine:
                    fuzzy[fkey] = fuzzy.get(fkey, frozenset()) | ids
            kept.append(b)
        if m.blocks is not None:
            m.blocks = list(reversed(kept))
            if not m.blocks:
                _empty_out(m)
    return removed


NEAR_DUP_MAX_BLOCKS = 600


def _near_dup_blocks(work: Work) -> int:
    """Drop prose blocks that a later block repeats almost word for word.

    Agents and chat threads repeat themselves with small variations ("Attempt 3: the test
    still fails..."). A block is removed only when a later block is a near duplicate
    (at least ``threshold`` of its word shingles occur in the later block) **and**
    every critical fact of the earlier block also occurs
    in the later one, so "port 5432" is never folded into "port 5433".
    """
    threshold = NEAR_DUP_THRESHOLD[work.options.strategy]
    entries: list[tuple[MsgState | None, int, set[int], frozenset[str]]] = []
    for m in work.msgs:
        if m.dropped:
            continue
        blocks = m.blocks if m.blocks is not None else split_blocks(m.current_text())
        for i, b in enumerate(blocks):
            if b.kind != "prose" or len(b.text) < 40:
                continue
            owner = m if m.blocks is not None else None  # None: protected, compare only
            entries.append((owner, i, shingles(b.text, size=3), extract_facts(b.text)))
    entries = entries[-NEAR_DUP_MAX_BLOCKS:]
    doomed: dict[int, set[int]] = {}
    for a_pos, (owner, idx, sig, facts) in enumerate(entries):
        if owner is None:
            continue
        for _owner, _, later_sig, later_facts in entries[a_pos + 1 :]:
            if facts <= later_facts and containment(sig, later_sig) >= threshold:
                doomed.setdefault(owner.index, set()).add(idx)
                break
    removed = 0
    for m in work.msgs:
        gone = doomed.get(m.index)
        if not gone or m.blocks is None:
            continue
        m.blocks = [b for i, b in enumerate(m.blocks) if i not in gone]
        removed += len(gone)
        if not m.blocks:
            _empty_out(m)
    return removed


def _dedup_documents(work: Work) -> int:
    opts = work.options
    removed = 0
    if not opts.deduplicate or not work.docs:
        return 0
    threshold = NEAR_DUP_THRESHOLD[opts.strategy]

    def prefer(a: DocState, b: DocState) -> tuple[DocState, DocState]:
        """(keeper, duplicate): protected and required first, then retriever score, then order."""

        def rank(d: DocState) -> tuple[int, int, float, int]:
            return (int(d.protected), int(d.required), d.doc.score or 0.0, -d.index)

        return (a, b) if rank(a) >= rank(b) else (b, a)

    by_hash: dict[str, DocState] = {}
    for d in work.docs:
        key = digest(normalize(d.doc.text))
        if key in by_hash:
            keep, dup = prefer(by_hash[key], d)
            if dup.protected:
                continue  # two protected copies: both stay
            dup.status, dup.into, dup.reason = "merged", keep.doc.id, "exact duplicate"
            by_hash[key] = keep
            removed += 1
        else:
            by_hash[key] = d
    if threshold > 1.0:
        return removed
    live = [d for d in work.docs if d.status == "kept"][:NEAR_DUP_MAX_DOCS]
    sigs = {d.index: shingles(d.doc.text) for d in live}
    for i, a in enumerate(live):
        if a.status != "kept":
            continue
        for b in live[i + 1 :]:
            if b.status != "kept":
                continue
            if jaccard(sigs[a.index], sigs[b.index]) >= threshold:
                keep, dup = prefer(a, b)
                if dup.protected:
                    continue
                dup.status, dup.into, dup.reason = "merged", keep.doc.id, "near duplicate"
                removed += 1
                if dup is a:
                    break
    # A merged chain (c into b, b into a) resolves to the final keeper.
    final = {d.doc.id: d for d in work.docs}
    for d in work.docs:
        hops = 0
        while d.status == "merged" and d.into and final[d.into].status == "merged" and hops < 50:
            d.into = final[d.into].into
            hops += 1
    return removed


# ─── Rank ─────────────────────────────────────────────────────────────────────────────


def build_units(work: Work) -> list[Unit]:
    units: list[Unit] = []
    for m in work.msgs:
        if m.dropped or m.protected:
            continue
        category: Category = "tool" if m.message.role == "tool" else "history"
        if m.atomic():
            text = m.message.text()
            unit = Unit(
                len(units),
                category,
                text,
                "prose",
                work.tok.count(text) or 1,
                extract_facts(text),
                msg_index=m.index,
            )
            m.units = [unit]
            units.append(unit)
            continue
        m.units = []
        for b in m.blocks or []:
            facts = extract_facts(b.text)
            unit = Unit(len(units), category, b.text, b.kind, b.tokens, facts, msg_index=m.index)
            unit.required = any(s in b.text for s in work.options.must_keep)
            m.units.append(unit)
            units.append(unit)
    for d in work.docs:
        if d.status != "kept" or d.protected:
            continue
        text = f"{d.doc.title}\n{d.doc.text}" if d.doc.title else d.doc.text
        unit = Unit(
            len(units),
            "documents",
            d.doc.text,
            "prose",
            work.tok.count(d.doc.text),
            extract_facts(text),
            doc_index=d.index,
        )
        unit.required = d.required
        d.unit = unit
        units.append(unit)
    return units


def rank(work: Work, units: list[Unit], profile: Profile) -> int:
    """Score every unit; drop irrelevant documents. Returns documents dropped."""
    if not units:
        return 0
    texts = []
    for u in units:
        if u.doc_index is not None and work.docs[u.doc_index].doc.title:
            texts.append(f"{work.docs[u.doc_index].doc.title}\n{u.text}")
        else:
            texts.append(u.text)
    rel = BM25(texts).normalized(work.query) if work.query else [0.0] * len(units)
    n_msgs = max(1, len(work.msgs))
    doc_scores = [d.doc.score for d in work.docs if d.doc.score is not None]
    lo, hi = (min(doc_scores), max(doc_scores)) if doc_scores else (0.0, 0.0)
    # The first user turn usually states the task; later turns refine it.
    first_user = next((m.index for m in work.msgs if m.message.role == "user"), None)
    for i, u in enumerate(units):
        relevance = rel[i]
        if u.doc_index is not None:
            score = work.docs[u.doc_index].doc.score
            if score is not None and hi > lo:
                relevance = 0.7 * relevance + 0.3 * ((score - lo) / (hi - lo))
            recency = 0.5
        else:
            recency = ((u.msg_index or 0) + 1) / n_msgs
        u.relevance = relevance
        u.score = (
            profile.relevance * relevance
            + profile.recency * recency
            + profile.importance * importance(u.text, u.kind, u.facts)
            + (FIRST_TASK_BOOST if u.msg_index is not None and u.msg_index == first_user else 0.0)
        )
    dropped = 0
    opts = work.options
    q_terms = set(terms(work.query))
    if (
        opts.rank_documents
        and opts.drop_irrelevant_documents
        and q_terms
        and opts.strategy != "conservative"
    ):
        for i, u in enumerate(units):
            if u.doc_index is None or u.required:
                continue
            if rel[i] == 0.0:
                d = work.docs[u.doc_index]
                d.status, d.reason = "dropped", "no overlap with the query"
                dropped += 1
    if opts.max_documents is not None:
        live = sorted(
            (
                u
                for u in units
                if u.doc_index is not None and work.docs[u.doc_index].status == "kept"
            ),
            key=lambda x: (-int(x.required), -x.score),
        )
        protected_docs = sum(1 for d in work.docs if d.protected and d.status == "kept")
        for k, u in enumerate(live):
            beyond = protected_docs + k >= opts.max_documents
            if beyond and not u.required and u.doc_index is not None:
                d = work.docs[u.doc_index]
                d.status, d.reason = "dropped", "beyond max_documents"
                dropped += 1
    return dropped
