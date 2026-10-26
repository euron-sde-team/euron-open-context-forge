"use client";

import { PencilIcon, PlusIcon, RotateCcwIcon, SlidersHorizontalIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { Profile, ProfileIn, Weights } from "@/lib/api/types";
import { workloadLabel } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";

import { useDeleteProfile, useProfiles, useSaveProfile } from "../api";

const CATEGORIES: { key: keyof Weights; label: string; className: string }[] = [
  { key: "history", label: "History", className: "bg-primary" },
  { key: "tool", label: "Tool output", className: "bg-info" },
  { key: "documents", label: "Documents", className: "bg-savings" },
  { key: "summary", label: "Summary", className: "bg-warning" },
];
const RANKING = [
  { key: "relevance", label: "Relevance" },
  { key: "recency", label: "Recency" },
  { key: "importance", label: "Importance" },
] as const;

export function shares(w: Weights): Record<keyof Weights, number> {
  const total = w.history + w.tool + w.documents + w.summary || 1;
  return { history: w.history / total, tool: w.tool / total, documents: w.documents / total, summary: w.summary / total };
}

function WeightBar({ weights }: { weights: Weights }) {
  const s = shares(weights);
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        {CATEGORIES.map((c) => (
          <div key={c.key} className={cn("h-full", c.className)} style={{ width: `${s[c.key] * 100}%` }} />
        ))}
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
        {CATEGORIES.map((c) => (
          <li key={c.key} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className={cn("size-2 rounded-[3px]", c.className)} aria-hidden />
              {c.label}
            </span>
            <span className="font-medium tabular">{Math.round(s[c.key] * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ProfileDialog({ profile, open, onOpenChange }: { profile: Profile | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const save = useSaveProfile();
  const creating = profile == null;
  const [form, setForm] = React.useState<ProfileIn>({
    name: "",
    description: "",
    weights: { history: 0.4, tool: 0.2, documents: 0.2, summary: 0.2 },
    relevance: 0.4,
    recency: 0.3,
    importance: 0.3,
  });
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      profile
        ? {
            name: profile.name,
            description: profile.description,
            weights: profile.weights,
            relevance: profile.relevance,
            recency: profile.recency,
            importance: profile.importance,
          }
        : { name: "", description: "", weights: { history: 0.4, tool: 0.2, documents: 0.2, summary: 0.2 }, relevance: 0.4, recency: 0.3, importance: 0.3 },
    );
  }, [open, profile]);

  const num = (v: string) => Math.min(1, Math.max(0, Number(v) || 0));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (creating && !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(form.name)) {
      setError("Use lowercase letters, digits, - or _ for the name, for example incident-review.");
      return;
    }
    const w = form.weights;
    if (w.history + w.tool + w.documents + w.summary <= 0) {
      setError("At least one category needs a weight above zero.");
      return;
    }
    if (form.relevance + form.recency + form.importance <= 0) {
      setError("At least one ranking weight needs to be above zero.");
      return;
    }
    save.mutate(
      { body: form, create: creating },
      {
        onSuccess: () => {
          toast.success(creating ? `Profile ${form.name} created.` : `Profile ${form.name} saved.`);
          onOpenChange(false);
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !save.isPending && onOpenChange(o)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{creating ? "New profile" : `Edit ${profile?.name}`}</DialogTitle>
          <DialogDescription>
            Weights are relative: they are normalised to shares of the budget left after protected content.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name" htmlFor="p-name">
                <Input id="p-name" value={form.name} disabled={!creating} onChange={(e) => setForm({ ...form, name: e.target.value.trim() })} placeholder="incident-review" />
              </Field>
              <Field label="Description" htmlFor="p-desc">
                <Input id="p-desc" value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </Field>
            </div>
            <div>
              <div className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
                Budget split <Hint term="profile" />
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {CATEGORIES.map((c) => (
                  <Field key={c.key} label={<span className="text-xs text-muted-foreground">{c.label}</span>} htmlFor={`w-${c.key}`}>
                    <Input
                      id={`w-${c.key}`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      className="tabular"
                      value={form.weights[c.key]}
                      onChange={(e) => setForm({ ...form, weights: { ...form.weights, [c.key]: num(e.target.value) } })}
                    />
                  </Field>
                ))}
              </div>
              <div className="mt-3">
                <WeightBar weights={form.weights} />
              </div>
            </div>
            <div>
              <div className="mb-2 text-[13px] font-medium">Ranking</div>
              <div className="grid grid-cols-3 gap-3">
                {RANKING.map((r) => (
                  <Field key={r.key} label={<span className="text-xs text-muted-foreground">{r.label}</span>} htmlFor={`r-${r.key}`}>
                    <Input
                      id={`r-${r.key}`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      className="tabular"
                      value={form[r.key]}
                      onChange={(e) => setForm({ ...form, [r.key]: num(e.target.value) })}
                    />
                  </Field>
                ))}
              </div>
            </div>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Saving..." : creating ? "Create profile" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ProfilesScreen() {
  const { canWrite } = usePermissions();
  const profiles = useProfiles();
  const remove = useDeleteProfile();
  const [editing, setEditing] = React.useState<Profile | null>(null);
  const [dialog, setDialog] = React.useState(false);
  const [target, setTarget] = React.useState<Profile | null>(null);

  const open = (p: Profile | null) => {
    setEditing(p);
    setDialog(true);
  };

  return (
    <>
      <PageHeader
        title="Profiles"
        description="Adaptive context budgeting: how each workload splits its budget between history, tool output, documents and the summary."
        actions={
          canWrite && (
            <Button onClick={() => open(null)}>
              <PlusIcon />
              New profile
            </Button>
          )
        }
      />
      {profiles.isError && !profiles.data ? (
        <Surface>
          <ErrorState error={profiles.error} onRetry={() => void profiles.refetch()} />
        </Surface>
      ) : !profiles.data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-52 rounded-2xl" />
          ))}
        </div>
      ) : profiles.data.length === 0 ? (
        <Surface>
          <EmptyState icon={SlidersHorizontalIcon} title="No profiles" description="The built-in profiles should always be listed. Reload them from the API."
            action={<Button variant="outline" size="sm" onClick={() => void profiles.refetch()}>Reload</Button>}
          />
        </Surface>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {profiles.data.map((p) => (
            <Surface key={p.name} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="font-mono text-[14px] font-semibold">{p.name}</h2>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{p.description || "No description"}</p>
                </div>
                <Chip tone={p.builtin ? (p.customized ? "warning" : "neutral") : "primary"}>
                  {p.builtin ? (p.customized ? "Edited" : "Built in") : "Custom"}
                </Chip>
              </div>
              <div className="mt-4 flex-1">
                <WeightBar weights={p.weights} />
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
                  {RANKING.map((r) => (
                    <span key={r.key}>
                      {r.label} <span className="font-medium text-foreground tabular">{Math.round(p[r.key] * 100)}%</span>
                    </span>
                  ))}
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between gap-2">
                <span className="text-[11.5px] text-faint">
                  {p.builtin && !p.customized ? `Workload: ${workloadLabel(p.name)}` : p.updated_at ? `Updated ${formatDate(p.updated_at)}` : ""}
                </span>
                {canWrite && (
                  <div className="flex gap-1">
                    <Button variant="subtle" size="xs" aria-label={`Edit ${p.name}`} onClick={() => open(p)}>
                      <PencilIcon />
                      Edit
                    </Button>
                    {(!p.builtin || p.customized) && (
                      <Button variant="subtle" size="xs" aria-label={`${p.builtin ? "Reset" : "Delete"} ${p.name}`} onClick={() => setTarget(p)}>
                        {p.builtin ? <RotateCcwIcon /> : <Trash2Icon />}
                        {p.builtin ? "Reset" : "Delete"}
                      </Button>
                    )}
                  </div>
                )}
              </div>
            </Surface>
          ))}
        </div>
      )}
      <ProfileDialog profile={editing} open={dialog} onOpenChange={setDialog} />
      <ConfirmDialog
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        title={target?.builtin ? `Reset ${target?.name}?` : `Delete ${target?.name}?`}
        description={
          target?.builtin
            ? "The profile goes back to the weights it ships with. Cached results that used the edited weights are invalidated."
            : "Requests and keys that name this profile will be refused until they pick another one."
        }
        confirmLabel={target?.builtin ? "Reset profile" : "Delete profile"}
        pending={remove.isPending}
        onConfirm={() =>
          target &&
          remove.mutate(target.name, {
            onSuccess: () => {
              toast.success(target.builtin ? "Profile reset." : "Profile deleted.");
              setTarget(null);
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </>
  );
}
