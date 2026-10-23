"use client";

import { BookOpenIcon, CableIcon, ExternalLinkIcon, LibraryIcon, RouteIcon, ShieldIcon, TerminalIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { CodeBlock } from "@/components/code-block";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { useUpstreams } from "@/features/upstreams/api";
import { librarySnippet, proxySnippet, restSnippet, smartRouterSnippet, tokenShieldSnippet } from "@/lib/snippets";

function Way({ icon: Icon, title, body, children }: { icon: typeof LibraryIcon; title: string; body: string; children: React.ReactNode }) {
  return (
    <Surface className="flex flex-col">
      <div className="flex items-start gap-3 px-5 pt-5 pb-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
          <Icon className="size-4" />
        </span>
        <div>
          <h2 className="text-[14px] font-semibold">{title}</h2>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{body}</p>
        </div>
      </div>
      <div className="mt-auto px-5 pb-5">{children}</div>
    </Surface>
  );
}

export function IntegrationsScreen() {
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => setOrigin(window.location.origin), []);
  const upstreams = useUpstreams();
  const kinds = new Set((upstreams.data ?? []).map((u) => u.kind));

  return (
    <>
      <PageHeader
        title="Integrations"
        description="Three ways in, and two optional partners from the Euron AI efficiency stack. Nothing here is required: the engine runs on its own."
      />
      <div className="space-y-4">
        <div className="grid gap-4 xl:grid-cols-3">
          <Way icon={LibraryIcon} title="Python library" body="Import the engine. No server, no network, no model: deterministic, in process.">
            <CodeBlock samples={[{ id: "py", label: "Python", code: librarySnippet() }]} />
          </Way>
          <Way icon={TerminalIcon} title="REST API" body="POST messages and documents; get the optimized context, stats, warnings and a trace.">
            <CodeBlock samples={[{ id: "curl", label: "curl", code: restSnippet(origin, "cfk_...") }]} />
          </Way>
          <Way icon={CableIcon} title="OpenAI-compatible proxy" body="Change base_url. Every call is optimized, then forwarded to your upstream, streaming included.">
            <CodeBlock samples={[{ id: "sdk", label: "OpenAI SDK", code: proxySnippet(origin, "cfk_...") }]} />
          </Way>
        </div>
        <Surface>
          <SurfaceHeader
            title="The Euron AI efficiency stack"
            description="TokenShield controls what may be spent, SmartRouter picks the model, ContextForge decides how little context it needs"
          />
          <div className="grid gap-4 px-5 pb-5 lg:grid-cols-2">
            {[
              {
                icon: ShieldIcon,
                name: "TokenShield",
                kind: "tokenshield",
                body: "Put the optimized request under TokenShield's hard budgets. Its x-tokenshield-* headers pass through, its cost header is recorded on each run, and a 402 budget_exceeded comes back unchanged.",
                code: tokenShieldSnippet(origin),
                href: "https://github.com/euron-sde-team/euron-open-tokenshield",
              },
              {
                icon: RouteIcon,
                name: "SmartRouter",
                kind: "smartrouter",
                body: 'Send model="auto" and let SmartRouter pick the model after ContextForge shaped the context. Counts use a clearly marked estimate; the routed model and its cost are recorded.',
                code: smartRouterSnippet(origin),
                href: null,
              },
            ].map((p) => (
              <div key={p.name} className="flex flex-col rounded-xl bg-muted/60 p-4">
                <div className="flex items-center gap-2">
                  <p.icon className="size-4 text-primary" />
                  <h3 className="text-[14px] font-semibold">{p.name}</h3>
                  <Chip tone={kinds.has(p.kind) ? "success" : "neutral"} dot className="ml-auto">
                    {kinds.has(p.kind) ? "Configured" : "Not configured"}
                  </Chip>
                </div>
                <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{p.body}</p>
                <CodeBlock className="mt-3" samples={[{ id: p.kind, label: "Proxy", code: p.code }]} />
                <div className="mt-3 flex gap-2">
                  <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/upstreams" />}>
                    {kinds.has(p.kind) ? "Manage upstreams" : `Add a ${p.name} upstream`}
                  </Button>
                  {p.href && (
                    <Button size="sm" variant="subtle" nativeButton={false} render={<a href={p.href} target="_blank" rel="noreferrer" />}>
                      Project
                      <ExternalLinkIcon />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Surface>
        <Surface className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <BookOpenIcon className="size-4 text-primary" />
            The full contract, with every option and error code, is in the interactive API reference.
          </div>
          <Button size="sm" variant="outline" nativeButton={false} render={<a href={`${origin}/docs`} target="_blank" rel="noreferrer" />}>
            Open /docs
            <ExternalLinkIcon />
          </Button>
        </Surface>
      </div>
    </>
  );
}
