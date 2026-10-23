/**
 * Query keys in one place, so invalidation after a mutation names exactly what it
 * touched.
 */
export const qk = {
  me: ["auth", "me"] as const,
  system: ["system"] as const,
  users: ["users"] as const,
  keys: (includeRevoked = false) => ["keys", { includeRevoked }] as const,
  keysAll: ["keys"] as const,
  upstreams: ["upstreams"] as const,
  profiles: ["profiles"] as const,
  runs: (filters: object) => ["runs", "list", filters] as const,
  run: (id: number) => ["runs", "detail", id] as const,
  runsAll: ["runs"] as const,
  overview: (days: number) => ["analytics", "overview", days] as const,
  analyticsAll: ["analytics"] as const,
  jobs: ["jobs"] as const,
  benchmarks: ["benchmarks"] as const,
  benchmark: (id: string) => ["benchmarks", "detail", id] as const,
  dataset: ["benchmarks", "dataset"] as const,
  samples: ["playground", "samples"] as const,
  sample: (id: string) => ["playground", "sample", id] as const,
  audit: (action?: string) => ["audit", { action }] as const,
};

/** staleTime per kind of data, chosen deliberately (see docs/architecture/HLD.md). */
export const STALE = {
  analytics: 15_000,
  config: 30_000,
  live: 5_000,
  static: 5 * 60_000,
} as const;
