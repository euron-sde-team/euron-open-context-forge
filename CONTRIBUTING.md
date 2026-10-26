# Contributing

Thanks for helping improve Euron Open ContextForge. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. See
  [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and
pnpm 9 (`corepack enable`).

```bash
make up          # Postgres, Redis, Floci (provisioned by Terraform), mock LLM, api, worker, web
make demo        # keys, upstreams, 60 days of runs, a benchmark, live traffic
make test        # unit tests (API and web)
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack in detail.

## Before you open a pull request

Each of these must pass:

```bash
make lint typecheck test
make test-integration                  # the API against real Postgres and Redis
make e2e                               # when you touched a dashboard flow or infrastructure
make benchmark                         # when you touched the engine (results must not regress)
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make tf-aws-on-floci                   # same: apply and destroy aws-dev against Floci
make openapi                           # when you changed an endpoint (a test checks drift)
make sanitize                          # no credentials, account ids, resource ids or dashes
```

## Conventions

**Package by domain.** `apps/api/src/contextforge/<domain>/` owns its `router.py` (HTTP
only), `schemas.py` (the public contract), `service.py` (rules) and `models.py`.
Dependencies point inward: router, service, data. A domain calls another domain's service,
never its tables.

**The engine stays pure.** `contextforge/engine/` has no I/O: no network, no database, no
clock in its output. It must keep working as a library with only pydantic, tiktoken and
orjson installed. Anything that needs the outside world (an LLM summarizer, storage, a
cache) lives in the service layer and plugs in through a Protocol.

**Never optimize for tokens alone.** A change that removes more tokens must keep the
benchmark's fact and citation retention where they are (`make benchmark`, and the AC13
test), and must not touch protected content: system messages, recent turns, tool call
pairs. Add a test for any new removal rule that shows what it keeps.

**Redis is optional.** Every Redis use goes through `core/kv.py`, has an in-process
fallback, and treats a Redis error as a cache miss or a pass. The test matrix runs the
whole integration suite without Redis.

**External systems sit behind a Protocol.** Tokenizers (`Tokenizer`), summarizers
(`Summarizer`), key sealing (`KeySealer`), storage (`ObjectStorage`) and upstream kinds
(`UpstreamAdapter`). Adding an upstream kind means one file in `integrations/` and one
line in `integrations/registry.py`.

**Configuration is validated.** A new setting goes in `core/config.py`, is documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR, and
security-relevant ones are enforced by `Settings.guard()` at boot.

**Database changes are new migrations.** Change the models, then run
`make migration MSG="what changed"`: it migrates the local Postgres and autogenerates a
revision under `apps/api/src/contextforge/migrations/versions/` for you to review. Indexes
and constraints are declared on the models (`__table_args__`), so autogenerate sees them.
Never edit an applied one. Indexes for
every new filter the API exposes belong in the same revision.

**Comments explain why.** The code says what it does. Comments are for the constraint, the
incident, or the trade-off that made it this way.

**Style.** ruff and mypy `--strict` for Python; ESLint and TypeScript strict for the web.
No em dashes or en dashes anywhere (the sanitization check enforces it).

## Commit messages

Imperative mood with an optional scope: `engine: keep file reads whole`,
`web: sort the citation list kept first`. Explain the why in the body when
it is not obvious.

## Architecture decisions

Significant decisions are recorded in [docs/architecture/adr/](docs/architecture/adr/).
If your change reverses or extends one, add a new ADR rather than editing the old one.
