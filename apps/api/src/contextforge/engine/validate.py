"""Checks run on every optimized context before it is returned."""

from __future__ import annotations

import re
from collections.abc import Iterable

from contextforge.engine.types import CitationEntry, Document, Message

_CITE = re.compile(r"\[([A-Za-z0-9_.:#/-]{1,200})\]")


def tool_pairs(messages: list[Message]) -> dict[str, int]:
    """tool_call_id -> index of the assistant message that issued it."""
    pairs: dict[str, int] = {}
    for i, m in enumerate(messages):
        for call in m.tool_calls or []:
            pairs[call.id] = i
    return pairs


def structure_problems(
    messages: list[Message], reference: list[Message] | None = None
) -> list[str]:
    """Problems that would make a provider reject the message list.

    With ``reference`` (the input), only problems the optimizer introduced are reported:
    a malformed input is the caller's, and it is passed through rather than "fixed".
    """
    problems: list[str] = []
    issued: dict[str, int] = {}
    answered: set[str] = set()
    for i, m in enumerate(messages):
        if m.role == "tool":
            if not m.tool_call_id:
                problems.append(f"message {i}: tool message without tool_call_id")
            elif m.tool_call_id not in issued:
                problems.append(f"message {i}: tool result {m.tool_call_id} has no preceding call")
            else:
                answered.add(m.tool_call_id)
        for call in m.tool_calls or []:
            issued[call.id] = i
    for call_id, idx in issued.items():
        if call_id not in answered:
            problems.append(f"message {idx}: tool call {call_id} has no result")
    if reference is not None:
        before = set(structure_problems(reference))
        # Indexes shift when messages are removed, so compare by the stable part (ids).
        before_ids = {p.split(": ", 1)[1] for p in before}
        problems = [p for p in problems if p.split(": ", 1)[1] not in before_ids]
    return problems


def cited_ids(texts: Iterable[str], known: set[str]) -> set[str]:
    """Document ids referenced as ``[id]`` in the given texts."""
    found: set[str] = set()
    for text in texts:
        for match in _CITE.finditer(text):
            if match.group(1) in known:
                found.add(match.group(1))
    return found


def citation_problems(
    inputs: list[Document],
    outputs: list[Document],
    citation_map: dict[str, CitationEntry],
    output_texts: list[str],
) -> list[str]:
    problems: list[str] = []
    by_id = {d.id: d for d in inputs}
    kept = {d.id: d for d in outputs}
    for doc_id in by_id:
        entry = citation_map.get(doc_id)
        if entry is None:
            problems.append(f"document {doc_id} missing from the citation map")
            continue
        if entry.status in ("kept", "compressed") and doc_id not in kept:
            problems.append(f"document {doc_id} marked {entry.status} but not returned")
        if entry.status == "merged" and (entry.into is None or entry.into not in kept):
            problems.append(f"document {doc_id} merged into a document that was not returned")
    for doc_id, doc in kept.items():
        original = by_id.get(doc_id)
        if original is None:
            problems.append(f"document {doc_id} was not in the input")
            continue
        if doc.source != original.source or doc.metadata != original.metadata:
            problems.append(f"document {doc_id} lost its source or metadata")
    for doc_id in cited_ids(output_texts, set(by_id)):
        entry = citation_map.get(doc_id)
        resolved = entry.into if entry and entry.status == "merged" else doc_id
        if resolved not in kept:
            problems.append(f"document {doc_id} is cited in the context but was not returned")
    return problems
