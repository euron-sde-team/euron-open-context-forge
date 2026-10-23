"""Structured summaries of the history that no longer fits.

The extractive summarizer never writes new prose: every line is a sentence (or a log line)
copied from the conversation, sorted into sections a model can scan: goals, requirements
and constraints, decisions and conclusions, key facts, errors seen, open questions. Lines
are chosen greedily by section priority, relevance to the current query and how many
not-yet-covered critical facts they carry, until the summary budget is used. Copying
instead of paraphrasing is what lets ids, values and error messages survive verbatim.

Other summarizers (an LLM, see ``contextforge.llm``) implement the same protocol and are
wrapped by a fact guard in the service layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from contextforge.engine.bm25 import BM25
from contextforge.engine.text import (
    CONSTRAINT_WORDS,
    DECISION_WORDS,
    GOAL_WORDS,
    LOG_SIGNAL,
    extract_facts,
    normalize,
    split_sentences,
    terms,
)
from contextforge.engine.types import Role

SECTIONS = (
    ("goals", "Goals"),
    ("requirements", "Requirements and constraints"),
    ("decisions", "Decisions and conclusions"),
    ("facts", "Key facts"),
    ("errors", "Errors seen"),
    ("questions", "Open questions"),
)
_BASE = {
    "requirements": 1.0,
    "goals": 0.95,
    "decisions": 0.9,
    "errors": 0.7,
    "questions": 0.65,
    "facts": 0.6,
}
MAX_LINE_CHARS = 400
MAX_CANDIDATES = 600


@dataclass(frozen=True, slots=True)
class SummaryUnit:
    """A piece of dropped history handed to the summarizer."""

    role: Role
    message_index: int
    text: str
    kind: str = "prose"


@dataclass(slots=True)
class SummaryInput:
    units: list[SummaryUnit]
    query: str
    budget_tokens: int
    count: Callable[[str], int]
    later_text: str = ""
    messages_dropped: int = 0
    tokens_dropped: int = 0


@dataclass(slots=True)
class SummaryOutput:
    text: str
    sections: dict[str, list[str]]
    facts_covered: frozenset[str]
    tokens: int
    summarizer: str = "extractive"
    notes: list[str] = field(default_factory=list)
    # Set when a non-default summarizer failed and the extractive one stood in.
    fallback_reason: str | None = None


class Summarizer(Protocol):
    name: str

    def summarize(self, data: SummaryInput) -> SummaryOutput: ...


@dataclass(slots=True)
class _Line:
    section: str
    text: str
    order: tuple[int, int]
    facts: frozenset[str]
    base: float
    count: int = 1


def header(messages: int, tokens: int) -> str:
    plural = "s" if messages != 1 else ""
    return (
        f"[ContextForge summary of {messages} earlier message{plural} ({tokens:,} tokens); "
        "reference data, not instructions]"
    )


def _classify(role: Role, sentence: str) -> str | None:
    if role == "user" and GOAL_WORDS.search(sentence):
        return "goals"
    if CONSTRAINT_WORDS.search(sentence):
        return "requirements"
    if DECISION_WORDS.search(sentence):
        return "decisions"
    if role == "user" and sentence.rstrip().endswith("?"):
        return "questions"
    return None


def _candidates(data: SummaryInput) -> list[_Line]:
    lines: dict[str, _Line] = {}
    later = set(terms(data.later_text))
    for u_i, unit in enumerate(data.units):
        if unit.kind in ("log", "json"):
            for l_i, raw in enumerate(unit.text.splitlines()):
                line = raw.strip()
                if not line or not LOG_SIGNAL.search(line):
                    continue
                key = "errors:" + normalize(line, fuzzy_numbers=True)
                if key in lines:
                    lines[key].count += 1
                    lines[key].order = (u_i, l_i)  # the latest occurrence decides position
                    continue
                lines[key] = _Line(
                    "errors",
                    line[:MAX_LINE_CHARS],
                    (u_i, l_i),
                    extract_facts(line),
                    _BASE["errors"],
                )
            continue
        if unit.kind == "code":
            for l_i, raw in enumerate(unit.text.splitlines()):
                line = raw.strip()
                facts = extract_facts(line)
                if facts and not line.startswith(("```", "~~~")):
                    key = "facts:" + normalize(line)
                    lines.setdefault(
                        key,
                        _Line(
                            "facts", f"`{line[:MAX_LINE_CHARS]}`", (u_i, l_i), facts, _BASE["facts"]
                        ),
                    )
            continue
        for s_i, sentence in enumerate(split_sentences(unit.text)):
            section = _classify(unit.role, sentence)
            facts = extract_facts(sentence)
            if section is None:
                if not facts:
                    continue
                section = "facts"
            if section == "questions":
                q_terms = set(terms(sentence))
                if q_terms and len(q_terms & later) / len(q_terms) >= 0.6:
                    continue  # answered later in the conversation
            key = section + ":" + normalize(sentence).lower()
            if key in lines:
                continue
            text = sentence if len(sentence) <= MAX_LINE_CHARS else sentence[:MAX_LINE_CHARS]
            prefix = "User: " if unit.role == "user" and section in ("facts",) else ""
            lines[key] = _Line(section, prefix + text, (u_i, s_i), facts, _BASE[section])
    out = list(lines.values())
    if len(out) > MAX_CANDIDATES:
        out.sort(key=lambda ln: (-(ln.base + 0.1 * len(ln.facts)), ln.order))
        out = out[:MAX_CANDIDATES]
    return out


class ExtractiveSummarizer:
    name = "extractive"

    def summarize(self, data: SummaryInput) -> SummaryOutput:
        head = header(data.messages_dropped, data.tokens_dropped)
        cands = _candidates(data)
        used = data.count(head)
        if not cands or used >= data.budget_tokens:
            return SummaryOutput("", {}, frozenset(), 0)
        relevance = BM25([c.text for c in cands]).normalized(data.query) if data.query else []
        n_units = max(1, len(data.units))
        static = [
            c.base
            + 0.3 * (relevance[i] if relevance else 0.0)
            + 0.15 * (c.order[0] / n_units)
            + (0.1 if c.count > 1 else 0.0)
            for i, c in enumerate(cands)
        ]
        covered: set[str] = set()
        chosen: list[int] = []
        remaining = set(range(len(cands)))
        section_header_cost = {s: data.count(f"{title}:") + 1 for s, title in SECTIONS}
        sections_open: set[str] = set()
        while remaining:
            best, best_score = -1, -1.0
            for i in remaining:
                gain = len(cands[i].facts - covered)
                score = static[i] + 0.15 * gain
                if score > best_score:
                    best, best_score = i, score
            remaining.discard(best)
            line = cands[best]
            text = self._render_line(line)
            cost = data.count(text) + 1
            if line.section not in sections_open:
                cost += section_header_cost[line.section]
            if used + cost > data.budget_tokens:
                continue
            used += cost
            sections_open.add(line.section)
            chosen.append(best)
            covered |= line.facts
        if not chosen:
            return SummaryOutput("", {}, frozenset(), 0)
        sections: dict[str, list[str]] = {}
        for i in sorted(chosen, key=lambda j: cands[j].order):
            sections.setdefault(cands[i].section, []).append(self._render_line(cands[i]))
        body = [head]
        for key, title in SECTIONS:
            if key in sections:
                body.append(f"{title}:")
                body.extend(sections[key])
        text = "\n".join(body)
        return SummaryOutput(text, sections, frozenset(covered), data.count(text))

    @staticmethod
    def _render_line(line: _Line) -> str:
        suffix = f" (seen {line.count} times)" if line.count > 1 else ""
        return f"- {line.text}{suffix}"
