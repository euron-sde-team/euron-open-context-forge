/**
 * Named aliases over the generated OpenAPI types (`pnpm gen:api`). Nothing here is
 * hand-written: every shape comes from `schema.d.ts`, which is generated from
 * docs/api/openapi.yaml.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type User = S["UserOut"];
export type UserCreate = S["UserCreate"];
export type UserUpdate = S["UserUpdate"];
export type Session = S["SessionOut"];
export type ApiKey = S["KeyOut"];
export type ApiKeyCreated = S["KeyCreated"];
export type ApiKeyIn = S["KeyIn"];
export type ApiKeyUpdate = S["KeyUpdate"];
export type Upstream = S["UpstreamOut"];
export type UpstreamIn = S["UpstreamIn"];
export type UpstreamUpdate = S["UpstreamUpdate"];
export type Profile = S["ProfileOut"];
export type ProfileIn = S["ProfileIn"];
export type Weights = S["Weights"];
export type Run = S["RunOut"];
export type RunDetail = S["RunDetail"];
export type RunPage = S["Page_RunOut_"];
export type Overview = S["Overview"];
export type Point = S["Point"];
export type Breakdown = S["Breakdown"];
export type Job = S["JobOut"];
export type BenchmarkRun = S["BenchmarkRunOut"];
export type BenchmarkRunDetail = S["BenchmarkRunDetail"];
export type DatasetCase = S["DatasetCase"];
export type Sample = S["Sample"];
export type OptimizeRequest = S["OptimizeRequest"];
export type OptimizeOptions = S["OptimizeOptions"];
export type OptimizeResponse = S["OptimizeResponse"];
export type ChatMessage = S["Message"];
export type ContextDocument = S["Document"];
export type TraceStep = S["TraceStep"];
export type Allocation = S["Allocation"];
export type CitationEntry = S["CitationEntry"];
export type OptimizeWarning = S["OptimizeWarning"];
export type AuditEntry = S["AuditOut"];
export type AuditPage = S["Page_AuditOut_"];
export type SystemInfo = S["SystemInfo"];

export type Role = NonNullable<UserCreate["role"]>;
export type Strategy = NonNullable<OptimizeOptions["strategy"]>;
export type Workload = NonNullable<OptimizeOptions["workload"]>;
export type UpstreamKind = NonNullable<UpstreamIn["kind"]>;
