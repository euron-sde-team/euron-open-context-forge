"use client";

import { ListChecksIcon } from "lucide-react";
import Link from "next/link";

import { CodeBlock } from "@/components/code-block";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { JobChip } from "@/components/status-chip";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Job } from "@/lib/api/types";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/format";

import { useJobs } from "../api";

const EXAMPLE = [
  "# Large inputs: submit, then poll",
  'curl -X POST $CONTEXTFORGE/v1/context/jobs -H "Authorization: Bearer cfk_..." \\',
  '  -H "Content-Type: application/json" -d @big-trace.json',
  '# => {"id": "...", "status": "queued", "poll": "/v1/context/jobs/<id>"}',
  'curl $CONTEXTFORGE/v1/context/jobs/<id> -H "Authorization: Bearer cfk_..."',
].join("\n");

/** What happened to a job, in words that match its status. */
function JobOutcome({ job }: { job: Job }) {
  const message = (job.error as { message?: string } | null)?.message;
  if (job.run_id)
    return (
      <Link href={`/runs?run=${job.run_id}`} className="text-primary hover:underline">
        Run {job.run_id}
      </Link>
    );
  if (job.status === "failed") return <span className="text-danger">{message ?? "Failed"}</span>;
  if (job.status === "running") return <span className="text-muted-foreground">Optimizing (attempt {job.attempts})</span>;
  if (job.status === "succeeded") return <span className="text-muted-foreground">Done; the run was not recorded</span>;
  // queued: a first try, or a retry after a failed attempt
  return message ? (
    <span className="text-warning">Retrying: {message}</span>
  ) : (
    <span className="text-faint">Waiting for a worker</span>
  );
}

export function JobsScreen() {
  const jobs = useJobs();
  return (
    <>
      <PageHeader
        title="Jobs"
        description="Background optimizations for inputs too large to hold a request open. Payloads and results live in object storage, never in the database."
      />
      <Surface>
        {jobs.isError && !jobs.data ? (
          <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
        ) : !jobs.data ? (
          <div className="p-4">
            <TableSkeleton rows={6} cols={5} />
          </div>
        ) : jobs.data.length === 0 ? (
          <EmptyState
            icon={ListChecksIcon}
            title="No background jobs yet"
            description={
              <>
                POST the same body as /v1/context/optimize to /v1/context/jobs; a worker claims it and the result is kept for you to
                fetch. Small inputs are faster through the <Link href="/playground" className="text-primary hover:underline">playground</Link> or the
                API directly.
              </>
            }
            action={<CodeBlock samples={[{ id: "curl", label: "curl", code: EXAMPLE }]} className="max-w-xl text-left" />}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Model</TableHead>
                <TableHead className="hidden sm:table-cell text-right">Payload</TableHead>
                <TableHead className="hidden lg:table-cell">Created</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.data.map((j) => (
                <TableRow key={j.id}>
                  <TableCell className="font-mono text-[12px]">{j.id.slice(0, 8)}</TableCell>
                  <TableCell>
                    <JobChip value={j.status} />
                  </TableCell>
                  <TableCell className="hidden font-mono text-[12px] md:table-cell">{j.model}</TableCell>
                  <TableCell className="hidden text-right text-muted-foreground tabular sm:table-cell">{formatBytes(j.payload_bytes)}</TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell" title={formatDateTime(j.created_at)}>
                    {formatRelative(j.created_at)}
                  </TableCell>
                  <TableCell className="text-[12.5px]">
                    <JobOutcome job={j} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Surface>
    </>
  );
}
