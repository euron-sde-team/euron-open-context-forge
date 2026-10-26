"""Optimize a noisy retrieval and show where every citation went.

    cd apps/api && uv run python ../../examples/rag_citations.py
"""

from __future__ import annotations

from contextforge import OptimizeRequest, optimize

documents = [
    {"id": "kb-1", "source": "handbook/api.md", "text": "The API rate limit is 1200 requests per minute per key."},
    {"id": "kb-2", "source": "handbook/api-copy.md", "text": "The API rate limit is 1200 requests per minute per key!"},
    {"id": "kb-3", "source": "wiki/kitchen.md", "text": "The office kitchen is restocked every Monday morning."},
    {"id": "kb-4", "source": "handbook/limits.md", "score": 0.8,
     "text": "Bursts above the rate limit receive HTTP 429 with a Retry-After header. See [kb-1]."},
]
result = optimize(OptimizeRequest.model_validate({
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "Answer from the documents and cite them as [id]."},
        {"role": "user", "content": "What is the API rate limit and what happens when I exceed it?"},
    ],
    "documents": documents,
}))
for doc_id, entry in result.citation_map.items():
    into = f" into [{entry.into}]" if entry.into else ""
    print(f"[{doc_id}] {entry.status}{into}{f' ({entry.reason})' if entry.reason else ''}")
print("kept, best first:", [d.id for d in result.documents], "citations preserved:", result.citations_preserved)
