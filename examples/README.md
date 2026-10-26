# Examples

| File | Shows | Needs |
| --- | --- | --- |
| [library_quickstart.py](library_quickstart.py) | The engine as a library on a coding agent's history: stats, warnings and the per-stage trace | Nothing (runs offline) |
| [rag_citations.py](rag_citations.py) | A noisy retrieval: duplicates merged, irrelevant chunks dropped, every citation mapped | Nothing (runs offline) |
| [openai_proxy.py](openai_proxy.py) | An unmodified OpenAI SDK through the proxy, with the savings headers | `make up && make demo` and the printed key |

Run them from `apps/api` so the package and its dependencies are on the path:

```bash
cd apps/api
uv run python ../../examples/library_quickstart.py
uv run python ../../examples/rag_citations.py
CONTEXTFORGE_KEY=cfk_... uv run python ../../examples/openai_proxy.py
```
