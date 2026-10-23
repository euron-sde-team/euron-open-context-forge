"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export function useBenchmarkRuns() {
  return useQuery({
    queryKey: qk.benchmarks,
    queryFn: () => unwrap(api.GET("/api/v1/benchmarks", { params: { query: { limit: 20 } } })),
    staleTime: STALE.live,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2_000 : false),
  });
}

export function useBenchmarkRun(id: string | undefined) {
  return useQuery({
    queryKey: qk.benchmark(id ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/benchmarks/{run_id}", { params: { path: { run_id: id ?? "" } } })),
    enabled: !!id,
    staleTime: STALE.static,
  });
}

export function useDataset() {
  return useQuery({
    queryKey: qk.dataset,
    queryFn: () => unwrap(api.GET("/api/v1/benchmarks/dataset")),
    staleTime: STALE.static,
  });
}

export function useQueueBenchmark() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runs: number) => unwrap(api.POST("/api/v1/benchmarks", { body: { runs_per_case: runs } })),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.benchmarks }),
  });
}
