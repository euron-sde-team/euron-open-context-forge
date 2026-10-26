# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-26

First public release: the deterministic engine, the service, the proxy and the dashboard.

### Added

- Deterministic optimization engine (`contextforge.engine`), importable as a library: eight
  stages (ingest, measure, protect, clean, rank, compress, validate, return), three
  strategies (conservative, balanced, aggressive) with automatic escalation, no network and
  no model on the default path.
- Tokenizer registry: exact tiktoken counts for OpenAI model families, configurable aliases,
  and an explicitly marked estimate (or a structured refusal) for every other model.
- Protection of system instructions, recent turns, pinned messages, the latest user turn,
  tool call pairs, cited documents and caller `must_keep` strings.
- Exact and near-duplicate removal for messages, paragraphs and documents; repeated tool runs
  collapsed while ids, paths and error classes are compared; file reads never cut.
- Tool output reduction for logs, stack traces and JSON (always valid JSON afterwards).
- BM25 ranking, extractive sentence selection, and a structured summary of dropped history
  (goals, requirements, decisions, facts, errors, open questions) placed in the user role.
- Adaptive context budgeting with six built-in workload profiles and custom profiles.
- Per-request quality safeguards: fact retention, citation map, structure and JSON
  validation, required-content checks, a per-stage trace and honest budget warnings.
- Optional LLM summarizer over any OpenAI-compatible endpoint, with a fact guard and an
  extractive fallback.
- REST API: `/v1/context/optimize`, `count-tokens`, `summarize`, `rank` and background
  `jobs`, authenticated by `cfk_` service keys with per-key rate limits.
- OpenAI-compatible proxy (`/v1/chat/completions`, streaming) that optimizes and forwards to
  named upstreams, with optional TokenShield and SmartRouter adapters.
- Runs history with same-transaction hourly rollups, analytics, and a result cache (Redis,
  or in process when Redis is absent).
- Reproducible benchmark on committed synthetic datasets against truncation, `make
  benchmark`, plus a service latency benchmark, `make bench`.
- Dashboard: overview, playground with before and after, runs, jobs, benchmarks, profiles,
  API keys, upstreams, integrations, users, audit log and settings, light and dark.
- Terraform for AWS (VPC, RDS, ElastiCache, S3, KMS, Secrets Manager, ECR, ECS Fargate,
  ALB, WAF, CloudWatch) and a local stack on Floci provisioned by the same modules.
- One-command AWS rollout (`make aws-deploy`, `aws-migrate`, `aws-admin`) and
  `make migration` for new Alembic revisions.

### Security

- Bounded work per request: linear sentence extraction, a per-process engine concurrency
  limit with 503 `engine_busy`, a JSON nesting cap for tool output, a capped `/rank`
  near-duplicate pass, and a bounded tokenizer count cache that never retains large prompts.
- Requests with unpaired UTF-16 surrogates are refused with 422 instead of failing later.
- Sign-out revokes the session server-side; failed sign-ins are audited and counted
  atomically; argon2 runs off the event loop; the client IP comes only from trusted proxies.
- Moving an upstream to another host requires its API key again.
- Malformed service key prefixes and upstream names are rejected before any cache or
  database lookup; the config cache is bounded.
- Dashboard: same-origin post-login redirects only, Content-Security-Policy and HSTS.
- Jobs: lease renewal, fenced result writes and an attempts cap for jobs that crash workers;
  one active benchmark enforced by the database.
- Streamed proxy responses are decoded before relay and close their upstream connection on
  every path.
- Signed-out sessions are kept in Postgres, so cache eviction cannot revive them.
- Database errors never log bound values (password or key hashes); uniqueness races answer
  409, validation errors raised inside handlers 422, expired storage objects 410.
- Body size limit enforced for chunked uploads; every CPU endpoint shares the engine's
  bounded pool; the in-process cache is bounded in bytes.
- Upstreams cannot target link-local or instance metadata addresses; keys cannot default to
  a profile or upstream that does not exist, and those cannot be deleted while in use.
