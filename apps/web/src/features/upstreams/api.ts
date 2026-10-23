"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { UpstreamIn, UpstreamUpdate } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useUpstreams() {
  return useQuery({
    queryKey: qk.upstreams,
    queryFn: () => unwrap(api.GET("/api/v1/upstreams")),
    staleTime: STALE.config,
  });
}

function useDone() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: qk.upstreams });
    void client.invalidateQueries({ queryKey: qk.system });
  };
}

export function useCreateUpstream() {
  const done = useDone();
  return useMutation({ mutationFn: (body: UpstreamIn) => unwrap(api.POST("/api/v1/upstreams", { body })), onSuccess: done });
}

export function useUpdateUpstream() {
  const done = useDone();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpstreamUpdate }) =>
      unwrap(api.PATCH("/api/v1/upstreams/{upstream_id}", { params: { path: { upstream_id: id } }, body })),
    onSuccess: done,
  });
}

export function useDeleteUpstream() {
  const done = useDone();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/upstreams/{upstream_id}", { params: { path: { upstream_id: id } } })),
    onSuccess: done,
  });
}
