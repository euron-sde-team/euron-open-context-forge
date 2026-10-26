# `storage` module

One private S3 bucket, `<name_prefix>-payloads`, for background job payloads and results, benchmark reports and stored run content. Objects are written with SSE-KMS and expire on a schedule.

- Public access blocked, bucket-owner-enforced ownership, TLS-only bucket policy (`aws:SecureTransport`).
- Default encryption SSE-KMS with the CMK (bucket key on), SSE-S3 when no key is given.
- Lifecycle: job payloads and results (`jobs/`) and stored run content (`runs/`) expire after `expiration_days` (30 by default), benchmark reports (`benchmarks/`) after `report_expiration_days` (365), incomplete multipart uploads abort after a day. Objects are short-lived job payloads, job results, benchmark reports and (with STORE_CONTENT) run content; an expired job result answers 410, so the bucket is not versioned.
- Optional CORS (`cors_origins`), only for JavaScript fetches from the dashboard.

Applied in `local-floci` as `contextforge-local-payloads` with `enforce_tls = false` (the emulator speaks plain HTTP) and `force_destroy = true`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. The bucket is `<name_prefix>-payloads`. | `string` | required |
| `kms_key_arn` | CMK for SSE-KMS. Null falls back to SSE-S3. | `string` | `null` |
| `enforce_tls` | Deny any request not made over TLS. | `bool` | `true` |
| `expiration_days` | Days a job payload, job result or stored run content object is kept. | `number` | `30` |
| `report_expiration_days` | Days a benchmark report is kept. | `number` | `365` |
| `cors_origins` | Browser origins allowed to GET objects with JavaScript. Empty = no CORS. | `list(string)` | `[]` |
| `force_destroy` | Allow destroying a non-empty bucket. Never in production. | `bool` | `false` |

## Outputs

| Name | Description |
|---|---|
| `bucket_name` | Payloads bucket name (`PAYLOADS_BUCKET`). |
| `bucket_arn` | Payloads bucket ARN, for IAM policies. |
