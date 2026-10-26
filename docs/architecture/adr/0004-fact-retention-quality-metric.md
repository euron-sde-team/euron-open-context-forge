# ADR-0004: Fact retention is the per-request quality metric

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

A context optimizer has to prove, on every request and not only in a benchmark, that it
did not remove what the task needs. Answer quality itself cannot be measured inline: there
is no reference answer, and judging with a model would put a model on the default path
(ADR-0001). Token reduction alone rewards deleting everything.

What usually breaks a downstream step after compression is a lost exact value: an order id,
a file path, a version, an error class, an environment variable, a URL. These are easy to
recognise and easy to check.

## Decision

Every optimization reports `facts_total`, `facts_retained` and `fact_retention`
(`engine/pipeline.py`, `engine/text.py`), stored on each run and rolled up hourly.

- **Strict and verbatim.** A fact counts as retained only if the exact string appears
  somewhere in the optimized messages or documents (the summary included). Paraphrase does
  not count.
- **What is a fact.** Pattern-matched critical values: URLs, email addresses, UUIDs, paths
  with an extension, ticket and order ids (`ORD-12345`), versions, `UPPER_SNAKE` constants,
  error and exception class names, function calls, commit hashes, money amounts, quantities
  with units, HTTP status codes, ports and ISO dates.
- **Which messages.** Facts are collected from user, assistant and tool messages. System
  and developer messages are excluded because they are returned verbatim anyway.
- **Salient facts for tool output.** Tool output is mostly bulk (400 search results, a
  full log). For log and JSON blocks, only facts on lines that signal a problem (error,
  exception, fail, warn, timeout, not found, ...) count, plus any fact the conversation
  itself refers to. Prose and code returned by tools count in full.
- **Identity versus measurement.** On those problem lines, identity facts (ids, paths,
  names, versions, error classes) count; measurements (durations, counts, sizes,
  percentages, dates, bare ports) count only when the conversation refers to them, because
  they change from one run of a tool to the next. The same split decides tool-output
  deduplication: two blocks that differ only in measurements collapse, but only when the
  later block carries every identity fact of the earlier one.

Callers who need more than heuristics name strings in `must_keep`; any that would be lost
produce `required_content_missing`. The benchmark (`make benchmark`) measures retention of
hand-picked gold facts with the same strict rule.

## Consequences

**Good**
- A per-request, model-free, explainable quality signal, visible in the response, the run
  history and the dashboard.
- Strictness errs on the side of reporting loss: a reworded fact is a lost fact.
- The salient and identity rules stop the metric from forcing ContextForge to keep every
  timestamp and counter in a log, which would defeat tool-output reduction.

**Bad / caveats**
- It is a proxy. A context can retain every fact and still lose a nuance (a negation, a
  preference stated in prose) that the patterns do not see.
- The patterns are regular expressions tuned for technical English text.
- Measurements dropped from unreferenced log lines are not counted as losses, by design.

## Alternatives considered

- **LLM-judged answer accuracy per request.** Accurate but costly, nondeterministic and
  model-dependent; planned for CI on the benchmark, not inline.
- **Embedding similarity between input and output.** Rewards topical overlap, not exact
  values, and needs a model.
- **Counting every fact in tool output.** Makes tool-output reduction look like loss and
  pushes the optimizer to keep bulk.
