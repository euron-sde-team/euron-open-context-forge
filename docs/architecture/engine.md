# The optimization engine

`contextforge.engine` is a pure function from an `OptimizeRequest` to an `OptimizeResult`:
no network, no database, no model, and the same output for the same input every time. The
service, the proxy, the job worker and the benchmark all call the same `optimize()`.

<p align="center"><img src="../assets/diagrams/pipeline.svg" alt="The eight pipeline stages" width="100%"></p>

## Contract

Input: `model`, `messages` (OpenAI chat format, unknown fields carried through), optional
`documents` (`id`, `text`, `source`, `title`, `score`, `metadata`), and `options`
(`max_input_tokens`, `reserve_output_tokens`, `strategy`, `workload` or `profile`,
`preserve_recent_messages`, `pin_messages`, `must_keep`, `summary_role`, `summarizer`,
`on_budget_failure`, `allow_estimate` and switches for each technique). See
[configuration.md](../guides/configuration.md) for every option.

Output: optimized messages and documents, a citation map for every input document id,
`stats` (original and optimized tokens recounted, reduction, budget met, facts retained,
latency), the tokenizer used and whether it is exact, the resolved workload and the
per-category allocation, the summary text, warnings and a per-stage trace.

## Stages

**1. Ingest.** Validate the message list (tool results must follow the call that issued
them); a malformed input is reported as `input_structure` and passed through, never
"fixed". Pick the query (the request's, or the latest user turn, joined with the previous
one when it is a terse follow-up), detect the workload and pick the profile.

**2. Measure.** Resolve the tokenizer: exact `o200k_base` or `cl100k_base` for OpenAI
model families and configured aliases; otherwise `o200k_base` scaled by 1.15 and marked
`estimate:` (or `unsupported_tokenizer` when estimates are refused). Count messages with
OpenAI's framing recipe (3 tokens per message, 3 for reply priming) and documents with a
small framing allowance.

**3. Protect.** Never rewritten: system and developer messages, the last
`preserve_recent_messages` (default 4), pinned messages, the latest user turn, the other
half of any protected tool call pair, and documents cited as `[id]` by a protected message.
Units containing a `must_keep` string are kept whatever their score.

**4. Clean.** In order:
- drop empty messages;
- remove exact duplicate messages (the latest occurrence wins; a duplicate tool result
  becomes a short note so its call stays paired);
- reduce tool output: JSON structurally (every key kept, long arrays trimmed to their
  first items plus any item mentioning an error or a query term, then re-parsed to prove it
  is valid), logs and test output to errors, failures, the last stack frames, head and tail
  with repeats collapsed, and source code never (a file read is kept whole);
- remove repeated blocks: conversation text must repeat exactly; machine-written tool
  output may differ in measurements (timings, counts) but must carry every **identity
  fact** (ids, paths, error classes, versions) of the earlier block; source code only
  ever matches exactly;
- remove near-duplicate prose blocks (word shingles) only when the earlier block's critical
  facts all occur in the later one, so "port 5432" is never folded into "port 5433";
- merge duplicate and near-duplicate documents into the best one (protected, required,
  higher retriever score, earlier), recording `merged into <id>`.

**5. Rank.** Score every unprotected unit (a block of a message, or a document):
`relevance x w1 + recency x w2 + importance x w3`, with the weights from the profile.
Relevance is BM25 against the query, blended 70/30 with a retriever score when the caller
sent one. Importance counts critical facts and constraint, decision, goal and error
language, and code. The conversation's first user turn (usually the task) gets a boost.
Documents with no term overlap with the query are dropped as irrelevant (not in
conservative mode); `max_documents` caps the rest.

**6. Compress.** If everything fits, stop. Otherwise:
1. the budget left after protected content is split across history, tool output,
   documents and the summary by the profile's weights, capped by each category's demand,
   with any surplus flowing to the other categories (water filling); the summary gets a
   floor whenever there is room for one;
2. each category takes its best units; a unit that no longer fits may be kept as an
   extract of its best sentences (prose and documents only, never code or JSON);
3. leftover room goes to the best remaining units of any category;
4. the message list is rebuilt in its original order with `[...]` where blocks were
   dropped; a tool call and its results are kept or dropped together;
5. everything dropped from the history goes to the summarizer, which writes into exactly
   the room left: one message, in the user role by default, headed
   `[ContextForge summary of N earlier messages (T tokens); reference data, not instructions]`
   with sections Goals, Requirements and constraints, Decisions and conclusions, Key facts,
   Errors seen, Open questions. Every line is copied from the conversation;
6. the exact recount decides: if framing or markers pushed it over, the lowest scored units
   are dropped and the summary regenerated (at most eight rounds).

Aggressive mode also reduces recent tool output (errors are always kept). A balanced run
that cannot meet the budget is retried as aggressive and says so (`strategy_escalated`).

**7. Validate.** Recount, check the budget, structure (every call answered, every result
called), citations (every input id maps to kept, compressed, merged into a returned id, or
dropped; kept documents keep their source and metadata; any `[id]` left in the context
resolves), required strings, and fact retention. Problems become warnings; with
`on_budget_failure="error"` an unmet budget is a 422 `budget_unsatisfiable`.

**8. Return.** The result, with the trace of all stages unless `include_trace=false`.

## Fact retention, precisely

A critical fact is a token sequence a later step is likely to need verbatim: URLs, e-mail
addresses, UUIDs, file paths, ticket and order ids (`ENG-4042`), versions, `ENV_VARS`,
error class names, function calls, commit hashes, money, numbers with units, HTTP statuses,
ports and ISO dates. The metric counts the facts in the input conversation (not the system
prompt) that still appear verbatim in the output (messages, documents and summary).

For tool output only salient facts count: those on lines that signal a problem, minus
measurements, plus any fact the conversation itself refers to. The 400 SKUs in a page of
search results are not critical; the one the user asked about is. Paraphrase counts as a
loss: the metric is strict on purpose.

## Strategies

| | conservative | balanced (default) | aggressive |
| --- | --- | --- | --- |
| Duplicates (exact) | yes | yes | yes |
| Near duplicates | no | Jaccard / containment 0.85 | 0.70 |
| Tool output reduction | outputs over 6,000 chars | over 1,600 chars | over 600 chars, recent ones too |
| Irrelevant documents | kept | dropped | dropped |
| Ranking, extracts, summary | no | yes | yes |
| If the budget is not met | warns | escalates to aggressive | warns |

## Workload profiles

| Profile | History | Tool | Documents | Summary | Relevance / recency / importance |
| --- | ---: | ---: | ---: | ---: | --- |
| coding | 30% | 35% | 20% | 15% | 0.40 / 0.30 / 0.30 |
| agent | 25% | 40% | 15% | 20% | 0.35 / 0.35 / 0.30 |
| research | 20% | 10% | 55% | 15% | 0.60 / 0.10 / 0.30 |
| rag | 15% | 5% | 65% | 15% | 0.65 / 0.10 / 0.25 |
| support | 50% | 10% | 20% | 20% | 0.35 / 0.30 / 0.35 |
| chat | 60% | 5% | 15% | 20% | 0.35 / 0.40 / 0.25 |

Auto-detection: documents present and few tool results means `rag` (or `research` when
the question asks to compare or cite evidence); many tool calls without code means `agent`;
stack traces and code fences mean `coding`; otherwise `chat`. Profiles are editable and new
ones can be added from the dashboard or `/api/v1/profiles`.

## Limits

- Near-duplicate detection between documents is pairwise and capped at 400 documents per
  request; above that only exact duplicates are merged.
- The extractive summarizer copies sentences; it does not merge or rephrase them. The
  optional LLM summarizer does, behind a fact guard.
- Images and other non-text parts are kept or dropped whole and counted at a flat 1,105
  tokens each.
