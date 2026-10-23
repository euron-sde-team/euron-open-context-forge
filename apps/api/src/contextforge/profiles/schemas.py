from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from contextforge.core.schemas import ApiModel

NAME = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class Weights(ApiModel):
    history: float = Field(ge=0, le=1)
    tool: float = Field(ge=0, le=1)
    documents: float = Field(ge=0, le=1)
    summary: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _positive(self) -> Weights:
        if self.history + self.tool + self.documents + self.summary <= 0:
            raise ValueError("at least one category weight must be above zero")
        return self


class ProfileIn(ApiModel):
    name: str = Field(pattern=NAME)
    description: str = Field("", max_length=300)
    weights: Weights
    relevance: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ranking(self) -> ProfileIn:
        if self.relevance + self.recency + self.importance <= 0:
            raise ValueError("at least one ranking weight must be above zero")
        return self


class ProfileOut(ApiModel):
    name: str
    description: str
    weights: Weights
    relevance: float
    recency: float
    importance: float
    builtin: bool = Field(description="Ships with ContextForge")
    customized: bool = Field(description="A built-in profile whose weights were edited")
    tags: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
