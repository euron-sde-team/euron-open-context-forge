"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export function useJobs() {
  return useQuery({
    queryKey: qk.jobs,
    queryFn: () => unwrap(api.GET("/api/v1/jobs", { params: { query: { limit: 100 } } })),
    staleTime: STALE.live,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 2_000 : 15_000),
  });
}
