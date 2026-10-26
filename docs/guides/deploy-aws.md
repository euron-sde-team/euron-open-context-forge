# Deploy to AWS

The Terraform in `infra/terraform` provisions a complete production deployment. The
maintainers develop and test against the local emulator; the AWS environments are kept
valid (`terraform validate`, tflint, checkov) on every change, and the whole `aws-dev`
environment is planned, applied, re-planned and destroyed against the emulator
(`make tf-aws-on-floci`). Nothing in this project is applied to a real AWS account by the
maintainers. This guide describes how to apply it in your own account.

## What gets created

| Module | Resources |
| --- | --- |
| `network` | VPC across two or three availability zones, public and private subnets, NAT, flow logs; KMS and Secrets Manager interface endpoints in `aws-prod` |
| `database` | RDS PostgreSQL 16 (encrypted with the CMK, private, automated backups). No extensions: ContextForge uses no vector database |
| `cache` | ElastiCache Valkey replication group with TLS, an auth token and `allkeys-lru` (every entry is recomputable). Redis is optional for ContextForge, but with several API replicas it shares the result cache, rate limits and the config version stamp |
| `storage` | Private, TLS-only payloads bucket (`<name_prefix>-payloads`) with SSE-KMS and a 30-day expiry, for job payloads and results, benchmark reports and stored run content |
| `kms` | Customer-managed key with yearly rotation. It encrypts the database, cache, logs, images and bucket, and seals upstream credentials |
| `secrets` | `<name_prefix>/app` (`SESSION_SECRET`, `API_KEY_PEPPER`, generated once) and `<name_prefix>/connections` (`DATABASE_URL`, `REDIS_URL`, kept in step with the database and cache) in Secrets Manager |
| `ecr` | Repositories for the `api` and `web` images (immutable tags, scan on push). The worker and one-off tasks reuse the api image |
| `service` | ECS Fargate cluster; `api`, `worker` and `web` services behind one ALB (with WAF); a `migrate` task definition for one-off commands. ARM64 by default |
| `observability` | CloudWatch log groups (api, worker, web, migrate), a dashboard and alarms (load balancer 5xx, API latency p95, unhealthy targets, CPU and memory per service, database, cache, and optionally budget misses) |

The ALB sends `/v1/*`, `/api/*`, `/healthz` and `/readyz` to the api, and everything else to
the dashboard. `/metrics` is served only to `metrics_allowed_cidrs` (404 at the edge
otherwise).

Upstream credentials are sealed with KMS `Encrypt` before they reach the database. The
api and worker task roles may call `Encrypt` and `Decrypt` only with the encryption
context key `contextforge:record` (bound to the upstream row), and may use the key for S3
only through the S3 service.

The environment sets `ENVIRONMENT=production`, `CONTEXTFORGE_CLOUD=aws`, `KEY_MODE=kms`,
`STORAGE=s3`, `PAYLOADS_BUCKET`, `KMS_KEY_ID`, `COOKIE_SECURE=true` and `CORS_ORIGINS`, so
the production boot guards pass. Add other non-secret settings (for example
`LLM_SUMMARIZER_URL`, `TOKENIZER_ALIASES`, `MODEL_PRICES`) through
`api_extra_environment` in `terraform.tfvars`.

## One command

From the repository root, once `terraform.tfvars` (and optionally `backend.tf`) exist in the
environment folder:

```bash
make aws-deploy ENV=aws-dev TAG=0.1.0
CONTEXTFORGE_OWNER_PASSWORD='<strong password>' make aws-admin ENV=aws-dev EMAIL=you@example.com
```

`make aws-deploy` (`scripts/aws-deploy.sh`) runs the five steps below in order and stops at
the first failure: registries, both images for `linux/arm64` (override with `PLATFORM`),
the full apply with `image_tag` set to `TAG`, migrations as a one-off ECS task
(`scripts/aws-run-task.sh`, which waits for the task and prints its logs and exit code),
then a wait until every service is stable. `make aws-migrate ENV=...` reruns only the
migrations. The steps by hand:

## Steps

```bash
cd infra/terraform/envs/aws-dev        # or aws-prod
cp terraform.tfvars.example terraform.tfvars      # set region, name_prefix, hostname, certificate, zone, image_tag
cp backend.tf.example backend.tf                   # recommended: S3 state with locking
terraform init

# 1. Registries first, so there is somewhere to push images.
terraform apply -target=module.ecr

# 2. Build and push both images for linux/arm64 with the tag set in terraform.tfvars (image_tag).
aws ecr get-login-password | docker login --username AWS --password-stdin <registry>
docker build --platform linux/arm64 -f ../../../../infra/docker/api.Dockerfile -t <api repo>:0.1.0 ../../../../apps/api
docker build --platform linux/arm64 -f ../../../../infra/docker/web.Dockerfile -t <web repo>:0.1.0 ../../../../apps/web
docker push <api repo>:0.1.0 && docker push <web repo>:0.1.0

# 3. Everything else.
terraform apply

# 4. Migrate, then create the first owner (one-off tasks, parameters in `terraform output run_task`).
aws ecs run-task --cluster <cluster> --task-definition <family> --launch-type FARGATE \
  --network-configuration 'awsvpcConfiguration={subnets=[...],securityGroups=[...]}'
aws ecs run-task ... --overrides '{"containerOverrides":[{"name":"migrate",
  "command":["create-owner","--email","you@example.com"],
  "environment":[{"name":"CONTEXTFORGE_OWNER_PASSWORD","value":"<strong password>"}]}]}'
```

The `migrate` task runs `contextforge migrate` by default; a command override runs any
other CLI command with the same image, network and secrets.

Then open `https://<hostname>`, sign in, add your upstreams (OpenAI-compatible APIs,
TokenShield or SmartRouter) on the Upstreams page, create service keys, and point your
applications at `https://<hostname>/v1`.

## Notes

- The API trusts `X-Forwarded-For` only from the VPC CIDR (`FORWARDED_ALLOW_IPS`), so the
  login throttle and audit log see the real client address behind the load balancer.
- Each API task runs one uvicorn process (`WEB_CONCURRENCY=1`) so `/metrics` and the
  in-process caches are exact; scale with `api_min_count`/`api_max_count`. The database
  pool per process (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) is sized so every task together
  stays under `db_max_connections`; change them together.
- Tasks reach the internet on HTTPS (443) only. An upstream or LLM summarizer on another
  port (plain `http://`, a self-hosted model server) needs an `upstream_egress` entry on
  the service module.
- The worker serves Prometheus metrics on port 9464 (`WORKER_METRICS_PORT`). Set
  `worker_metrics_cidrs` to your in-VPC Prometheus to open that port to it; by default the
  worker has no ingress at all.
- `name_prefix` is at most 24 characters, and the payloads bucket name derives from it, so
  make it globally unique (for example `acme-contextforge-dev`).
- Without `route53_zone_id`, create a CNAME for `hostname` to the `load_balancer_dns_name`
  output yourself.
- State contains generated secrets (database password, cache auth token, signing secrets):
  keep the state bucket private, versioned and encrypted.
- `aws-prod` differs from `aws-dev` in resilience and retention: three availability zones
  with a NAT gateway each (dev: two zones, one NAT), VPC interface endpoints, Multi-AZ RDS
  with more storage and 14 days of backups (dev: 3), a primary and replica cache, deletion
  protection, larger and more API and web tasks (2 to 8 API tasks; dev: 1 to 2), a 30-day
  KMS deletion window (dev: 7) and a year of log retention (dev: 14 days).
- `store_content` (default `false`) turns on `STORE_CONTENT`; `alarm_email` subscribes an
  address to the alarms; `budget_missed_threshold` enables the budget-miss alarm.
- Never run `seed-demo` against a real deployment (it refuses in production).
- For a cheaper trial, use [local against AWS](local-with-aws.md): local containers with a
  real KMS key and payloads bucket.
