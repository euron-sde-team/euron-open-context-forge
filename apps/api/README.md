# contextforge (engine, API, proxy and worker)

The Python package behind Euron Open ContextForge: the deterministic optimization engine
(`contextforge.engine`, importable on its own), the `/v1/context` API, the OpenAI-compatible
proxy (`/v1/chat/completions`), the dashboard API (`/api/v1`), the background worker, the
reproducible benchmark (`contextforge.benchmarks`) and a deterministic mock LLM upstream used
by the demo and the tests.

```bash
uv sync
uv run contextforge --help          # serve, worker, migrate, openapi, create-owner, seed-demo, benchmark
uv run pytest tests/unit            # no database, no network
make -C ../.. test-integration      # real Postgres and Redis
```

Layout, conventions and the pipeline: [CONTRIBUTING.md](../../CONTRIBUTING.md) and the
[low-level design](../../docs/architecture/LLD.md).
