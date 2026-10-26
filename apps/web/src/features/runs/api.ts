"use client";

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export interface RunFilters {
  source?: string;
  workload?: string;
  budget_missed?: boolean;
}

export function useRuns(filters: RunFilters, limit = 50) {
  return useInfiniteQuery({
    queryKey: qk.runs({ ...filters, limit }),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/runs", {
          params: {
            query: {
              cursor: pageParam,
              limit,
              source: filters.source || null,
              workload: filters.workload || null,
              budget_missed: filters.budget_missed ?? false,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
    staleTime: STALE.live,
    refetchInterval: 15_000,
  });
}

/** Stored input and output of a run (admins, and only when STORE_CONTENT is on). */
export function useRunContent(id: number | null, enabled: boolean) {
  return useQuery({
    queryKey: [...qk.run(id ?? 0), "content"],
    queryFn: () => unwrap(api.GET("/api/v1/runs/{run_id}/content", { params: { path: { run_id: id ?? 0 } } })),
    enabled: enabled && id != null,
    staleTime: STALE.static,
    retry: false,
  });
}

export function useRun(id: number | null) {
  return useQuery({
    queryKey: qk.run(id ?? 0),
    queryFn: () => unwrap(api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: id ?? 0 } } })),
    enabled: id != null,
    staleTime: STALE.static,
  });
}
