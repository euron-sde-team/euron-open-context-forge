# ADR-0007: A local AWS emulator, provisioned by the same Terraform as production

- **Status:** Accepted
- **Date:** 2026-10-24

## Context

ContextForge uses S3 (job payloads and results, benchmark reports, optional run content),
KMS (sealing upstream credentials with an encryption context) and Secrets Manager.
Asking every contributor or evaluator for an AWS account before they can see the service
work is a steep on-ramp, and mocking each SDK call would test the mocks, not the system.
The sibling project TokenShield solved this already
([TokenShield ADR-0005](https://github.com/euron-sde-team/euron-open-tokenshield/blob/main/docs/architecture/adr/0005-local-aws-emulation.md)),
and ContextForge reuses its approach and its Terraform modules.

## Decision

Run **[Floci](https://github.com/floci-io/floci)** (`floci/floci:2.3.0`, MIT) as a Compose
service in the `compose.floci.yaml` overlay. Point the unmodified AWS SDK at it with
`AWS_ENDPOINT_URL`. A one-shot `hashicorp/terraform:1.16.6` container applies
`infra/terraform/envs/local-floci`, which uses the same `kms`, `storage` and `secrets`
modules as `aws-dev` and `aws-prod`, before the migrate, API and worker containers start.
Postgres and Redis, which Floci does not back, run as plain containers locally and map to
RDS and ElastiCache in the AWS environments.

## Consequences

**Good**
- Clone to a working stack with only Docker: `make up && make demo`.
- Application code has no emulator branches: everything is configuration
  (`AWS_ENDPOINT_URL`, `S3_FORCE_PATH_STYLE`, `KEY_MODE`, `STORAGE`).
- The Terraform runs on every local start, and the integration suite runs under every
  cache, key and storage backend against it (`make test-matrix`: Redis or none, local
  AES-GCM or KMS, local disk or S3).
- The full production environment is exercised too: `make tf-aws-on-floci` plans,
  applies, re-plans and destroys `aws-dev` against a throwaway Floci (port 4396), which
  catches plan-time bugs that `terraform validate` cannot see.

**Bad / caveats**
- Emulators prove API compatibility, not IAM. Least-privilege mistakes show up only on real
  AWS, which is what `aws-dev` is for.
- Floci does not persist every attribute, so a re-plan against it can show a few in-place
  updates that real AWS would not; additions and replacements are what the check rejects.
- The local Terraform state lives in a Docker volume; resetting the volumes resets the
  emulated resources.

## Alternatives considered

- **Real AWS for development.** Cost and friction for every contributor.
- **LocalStack.** Similar role; Floci matches the sibling Euron projects and is MIT.
- **Local-only backends with no AWS code path exercised locally.** The KMS and S3 code
  would then be tested only in production.
