"""Okapi BM25 over in-memory passages: fast, deterministic and dependency free.

Relevance is the strongest signal for retrieved documents and a useful one for history.
BM25 needs no model and no index service; for the passage counts a context window holds
(tens to a few thousand) it scores everything in a few milliseconds.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from contextforge.engine.text import terms


class BM25:
    def __init__(self, passages: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._tf: list[Counter[str]] = [Counter(terms(p)) for p in passages]
        self._len = [sum(tf.values()) for tf in self._tf]
        n = len(passages)
        self._avg = (sum(self._len) / n) if n else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        # BM25+ style floor keeps idf positive for terms present in most passages.
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def scores(self, query: str) -> list[float]:
        q = set(terms(query))
        if not q or not self._tf:
            return [0.0] * len(self._tf)
        out: list[float] = []
        for tf, length in zip(self._tf, self._len, strict=True):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * (length / self._avg if self._avg else 0))
            for t in q:
                f = tf.get(t)
                if f:
                    s += self._idf[t] * (f * (self.k1 + 1)) / (f + norm)
            out.append(s)
        return out

    def normalized(self, query: str) -> list[float]:
        """Scores scaled to 0..1 by the best passage (all zeros when nothing matches)."""
        raw = self.scores(query)
        top = max(raw, default=0.0)
        return [s / top for s in raw] if top > 0 else [0.0] * len(raw)


def rank(query: str, passages: Sequence[str]) -> list[tuple[int, float]]:
    """(index, normalized score) sorted best first; ties keep input order."""
    scores = BM25(passages).normalized(query)
    return sorted(enumerate(scores), key=lambda p: (-p[1], p[0]))
