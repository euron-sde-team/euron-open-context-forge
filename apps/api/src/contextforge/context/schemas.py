"""The public /v1/context contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contextforge.engine.types import (
    Allocation,
    CitationEntry,
    Document,
    Message,
    OptimizeWarning,
    ResolvedWorkload,
    Stats,
    Strategy,
    TokenizerInfo,
    TraceStep,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptimizeResponse(BaseModel):
    optimized_messages: list[Message]
    optimized_documents: list[Document]
    citation_map: dict[str, CitationEntry]
    citations_preserved: bool
    stats: Stats
    tokenizer: TokenizerInfo
    strategy: Strategy
    workload: ResolvedWorkload
    profile: str
    allocation: list[Allocation]
    summary: str | None
    warnings: list[OptimizeWarning]
    trace: list[TraceStep]
    run_id: int | None = Field(None, description="Id of the recorded run (dashboard: Runs)")
    cached: bool = Field(False, description="Served from the result cache")
    cost_avoided_usd: float | None = Field(
        None, description="Estimate: tokens removed x the model's list input price"
    )


class CountTokensRequest(_Strict):
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(default_factory=list, max_length=20_000)
    documents: list[Document] = Field(default_factory=list, max_length=20_000)
    text: str | None = Field(None, max_length=20_000_000)
    allow_estimate: bool = True

    @model_validator(mode="after")
    def _some(self) -> CountTokensRequest:
        if not self.messages and not self.documents and self.text is None:
            raise ValueError("send messages, documents or text")
        return self


class CountTokensResponse(BaseModel):
    model: str
    tokenizer: TokenizerInfo
    total: int
    messages_tokens: int
    documents_tokens: int
    text_tokens: int
    per_message: list[int]
    per_document: list[int]


class SummarizeRequest(_Strict):
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=20_000)
    max_summary_tokens: int = Field(500, ge=32, le=20_000)
    summarizer: Literal["extractive", "llm"] = "extractive"
    query: str | None = Field(None, max_length=20_000)
    include_system: bool = Field(
        False, description="Summarise system messages too (they are excluded by default)"
    )
    allow_estimate: bool = True


class SummarizeResponse(BaseModel):
    summary: str
    sections: dict[str, list[str]]
    summarizer: str
    tokens: int
    source_tokens: int
    facts_total: int
    facts_covered: int
    tokenizer: TokenizerInfo
    warnings: list[OptimizeWarning]


class RankRequest(_Strict):
    query: str = Field(min_length=1, max_length=20_000)
    passages: list[Document] = Field(min_length=1, max_length=20_000)
    model: str = Field("gpt-4o", max_length=200)
    top_k: int | None = Field(None, ge=1, le=20_000)
    max_tokens: int | None = Field(None, ge=1, le=10_000_000)
    deduplicate: bool = True
    allow_estimate: bool = True


class RankedPassage(BaseModel):
    id: str
    rank: int
    score: float = Field(description="BM25 relevance blended with the retriever score, 0..1")
    relevance: float = Field(description="BM25 relevance to the query, 0..1")
    tokens: int
    duplicate_of: str | None = None
    source: str | None = None


class RankResponse(BaseModel):
    query: str
    tokenizer: TokenizerInfo
    ranked: list[RankedPassage]
    dropped: list[RankedPassage] = Field(
        description="Duplicates, zero-relevance passages and those beyond top_k or max_tokens"
    )
    tokens_selected: int
