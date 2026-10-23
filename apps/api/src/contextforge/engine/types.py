"""Public data contract of the engine: what goes in, what comes out.

These models are shared by the Python library and the HTTP API, so a request that works
in-process works over the wire unchanged. Messages follow the OpenAI chat format (the
lingua franca of LLM clients); unknown message fields are carried through untouched so
provider-specific extras are never lost.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["system", "developer", "user", "assistant", "tool"]
Strategy = Literal["conservative", "balanced", "aggressive"]
Workload = Literal["auto", "coding", "research", "support", "agent", "rag", "chat"]
ResolvedWorkload = Literal["coding", "research", "support", "agent", "rag", "chat"]
Category = Literal["history", "tool", "documents", "summary"]
CitationStatus = Literal["kept", "compressed", "merged", "dropped"]


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ToolCallFunction(_Model):
    name: str
    arguments: str = ""


class ToolCall(_Model):
    model_config = ConfigDict(extra="allow")
    id: str
    type: str = "function"
    function: ToolCallFunction


class ContentPart(_Model):
    """One part of a multi-part message. Text parts may be optimized; others never are."""

    model_config = ConfigDict(extra="allow")
    type: str
    text: str | None = None


class Message(_Model):
    model_config = ConfigDict(extra="allow")
    role: Role
    content: str | list[ContentPart] | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def text(self) -> str:
        """The message's text, or an empty string for non-text content."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(p.text for p in self.content if p.type == "text" and p.text)
        return ""

    def has_non_text_parts(self) -> bool:
        return isinstance(self.content, list) and any(p.type != "text" for p in self.content)


class Document(_Model):
    """A retrieved passage. ``id`` is the citation handle and is never rewritten."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    text: str
    source: str | None = Field(None, max_length=2000)
    title: str | None = Field(None, max_length=500)
    score: float | None = Field(None, description="Optional retriever score, blended into ranking")
    metadata: dict[str, Any] = Field(default_factory=dict)


class OptimizeOptions(_Model):
    model_config = ConfigDict(extra="forbid")

    max_input_tokens: int | None = Field(
        None,
        ge=1,
        le=10_000_000,
        description="Budget for messages plus documents. Omit to clean only (dedup, tool output)",
    )
    reserve_output_tokens: int = Field(
        0, ge=0, le=1_000_000, description="Room kept free for the model's answer"
    )
    strategy: Strategy = "balanced"
    workload: Workload = Field(
        "auto", description="Adaptive budget profile; auto detects it from the input"
    )
    profile: str | None = Field(
        None,
        max_length=64,
        description="Name of a stored profile (service only); overrides workload weights",
    )
    preserve_recent_messages: int = Field(4, ge=0, le=1000)
    preserve_system_instructions: bool = Field(
        True,
        description="System and developer messages are always returned verbatim; with false, "
        "exact duplicates among them may be removed",
    )
    pin_messages: list[int] = Field(
        default_factory=list, max_length=1000, description="Message indexes never rewritten"
    )
    must_keep: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Strings that must survive verbatim (ids, values, phrases)",
    )
    deduplicate: bool = True
    summarize_history: bool = True
    reduce_tool_output: bool = True
    rank_documents: bool = True
    drop_irrelevant_documents: bool = True
    max_documents: int | None = Field(None, ge=0, le=10_000)
    query: str | None = Field(
        None, max_length=20_000, description="Ranking query; defaults to the latest user turn"
    )
    summary_role: Literal["user", "assistant", "system"] = Field(
        "user",
        description="Role of the generated summary message. user keeps quoted tool and "
        "document text out of system authority",
    )
    summarizer: Literal["extractive", "llm"] = "extractive"
    on_budget_failure: Literal["warn", "error"] = Field(
        "warn",
        description="warn returns the best safe result with budget_met=false; error returns 422",
    )
    allow_estimate: bool = Field(
        True,
        description="Allow an explicitly marked token estimate when the model's tokenizer is "
        "unknown; false returns unsupported_tokenizer instead",
    )
    include_trace: bool = True

    @field_validator("must_keep")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        cleaned = [s for s in v if s.strip()]
        if any(len(s) > 2000 for s in cleaned):
            raise ValueError("must_keep entries are limited to 2000 characters")
        return cleaned


class OptimizeRequest(_Model):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(default_factory=list, max_length=20_000)
    documents: list[Document] = Field(default_factory=list, max_length=20_000)
    options: OptimizeOptions = Field(default_factory=OptimizeOptions)

    @model_validator(mode="after")
    def _check(self) -> OptimizeRequest:
        if not self.messages and not self.documents:
            raise ValueError("send at least one message or document")
        ids = [d.id for d in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document ids must be unique")
        n = len(self.messages)
        if any(i < 0 or i >= n for i in self.options.pin_messages):
            raise ValueError("pin_messages contains an index outside the message list")
        return self


class TokenizerInfo(_Model):
    id: str = Field(description="Tokenizer used, e.g. o200k_base or estimate:o200k_base*1.15")
    exact: bool = Field(description="True when counts come from the model's own tokenizer")
    model: str


class Stats(_Model):
    original_tokens: int
    optimized_tokens: int
    tokens_removed: int
    reduction_percent: float
    budget: int | None
    budget_met: bool
    messages_in: int
    messages_out: int
    documents_in: int
    documents_out: int
    facts_total: int = Field(description="Critical facts detected in the input messages")
    facts_retained: int
    fact_retention: float = Field(description="facts_retained / facts_total (1.0 when none)")
    latency_ms: float


class CitationEntry(_Model):
    status: CitationStatus
    into: str | None = Field(None, description="For merged duplicates: the id that was kept")
    reason: str | None = None


class Allocation(_Model):
    category: Category
    weight: float
    budget: int
    used: int


class OptimizeWarning(_Model):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TraceStep(_Model):
    stage: str
    tokens_before: int
    tokens_after: int
    items_removed: int = 0
    ms: float = 0.0
    notes: list[str] = Field(default_factory=list)


class OptimizeResult(_Model):
    messages: list[Message]
    documents: list[Document]
    citation_map: dict[str, CitationEntry]
    citations_preserved: bool
    stats: Stats
    tokenizer: TokenizerInfo
    strategy: Strategy
    workload: ResolvedWorkload
    allocation: list[Allocation]
    summary: str | None = None
    warnings: list[OptimizeWarning] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
