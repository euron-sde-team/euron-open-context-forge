"""Tool output reduction: keep the fields and lines that matter, drop the bulk.

Agents read far less of a tool result than they are sent. Three shapes cover most of it:

* **JSON**: reduced structurally. Every key survives; long arrays keep their first items
  plus any item that mentions an error or a query term, followed by a note string; long
  strings are shortened. The result is always valid JSON (re-parsed before it is used).
* **Logs and test output**: errors, warnings, failures, assertions and the last frames of
  a stack trace are kept, plus the head and tail; repeated lines collapse with a count.
* **Source code** (a file read): never cut. Earlier re-reads of the same file are removed
  by duplicate detection, so the latest read survives whole.
* **Anything else**: head and tail with an omission marker.

Reduction never invents content: every kept line is copied verbatim from the input.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from contextforge.engine.text import ERROR_WORDS, looks_like_code, normalize

_SIGNAL = re.compile(
    r"(error|exception|traceback|fail|fatal|panic|warn|assert|expected|actual|denied|refused|"
    r"timeout|timed out|exit code|exit status|not found|undefined|\bE\s{2,}|^\s*>\s)",
    re.IGNORECASE,
)
_FRAME = re.compile(r'^\s*(File "|at [\w$.<>]+\()')
MAX_JSON_DEPTH = 64
_ALWAYS_KEEP_KEYS = {"error", "errors", "message", "status", "code", "id", "name", "type", "detail"}


@dataclass(frozen=True, slots=True)
class ReductionLevel:
    """How hard to squeeze. Chosen from the strategy."""

    min_chars: int  # outputs shorter than this are left alone
    head: int
    tail: int
    array_items: int
    string_chars: int
    max_signal_lines: int


LIGHT = ReductionLevel(
    min_chars=6000, head=20, tail=20, array_items=10, string_chars=2000, max_signal_lines=80
)
NORMAL = ReductionLevel(
    min_chars=1600, head=8, tail=12, array_items=5, string_chars=600, max_signal_lines=40
)
HARD = ReductionLevel(
    min_chars=600, head=4, tail=6, array_items=3, string_chars=240, max_signal_lines=20
)


def reduce_output(text: str, level: ReductionLevel, query_terms: set[str]) -> str | None:
    """A shorter verbatim-derived version of ``text``, or None when it is not worth it."""
    if len(text) < level.min_chars:
        return None
    stripped = text.strip()
    if stripped[:1] in "[{":
        try:
            value = json.loads(stripped)
        except (ValueError, RecursionError):
            value = None
        if isinstance(value, (dict, list)):
            try:
                reduced = json.dumps(
                    _reduce_json(value, level, query_terms, depth=0),
                    ensure_ascii=False,
                    indent=1,
                )
                json.loads(reduced)  # invariant: the output is valid JSON
            except RecursionError:
                reduced = ""  # pathologically deep: fall through to text reduction
            if reduced:
                return reduced if len(reduced) < len(text) * 0.9 else None
    lines = text.splitlines()
    if looks_like_code([ln for ln in lines if ln.strip()]):
        # A file read: cutting its middle breaks the code a later edit needs. Repeated
        # reads are removed by duplicate detection instead, keeping the latest whole.
        return None
    if len(lines) >= level.head + level.tail + 4:
        reduced = _reduce_lines(lines, level, query_terms)
        return reduced if len(reduced) < len(text) * 0.9 else None
    return _head_tail_chars(text, level)


def _mentions(value: Any, query_terms: set[str]) -> bool:
    blob = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value
    blob = blob.lower()
    if ERROR_WORDS.search(blob):
        return True
    return any(t in blob for t in query_terms if len(t) > 3)


def _reduce_json(value: Any, level: ReductionLevel, query_terms: set[str], depth: int) -> Any:
    if depth >= MAX_JSON_DEPTH and isinstance(value, (dict, list)):
        return f"[ContextForge: nesting deeper than {MAX_JSON_DEPTH} levels omitted]"
    if isinstance(value, dict):
        return {
            k: (
                v
                if k.lower() in _ALWAYS_KEEP_KEYS and not isinstance(v, (dict, list))
                else _reduce_json(v, level, query_terms, depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        if len(value) <= level.array_items:
            return [_reduce_json(v, level, query_terms, depth + 1) for v in value]
        keep_idx = list(range(level.array_items))
        extra = [
            i for i in range(level.array_items, len(value)) if _mentions(value[i], query_terms)
        ][: level.array_items]
        keep_idx.extend(extra)
        kept = [_reduce_json(value[i], level, query_terms, depth + 1) for i in keep_idx]
        omitted = len(value) - len(keep_idx)
        if omitted:
            kept.append(f"[ContextForge: {omitted} more items omitted]")
        return kept
    if isinstance(value, str) and len(value) > level.string_chars:
        cut = len(value) - level.string_chars
        return value[: level.string_chars] + f"...[{cut} chars truncated]"
    return value


def _reduce_lines(lines: list[str], level: ReductionLevel, query_terms: set[str]) -> str:
    n = len(lines)
    keep: set[int] = set(range(min(level.head, n))) | set(range(max(0, n - level.tail), n))
    signal = [
        i
        for i, line in enumerate(lines)
        if _SIGNAL.search(line) or any(t in line.lower() for t in query_terms if len(t) > 3)
    ]
    # Prefer the latest signals: the end of a run is what decides the next step.
    for i in signal[-level.max_signal_lines :]:
        keep.add(i)
    # Keep the last three frames of each stack trace block that ends in a kept error line.
    frames = [i for i, line in enumerate(lines) if _FRAME.match(line)]
    for i in frames[-3:]:
        keep.add(i)
        if i + 1 < n:
            keep.add(i + 1)
    out: list[str] = []
    counts: dict[str, int] = {}
    last_norm: str | None = None
    skipped = 0
    for i, line in enumerate(lines):
        if i not in keep:
            skipped += 1
            continue
        norm = normalize(line, fuzzy_numbers=True)
        if norm and norm == last_norm:
            counts[norm] = counts.get(norm, 1) + 1
            continue
        if last_norm is not None and counts.get(last_norm, 1) > 1:
            out.append(f"[previous line repeated {counts[last_norm]} times]")
            counts[last_norm] = 1
        if skipped:
            out.append(f"[... {skipped} lines omitted ...]")
            skipped = 0
        out.append(line)
        last_norm = norm
    if last_norm is not None and counts.get(last_norm, 1) > 1:
        out.append(f"[previous line repeated {counts[last_norm]} times]")
    if skipped:
        out.append(f"[... {skipped} lines omitted ...]")
    return "\n".join(out)


def _head_tail_chars(text: str, level: ReductionLevel) -> str | None:
    budget = level.string_chars * 2
    if len(text) <= budget * 1.2:
        return None
    head = text[: budget // 2]
    tail = text[-budget // 2 :]
    return f"{head}\n[... {len(text) - budget} chars omitted ...]\n{tail}"
