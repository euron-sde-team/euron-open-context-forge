"""Text analysis: blocks, sentences, search terms and critical facts.

Everything here is deterministic and regex based, so it needs no model and gives the same
answer every time. Two rules matter most:

* code fences and JSON are **atomic** blocks: they are kept whole or dropped whole, never
  cut in the middle, so whatever survives is still syntactically valid;
* a "critical fact" is a token sequence a downstream step is likely to need verbatim (an
  id, a path, a version, a number with a unit, a config key, an error class). Facts drive
  importance scores, the summary, and the fact-retention metric reported on every run.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["prose", "code", "json", "log", "list"]

_FENCE = re.compile(r"^(```|~~~)")
_LOG_LINE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2}[ T]\d|\[?\d{2}:\d{2}:\d{2}"
    r"|(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|TRACE)\b"
    r"|\s*at [\w$.<>]+\(|\s*File \"|Traceback|\s*\^+\s*$|[\w.]+(Error|Exception):|npm (ERR|WARN)"
    r"|E\s{2,}|FAILED |PASSED |\$ )"
)
# Unfenced source code (file reads in agent tool output): definitions, imports, blocks.
_CODE_LINE = re.compile(
    r"^\s*(def |class |import |from \S+ import |async def |return\b|if .*:$|for .*:$|while .*:$"
    r"|try:$|except|elif |else:$|with .*:$|@\w+|function |const |let |var |export |public |private "
    r"|package |func |fn |#include|[}\])];?$|.*[{;]\s*$)"
)
_BULLET = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[`])")
_WORD = re.compile(r"[A-Za-z0-9_]+(?:[.\-/][A-Za-z0-9_]+)*")
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")

_STOPWORDS_TEXT = """
a an and are as at be been but by can could did do does for from had has have how i if in into
is it its me my no not of on or our so than that the their them then there these they this to
too was we were what when where which who why will with would you your please thanks thank ok
okay just also now let us get got like
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())

CONSTRAINT_WORDS = re.compile(
    r"\b(must|must not|never|do not|don't|cannot|can't|required|requirement|always|only|"
    r"should not|shouldn't|no more than|at most|at least|deadline|limit|forbidden|avoid)\b",
    re.IGNORECASE,
)
DECISION_WORDS = re.compile(
    r"\b(decided|decision|agreed|we will|we'll|let's|going with|chose|chosen|the fix|fixed by|"
    r"root cause|resolved|conclusion|concluded|turns out|confirmed|approved|settled on)\b",
    re.IGNORECASE,
)
GOAL_WORDS = re.compile(
    r"\b(goal|objective|i need|we need|need to|i want|want to|trying to|task is|help me|"
    r"please (build|fix|write|add|create|implement|debug|find)|the aim)\b",
    re.IGNORECASE,
)
ERROR_WORDS = re.compile(
    r"\b(error|exception|traceback|failed|failure|fatal|panic|denied|refused|timeout|"
    r"timed out|cannot|undefined|null pointer|segfault|assert)\b",
    re.IGNORECASE,
)

# Log lines that report a problem. Substring match on purpose: ``ExpiredSignatureError``,
# ``FAILED`` and ``AssertionError`` all count.
LOG_SIGNAL = re.compile(
    r"(error|exception|traceback|fail|fatal|panic|warn|assert|denied|refused|timeout|"
    r"timed out|exit code|not found)",
    re.IGNORECASE,
)

# Critical facts. Order matters only for readability; every pattern is applied.
_FACT_PATTERNS = [
    re.compile(r"https?://[^\s)\]>\"']+"),  # URLs
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),  # e-mail addresses
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),  # UUID
    re.compile(r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6}\b"),  # paths with extension
    re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,7}\b"),  # ticket and order ids: ORD-12345
    re.compile(r"\bv?\d+\.\d+\.\d+(?:[-+][\w.]+)?\b"),  # versions
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),  # ENV_VARS and CONSTANTS
    re.compile(r"\b\w+(?:Error|Exception)\b"),  # error classes
    re.compile(r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*\(\)"),  # function calls foo.bar()
    re.compile(r"\b[0-9a-f]{7,40}\b"),  # commit hashes (filtered below)
    re.compile(r"(?:[$€£₹]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|INR|GBP)\b)"),
    re.compile(
        r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds|minutes|min|hours|h|days|KB|MB|GB|TB|%|rps|qps|"
        r"tokens|req/s)\b"
    ),
    re.compile(r"\b(?:HTTP|status)\s?\d{3}\b", re.I),
    re.compile(r"\bport\s?\d{2,5}\b|:\d{4,5}\b", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates
]


_MEASUREMENT = re.compile(
    r"^(?:[$€£₹]\s?)?\d[\d,]*(?:\.\d+)?\s?(?:ms|s|sec|seconds|minutes|min|hours|h|days|KB|MB|GB|"
    r"TB|%|rps|qps|tokens|req/s|USD|EUR|INR|GBP)?$|^\d{4}-\d{2}-\d{2}$|^:\d{4,5}$",
    re.IGNORECASE,
)


def identity_facts(facts: frozenset[str]) -> frozenset[str]:
    """Facts that identify something (ids, paths, names, versions), not measurements.

    Durations, counts, sizes, percentages and dates change from one run of a tool to the
    next; ids and paths say *which* thing a block is about.
    """
    return frozenset(f for f in facts if not _MEASUREMENT.match(f))


@dataclass(slots=True)
class Block:
    text: str
    kind: BlockKind
    # Filled by the pipeline.
    tokens: int = 0
    facts: frozenset[str] = field(default_factory=frozenset)


def split_blocks(text: str) -> list[Block]:
    """Split text into paragraphs, keeping code fences and JSON documents whole."""
    if not text.strip():
        return []
    stripped = text.strip()
    if stripped[:1] in "[{" and looks_like_json(stripped):
        return [Block(stripped, "json")]
    blocks: list[Block] = []
    lines = text.splitlines()
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        if buf and any(line.strip() for line in buf):
            body = "\n".join(buf).strip("\n")
            blocks.append(Block(body, classify(body)))
        buf.clear()

    for line in lines:
        if _FENCE.match(line.strip()):
            if not in_fence:
                flush()
                in_fence = True
                buf.append(line)
            else:
                buf.append(line)
                body = "\n".join(buf)
                blocks.append(Block(body, "code"))
                buf.clear()
                in_fence = False
            continue
        if in_fence:
            buf.append(line)
            continue
        if not line.strip():
            flush()
            continue
        buf.append(line)
    if in_fence:
        # An unterminated fence: keep it atomic anyway.
        blocks.append(Block("\n".join(buf), "code"))
        buf.clear()
    flush()
    return blocks


def classify(body: str) -> BlockKind:
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return "prose"
    if body.lstrip()[:1] in "[{" and looks_like_json(body.strip()):
        return "json"
    log_lines = sum(1 for ln in lines if _LOG_LINE.match(ln))
    if len(lines) >= 2 and log_lines / len(lines) >= 0.5:
        return "log"
    if looks_like_code(lines):
        return "code"
    bullets = sum(1 for ln in lines if _BULLET.match(ln))
    if len(lines) >= 2 and bullets / len(lines) >= 0.6:
        return "list"
    return "prose"


def looks_like_code(lines: list[str]) -> bool:
    """Unfenced source: most lines are definitions, statements or indented bodies."""
    if len(lines) < 3:
        return False
    code = sum(1 for ln in lines if _CODE_LINE.match(ln) or ln.startswith(("    ", "\t")))
    return code / len(lines) >= 0.6 and any(_CODE_LINE.match(ln) for ln in lines)


def looks_like_json(text: str) -> bool:
    import json

    try:
        value = json.loads(text)
    except ValueError:
        return False
    return isinstance(value, (dict, list))


def split_sentences(text: str) -> list[str]:
    """Sentence split for prose; lists split per item; other kinds stay whole."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _BULLET.match(line):
            out.append(line)
            continue
        out.extend(s.strip() for s in _SENTENCE_END.split(line) if s.strip())
    return out


def terms(text: str) -> list[str]:
    """Search terms: lower-cased words without stopwords, plus identifier parts.

    ``getUserById`` and ``user_id`` both contribute ``user`` and ``id`` so a query about
    "user id" finds the code that handles it.
    """
    out: list[str] = []
    for word in _WORD.findall(text):
        low = word.lower()
        if low in STOPWORDS or len(low) < 2:
            continue
        out.append(low)
        if any(c in word for c in "_./-") or (word != low and word != word.upper()):
            for part in re.split(r"[_./-]", word):
                for sub in _CAMEL.findall(part):
                    s = sub.lower()
                    if len(s) > 1 and s not in STOPWORDS and s != low:
                        out.append(s)
    return out


def extract_facts(text: str) -> frozenset[str]:
    found: set[str] = set()
    for pattern in _FACT_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0).strip().rstrip(".,;:")
            if len(value) < 3:
                continue
            if re.fullmatch(r"[0-9a-f]{7,40}", value) and not (
                re.search(r"\d", value) and re.search(r"[a-f]", value)
            ):
                continue  # plain words or numbers, not a hash
            found.add(value)
    return frozenset(found)


def normalize(text: str, *, fuzzy_numbers: bool = False) -> str:
    """Whitespace-insensitive form for duplicate detection.

    ``fuzzy_numbers`` replaces digits so repeated log lines that differ only in timestamps,
    durations or counters collapse together.
    """
    value = " ".join(text.split())
    if fuzzy_numbers:
        value = re.sub(r"\d+", "#", value)
    return value


def digest(text: str) -> str:
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()


def shingles(text: str, size: int = 5) -> set[int]:
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < size:
        return {hash(" ".join(words))} if words else set()
    return {hash(" ".join(words[i : i + size])) for i in range(len(words) - size + 1)}


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[int], b: set[int]) -> float:
    """Share of ``a`` that also occurs in ``b``: high when b repeats a (and maybe more)."""
    if not a:
        return 0.0
    return len(a & b) / len(a)


def importance(text: str, kind: BlockKind, facts: frozenset[str]) -> float:
    """0..1: how likely this block carries something a later step needs."""
    score = min(0.45, 0.15 * len(facts))
    if CONSTRAINT_WORDS.search(text):
        score += 0.3
    if DECISION_WORDS.search(text):
        score += 0.3
    if GOAL_WORDS.search(text):
        score += 0.2
    if kind == "code":
        score += 0.2
    if ERROR_WORDS.search(text):
        score += 0.2
    return min(1.0, score)


def salient_facts(
    text: str, *, tool: bool = False, referenced: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Facts that matter for the task: what the fact-retention metric counts.

    Conversation text contributes every fact. Tool output is mostly bulk, so for logs and
    JSON only facts on lines that signal a problem count, plus facts the conversation
    itself refers to (``referenced``): the SKU the user asked about, not the 400 others in
    the search results. Measurements on those lines (durations, counts) count only when
    referenced. Prose and source code from tools count in full.
    """
    if not tool:
        return extract_facts(text)
    found: set[str] = set()
    for block in split_blocks(text):
        if block.kind in ("log", "json"):
            for line in block.text.splitlines():
                facts = extract_facts(line)
                if LOG_SIGNAL.search(line):
                    found |= identity_facts(facts) | (facts & referenced)
                else:
                    found |= facts & referenced
        else:
            found |= extract_facts(block.text)
    return frozenset(found)
