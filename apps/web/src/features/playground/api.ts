"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { OptimizeRequest } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useSamples() {
  return useQuery({
    queryKey: qk.samples,
    queryFn: () => unwrap(api.GET("/api/v1/playground/samples")),
    staleTime: STALE.static,
  });
}

export function useSample(id: string | null) {
  return useQuery({
    queryKey: qk.sample(id ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/playground/samples/{sample_id}", { params: { path: { sample_id: id ?? "" } } })),
    enabled: !!id,
    staleTime: STALE.static,
  });
}

export function useOptimize() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: OptimizeRequest) => unwrap(api.POST("/api/v1/playground/optimize", { body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.runsAll });
      void client.invalidateQueries({ queryKey: qk.analyticsAll });
    },
  });
}
