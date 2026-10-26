"use client";

import { CableIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/segmented";
import { KindChip, StrategyChip } from "@/components/status-chip";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { Strategy, Upstream, UpstreamKind } from "@/lib/api/types";
import { STRATEGIES } from "@/lib/chips";
import { formatNumber } from "@/lib/format";

import { useCreateUpstream, useDeleteUpstream, useUpdateUpstream, useUpstreams } from "../api";

const KINDS: { value: UpstreamKind; label: string }[] = [
  { value: "openai", label: "OpenAI-compatible" },
  { value: "tokenshield", label: "TokenShield" },
  { value: "smartrouter", label: "SmartRouter" },
];

/** scheme://host[:port], to tell a path change from a move to another host. */
function hostOf(url: string): string {
  try {
    return new URL(url.trim()).origin.toLowerCase();
  } catch {
    return url.trim().toLowerCase();
  }
}

function UpstreamDialog({ upstream, open, onOpenChange }: { upstream: Upstream | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const create = useCreateUpstream();
  const update = useUpdateUpstream();
  const editing = upstream != null;
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<UpstreamKind>("openai");
  const [url, setUrl] = React.useState("");
  const [key, setKey] = React.useState("");
  const [budget, setBudget] = React.useState("");
  const [strategy, setStrategy] = React.useState<Strategy>("balanced");
  const [enabled, setEnabled] = React.useState(true);
  const [clearKey, setClearKey] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const pending = create.isPending || update.isPending;

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setKey("");
    setClearKey(false);
    setName(upstream?.name ?? "");
    setKind((upstream?.kind as UpstreamKind) ?? "openai");
    setUrl(upstream?.base_url ?? "");
    setBudget(upstream?.max_input_tokens ? String(upstream.max_input_tokens) : "");
    setStrategy((upstream?.strategy as Strategy) ?? "balanced");
    setEnabled(upstream?.enabled ?? true);
  }, [open, upstream]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing && !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(name)) return setError("Use lowercase letters, digits, - or _ for the name.");
    if (!/^https?:\/\//.test(url.trim())) return setError("The base URL starts with http:// or https://, for example https://api.openai.com/v1.");
    const n = budget.trim() ? Number(budget) : null;
    if (n != null && (!Number.isInteger(n) || n < 1)) return setError("The default budget is a whole number of tokens, or empty.");
    const hostChanged = editing && upstream && hostOf(url) !== hostOf(upstream.base_url);
    if (hostChanged && upstream.has_api_key && !key && !clearKey)
      return setError("The host changed: enter the API key for the new host, or remove the stored key. A stored key is never sent to a new host.");
    setError(null);
    const done = {
      onSuccess: () => {
        toast.success(editing ? "Upstream saved." : "Upstream added.");
        onOpenChange(false);
      },
      onError: (err: unknown) => setError(errorMessage(err)),
    };
    if (editing && upstream) {
      update.mutate(
        { id: upstream.id, body: { kind, base_url: url.trim(), max_input_tokens: n, strategy, enabled, ...(key ? { api_key: key } : clearKey ? { clear_api_key: true } : {}) } },
        done,
      );
    } else {
      create.mutate({ name, kind, base_url: url.trim(), api_key: key || null, max_input_tokens: n, strategy, enabled }, done);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit ${upstream?.name}` : "Add an upstream"}</DialogTitle>
          <DialogDescription>Where the proxy forwards optimized requests. The credential is sealed at rest and never shown again.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name" htmlFor="u-name">
                <Input id="u-name" value={name} disabled={editing} onChange={(e) => setName(e.target.value.trim())} placeholder="openai" />
              </Field>
              <Field label="Default budget" htmlFor="u-budget" hint="Tokens; empty to clean only">
                <Input id="u-budget" inputMode="numeric" className="tabular" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="8000" />
              </Field>
            </div>
            <Field label="Kind">
              <Segmented<UpstreamKind> ariaLabel="Kind" value={kind} onChange={setKind} options={KINDS} />
            </Field>
            <Field label="Base URL" htmlFor="u-url" hint="OpenAI-compatible base, ending in /v1">
              <Input id="u-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.openai.com/v1" className="font-mono" />
            </Field>
            <Field label="API key" htmlFor="u-key" hint={editing && upstream?.has_api_key ? `Stored (${upstream.key_hint}). Leave empty to keep it.` : "Optional for local models"}>
              <Input id="u-key" type="password" value={key} disabled={clearKey} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
            </Field>
            {editing && upstream?.has_api_key && (
              <label className="flex items-center gap-2 text-[13px]">
                <Switch checked={clearKey} onCheckedChange={(v) => { setClearKey(v); if (v) setKey(""); }} aria-label="Remove stored key" />
                Remove the stored key (for upstreams that need none)
              </label>
            )}
            <Field label="Default strategy">
              <Segmented<Strategy> ariaLabel="Default strategy" value={strategy} onChange={setStrategy} options={STRATEGIES.map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }))} />
            </Field>
            <label className="flex items-center gap-2 text-[13px]">
              <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Enabled" />
              Enabled
            </label>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving..." : editing ? "Save" : "Add upstream"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function UpstreamsScreen() {
  const { canWrite } = usePermissions();
  const upstreams = useUpstreams();
  const remove = useDeleteUpstream();
  const [editing, setEditing] = React.useState<Upstream | null>(null);
  const [dialog, setDialog] = React.useState(false);
  const [target, setTarget] = React.useState<Upstream | null>(null);
  const open = (u: Upstream | null) => {
    setEditing(u);
    setDialog(true);
  };

  return (
    <>
      <PageHeader
        title="Upstreams"
        description="Models the OpenAI-compatible proxy forwards to after optimizing: any OpenAI-compatible API, TokenShield or SmartRouter."
        actions={
          canWrite && (
            <Button onClick={() => open(null)}>
              <PlusIcon />
              Add upstream
            </Button>
          )
        }
      />
      <Surface>
        {upstreams.isError && !upstreams.data ? (
          <ErrorState error={upstreams.error} onRetry={() => void upstreams.refetch()} />
        ) : !upstreams.data ? (
          <div className="p-4">
            <TableSkeleton rows={4} cols={5} />
          </div>
        ) : upstreams.data.length === 0 ? (
          <EmptyState
            icon={CableIcon}
            title="No upstreams yet"
            description="The /v1/context API works without one. Add an upstream to use the OpenAI-compatible proxy: requests are optimized, then forwarded with the upstream's sealed credential."
            action={
              canWrite ? (
                <Button onClick={() => open(null)}>
                  <PlusIcon />
                  Add an upstream
                </Button>
              ) : undefined
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Upstream</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead className="hidden lg:table-cell">Base URL</TableHead>
                <TableHead className="hidden md:table-cell">Defaults</TableHead>
                <TableHead className="hidden sm:table-cell">Credential</TableHead>
                {canWrite && (
                  <TableHead className="text-right">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {upstreams.data.map((u) => (
                <TableRow key={u.id} className={u.enabled ? "" : "opacity-60"}>
                  <TableCell>
                    <div className="font-mono text-[13px] font-medium">{u.name}</div>
                    {!u.enabled && <Chip tone="neutral">Disabled</Chip>}
                  </TableCell>
                  <TableCell>
                    <KindChip value={u.kind} />
                  </TableCell>
                  <TableCell className="hidden max-w-64 truncate font-mono text-[12px] text-muted-foreground lg:table-cell">{u.base_url}</TableCell>
                  <TableCell className="hidden md:table-cell">
                    <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                      <StrategyChip value={u.strategy} />
                      {u.max_input_tokens ? `${formatNumber(u.max_input_tokens)} tokens` : "No budget"}
                    </div>
                  </TableCell>
                  <TableCell className="hidden text-[12.5px] text-muted-foreground sm:table-cell">
                    {u.has_api_key ? <span className="font-mono">{u.key_hint}</span> : "None"}
                  </TableCell>
                  {canWrite && (
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="subtle" size="icon-xs" aria-label={`Edit ${u.name}`} onClick={() => open(u)}>
                          <PencilIcon />
                        </Button>
                        <Button variant="subtle" size="icon-xs" aria-label={`Remove ${u.name}`} onClick={() => setTarget(u)}>
                          <Trash2Icon />
                        </Button>
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Surface>
      <UpstreamDialog upstream={editing} open={dialog} onOpenChange={setDialog} />
      <ConfirmDialog
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        title={`Remove ${target?.name ?? ""}?`}
        description="Proxy calls that name this upstream, and keys that default to it, will be refused until they use another one."
        confirmLabel="Remove upstream"
        pending={remove.isPending}
        onConfirm={() =>
          target &&
          remove.mutate(target.id, {
            onSuccess: () => {
              toast.success("Upstream removed.");
              setTarget(null);
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </>
  );
}
