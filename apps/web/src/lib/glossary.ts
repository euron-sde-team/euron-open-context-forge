/** Plain-words explanations for ContextForge's vocabulary, shown as inline hints. */
export const GLOSSARY = {
  reduction: "Share of input tokens removed, counted with the target model's own tokenizer before and after.",
  tokensSaved: "Input tokens that were never sent to a model: original minus optimized, summed over runs.",
  factRetention:
    "Share of critical facts (ids, paths, versions, values, error names, constraints) from the conversation that are still present verbatim after optimization. Strict: a paraphrase counts as lost.",
  budgetMet: "Share of runs whose optimized context fits max_input_tokens, recounted with the exact tokenizer.",
  costAvoided:
    "An estimate: tokens removed multiplied by the model's list input price. Configure prices with MODEL_PRICES.",
  cacheHit: "An identical request (same input, options and profiles) answered from the result cache without re-running the engine.",
  exact: "Exact means the count comes from the model's own tokenizer. Other models get a conservative, clearly marked estimate.",
  profile:
    "A workload profile splits the budget between history, tool output, documents and the summary, and weighs relevance, recency and importance when ranking.",
  workload: "The kind of input (coding, agent, research, RAG, support, chat). Detected automatically unless the request names one.",
  strategy:
    "Conservative removes only duplicates and tool bulk; balanced also ranks, extracts and summarises; aggressive squeezes harder and may reduce recent tool output.",
  protected:
    "System instructions, the last N messages, pinned messages and the latest user turn are never rewritten. Tool results stay paired with their calls.",
  citations:
    "Every input document id maps to kept, compressed, merged (into the duplicate that was kept) or dropped, so citations still resolve.",
  allocation: "How the budget left after protected content was split between categories, and how much each used.",
  readerAccuracy:
    "Simulated: a deterministic extractive reader picks the three sentences that best match each question. It stands in for a model; it is not one.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
