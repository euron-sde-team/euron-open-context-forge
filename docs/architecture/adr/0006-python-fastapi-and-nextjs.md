# ADR-0006: Python and FastAPI for the engine and service, Next.js for the dashboard

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

ContextForge lives in the LLM ecosystem: tokenizers (tiktoken), provider wire formats,
retrieval and evaluation tooling are Python first, and the people integrating a context
optimizer into a RAG pipeline or an agent are mostly writing Python. The engine should be
importable as a library by those applications, not only reachable over HTTP. The Euron
open-source projects also share a fixed rule: Python and FastAPI backends, Next.js
frontends, no exceptions.

## Decision

The engine, the API (optimize endpoints, proxy, dashboard API) and the worker are one
Python 3.12 package, `contextforge`, on FastAPI, Pydantic v2, SQLAlchemy 2 (async,
asyncpg), Alembic, redis-py, httpx, tiktoken and boto3, managed by uv and checked with ruff
and mypy `--strict`. The engine subpackage has no I/O and no dependency on the service, so
`from contextforge import optimize` works in-process. The CPU-bound engine runs in a worker
thread (`asyncio.to_thread`) on the request path, so the event loop stays free.

The dashboard is Next.js 15 (App Router, React 19, TypeScript strict, Tailwind, shadcn
components, TanStack Query), proxying `/api` and `/v1` to the API so the browser stays
same-origin.

## Consequences

**Good**
- tiktoken gives exact counts for OpenAI model families with no second implementation.
- One codebase serves the library, the REST service and the proxy, sharing Pydantic types.
- Typed contracts on both sides: the dashboard's types are generated from the OpenAPI
  document, and a drift test keeps `docs/api/openapi.yaml` in sync with the app.

**Bad / caveats**
- Python's per-request CPU cost is higher than Go or Rust, and optimization is CPU bound.
  The service scales horizontally (stateless processes), and long inputs move to background
  jobs.
- The GIL limits parallel engine work within one process; throughput comes from more
  processes or replicas.

## Alternatives considered

- **Go or Rust service.** Faster per request, but no in-process library for Python
  applications and a weaker tokenizer ecosystem.
- **A plain React SPA.** Next.js gives routing, code splitting and a same-origin proxy, and
  matches the sibling projects.
