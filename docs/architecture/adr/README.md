# Architecture Decision Records

Each ADR captures one significant decision: the context that forced it, what we chose,
and what it costs us. ADRs are immutable once accepted. To revisit one, write a new ADR
that supersedes it.

| ADR | Decision | Status |
| --- | -------- | ------ |
| [0001](0001-deterministic-engine-first.md) | The default optimization path is deterministic: no model, no GPU, no network | Accepted |
| [0002](0002-redis-optional-in-process-fallback.md) | Redis is optional; every Redis use has an in-process fallback and degrades on outage | Accepted |
| [0003](0003-summaries-are-user-role.md) | Generated summaries are a `user` message framed as reference data, never `system` by default | Accepted |
| [0004](0004-fact-retention-quality-metric.md) | Strict verbatim fact retention is the quality metric reported on every request | Accepted |
| [0005](0005-openai-chat-format-and-proxy.md) | The OpenAI chat format is the message contract; the proxy optimizes, then forwards | Accepted |
| [0006](0006-python-fastapi-and-nextjs.md) | Python and FastAPI for the engine and service, Next.js for the dashboard | Accepted |
| [0007](0007-local-aws-emulation.md) | Local AWS emulator (Floci), provisioned by the same Terraform as production | Accepted |

**Template:** Status / Date, then Context, Decision, Consequences (good and bad), and
Alternatives considered.
