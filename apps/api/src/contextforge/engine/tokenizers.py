"""Tokenizer registry: the right tokenizer per model, and honesty when there is none.

OpenAI model families map to their real tiktoken encodings, so counts are exact. For any
other model (Claude, Gemini, Llama, a SmartRouter ``auto`` route) the registry returns an
estimate built on ``o200k_base`` scaled up by a safety factor, and says so: the result's
``exact`` flag is false and its id reads ``estimate:o200k_base*1.15``. A caller that cannot
accept an estimate gets :class:`UnsupportedTokenizerError` instead of a number that looks
exact but is not.

Adapters are pluggable: register any object with ``id``, ``exact`` and ``count(text)``,
for example a Hugging Face tokenizer, under a model name pattern.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import orjson
import tiktoken

from contextforge.engine.types import Document, Message

# Per-message framing (role markers, separators) and reply priming, following OpenAI's
# published counting recipe for chat models.
TOKENS_PER_MESSAGE = 3
TOKENS_PER_NAME = 1
REPLY_PRIMING = 3
# Framing charged per document when a caller renders it ("[id] title\ntext").
TOKENS_PER_DOCUMENT = 4
# A conservative flat charge per image part; real cost depends on resolution and provider.
IMAGE_TOKENS = 1105
# Other vendors' tokenizers usually produce more tokens than o200k_base for the same text;
# scaling up keeps a budget computed from the estimate on the safe side.
ESTIMATE_FACTOR = 1.15
ENCODINGS = ("o200k_base", "cl100k_base")


class UnsupportedTokenizerError(ValueError):
    """The model has no known tokenizer and the caller refused an estimate."""

    def __init__(self, model: str) -> None:
        super().__init__(f"No tokenizer is configured for model {model!r}")
        self.model = model


class Tokenizer(Protocol):
    id: str
    exact: bool

    def count(self, text: str) -> int: ...


@lru_cache(maxsize=4)
def _encoding(name: str) -> tiktoken.Encoding:
    return tiktoken.get_encoding(name)


class TiktokenTokenizer:
    def __init__(self, encoding: str, *, exact: bool = True, factor: float = 1.0) -> None:
        self._enc = _encoding(encoding)
        self._factor = factor
        self.exact = exact
        self.id = encoding if factor == 1.0 else f"estimate:{encoding}*{factor:g}"
        self._cache: dict[str, int] = {}

    def count(self, text: str) -> int:
        if not text:
            return 0
        hit = self._cache.get(text)
        if hit is not None:
            return hit
        n = len(self._enc.encode(text, disallowed_special=()))
        if self._factor != 1.0:
            n = math.ceil(n * self._factor)
        if len(self._cache) < 50_000:
            self._cache[text] = n
        return n


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: re.Pattern[str]
    encoding: str


# Ordered: first match wins. Patterns match the bare model name (provider prefixes such as
# "openai/" are stripped first).
_OPENAI_RULES = [
    _Rule(re.compile(r"^(gpt-4o|chatgpt-4o|gpt-4\.1|gpt-4\.5|gpt-5|o1|o3|o4)"), "o200k_base"),
    _Rule(re.compile(r"^(gpt-4|gpt-3\.5|text-embedding-3|text-embedding-ada)"), "cl100k_base"),
]


class TokenizerRegistry:
    """Resolves a model name to a tokenizer. Thread-safe for reads after construction."""

    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        # alias -> encoding name or another model name (e.g. TokenShield's "chat-small")
        self._aliases = {k.lower(): v for k, v in (aliases or {}).items()}
        self._custom: list[tuple[re.Pattern[str], Tokenizer]] = []
        self._instances: dict[str, Tokenizer] = {}

    def register(self, pattern: str, tokenizer: Tokenizer) -> None:
        """Register a custom adapter for model names matching ``pattern`` (a regex)."""
        self._custom.append((re.compile(pattern), tokenizer))

    def _tiktoken(self, encoding: str, *, estimate: bool) -> Tokenizer:
        key = f"{encoding}:{estimate}"
        if key not in self._instances:
            self._instances[key] = (
                TiktokenTokenizer(encoding, exact=False, factor=ESTIMATE_FACTOR)
                if estimate
                else TiktokenTokenizer(encoding)
            )
        return self._instances[key]

    def resolve(self, model: str, *, allow_estimate: bool = True) -> Tokenizer:
        name = model.strip().lower()
        seen: set[str] = set()
        while name in self._aliases and name not in seen:
            seen.add(name)
            target = self._aliases[name]
            if target in ENCODINGS:
                return self._tiktoken(target, estimate=False)
            name = target.lower()
        for pattern, tok in self._custom:
            if pattern.search(name):
                return tok
        bare = name.split("/", 1)[1] if "/" in name else name
        for rule in _OPENAI_RULES:
            if rule.pattern.search(bare):
                return self._tiktoken(rule.encoding, estimate=False)
        if not allow_estimate:
            raise UnsupportedTokenizerError(model)
        return self._tiktoken("o200k_base", estimate=True)


def warm_up() -> None:
    """Load the BPE tables before serving traffic (the first load reads them from disk)."""
    for name in ENCODINGS:
        _encoding(name)


def content_tokens(message: Message, tok: Tokenizer) -> int:
    content = message.content
    if isinstance(content, str):
        return tok.count(content)
    total = 0
    if isinstance(content, list):
        for part in content:
            if part.type == "text":
                total += tok.count(part.text or "")
            elif part.type in ("image_url", "input_image", "image"):
                total += IMAGE_TOKENS
            else:
                total += tok.count(orjson.dumps(part.model_dump(exclude_none=True)).decode())
    return total


def message_tokens(message: Message, tok: Tokenizer) -> int:
    total = TOKENS_PER_MESSAGE + content_tokens(message, tok)
    if message.name:
        total += tok.count(message.name) + TOKENS_PER_NAME
    if message.tool_calls:
        calls = [c.model_dump(exclude_none=True) for c in message.tool_calls]
        total += tok.count(orjson.dumps(calls).decode())
    if message.tool_call_id:
        total += tok.count(message.tool_call_id)
    return total


def messages_tokens(messages: Iterable[Message], tok: Tokenizer) -> int:
    items = list(messages)
    if not items:
        return 0
    return REPLY_PRIMING + sum(message_tokens(m, tok) for m in items)


def document_tokens(doc: Document, tok: Tokenizer) -> int:
    head = f"[{doc.id}] {doc.title or ''}".strip()
    return TOKENS_PER_DOCUMENT + tok.count(head) + tok.count(doc.text)


def documents_tokens(docs: Iterable[Document], tok: Tokenizer) -> int:
    return sum(document_tokens(d, tok) for d in docs)
