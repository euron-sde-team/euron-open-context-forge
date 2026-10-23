"""Mutable working state shared by the pipeline stages for one optimization."""

from __future__ import annotations

from dataclasses import dataclass, field

from contextforge.engine.text import Block, BlockKind
from contextforge.engine.tokenizers import Tokenizer
from contextforge.engine.types import (
    Category,
    CitationEntry,
    Document,
    Message,
    OptimizeOptions,
    OptimizeWarning,
    TraceStep,
)

DUPLICATE_TOOL_NOTE = "[duplicate of a later tool result, removed by ContextForge]"


@dataclass(slots=True)
class Unit:
    """The smallest piece the selector keeps or drops: a block of a message, or a document."""

    uid: int
    category: Category
    text: str
    kind: BlockKind
    tokens: int
    facts: frozenset[str]
    msg_index: int | None = None
    doc_index: int | None = None
    score: float = 0.0
    relevance: float = 0.0
    required: bool = False
    keep: bool = False
    # A shortened (extractive) version used when the whole unit does not fit.
    partial_text: str | None = None
    partial_tokens: int = 0

    def cost(self) -> int:
        return self.partial_tokens if self.partial_text is not None else self.tokens

    def output_text(self) -> str:
        return self.partial_text if self.partial_text is not None else self.text


@dataclass(slots=True)
class MsgState:
    index: int
    message: Message
    protected: bool = False
    reason: str | None = None
    dropped: bool = False
    # Whole-content replacement (tool output reduction, duplicate note).
    override: str | None = None
    clear_content: bool = False
    blocks: list[Block] | None = None
    units: list[Unit] = field(default_factory=list)
    group: int | None = None  # index of the assistant message whose tool calls it belongs to

    def current_text(self) -> str:
        if self.override is not None:
            return self.override
        if self.clear_content:
            return ""
        return self.message.text()

    def atomic(self) -> bool:
        """Messages that are kept or dropped whole (images and other non-text parts)."""
        return self.message.has_non_text_parts()


@dataclass(slots=True)
class DocState:
    index: int
    doc: Document
    protected: bool = False
    required: bool = False
    status: str = "kept"
    into: str | None = None
    reason: str | None = None
    unit: Unit | None = None


@dataclass(slots=True)
class Work:
    model: str
    options: OptimizeOptions
    tok: Tokenizer
    msgs: list[MsgState]
    docs: list[DocState]
    query: str = ""
    warnings: list[OptimizeWarning] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    citation_map: dict[str, CitationEntry] = field(default_factory=dict)
    must_keep_missing_in_input: list[str] = field(default_factory=list)

    def warn(self, code: str, message: str, **details: object) -> None:
        if not any(w.code == code for w in self.warnings):
            self.warnings.append(OptimizeWarning(code=code, message=message, details=details))
