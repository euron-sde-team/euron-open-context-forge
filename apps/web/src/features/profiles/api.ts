"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ProfileIn } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

export function useProfiles() {
  return useQuery({
    queryKey: qk.profiles,
    queryFn: () => unwrap(api.GET("/api/v1/profiles")),
    staleTime: STALE.config,
  });
}

export function useSaveProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, create }: { body: ProfileIn; create: boolean }) =>
      create
        ? unwrap(api.POST("/api/v1/profiles", { body }))
        : unwrap(api.PUT("/api/v1/profiles/{name}", { params: { path: { name: body.name } }, body })),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.profiles }),
  });
}

export function useDeleteProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => unwrap(api.DELETE("/api/v1/profiles/{name}", { params: { path: { name } } })),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.profiles }),
  });
}
