# `observability` module

CloudWatch for a deployment: the app log groups, alarms to one SNS topic and a dashboard.

- **Log groups** `/contextforge/<name_prefix>/{api,worker,web,migrate}`, KMS-encrypted, with retention. The `service` module writes to them (`log_group_names` output).
- **Alarms** (SNS, optional e-mail subscription):
  - 5xx from each load-balanced app and from the load balancer itself
  - api **p95** time to first byte (`api_p95_latency_seconds`; non-streaming completions include the upstream call)
  - unhealthy targets, CPU and memory per ECS service
  - database CPU, free storage, connections
  - cache memory per node (the cache evicts LRU entries, so pressure lowers the hit rate) and engine CPU
  - optional **budget misses**: a metric filter turns the api's JSON log lines matching `budget_missed_log_pattern` (default `{ $.event = "budget_not_met" }`) into `ContextForge/<name_prefix>/BudgetMissed`; set `budget_missed_threshold` to alarm on it
- **Dashboard** with requests and errors, api latency p50/p95/p99, per-service CPU/memory, budget misses, database and cache.

Prometheus `/metrics` on the api remains the detailed, per-project source; CloudWatch covers what an on-call engineer needs without a Prometheus server.

Not applied in `local-floci`: locally logs go to stdout and metrics to `/metrics`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `log_retention_days` | App log retention. | `number` | `30` |
| `logs_kms_key_arn` | CMK for the log groups. | `string` | `null` |
| `alarm_email` | Alarm e-mail subscription. | `string` | `null` |
| `alb_arn_suffix` | Load balancer ARN suffix. | `string` | required |
| `ecs_cluster_name` | ECS cluster name. | `string` | required |
| `lb_services` | Service module `services` (must contain `api`). | `map(object)` | required |
| `ecs_services` | Service module `service_names`. | `map(string)` | required |
| `db_instance_identifier` | RDS instance identifier. | `string` | required |
| `db_max_connections` | Connection ceiling for the alarm. | `number` | `200` |
| `cache_replication_group_id` | ElastiCache replication group id. | `string` | required |
| `cache_node_count` | Nodes in the replication group. | `number` | `1` |
| `target_5xx_threshold` | 5xx per 5 minutes that alarm. | `number` | `25` |
| `api_p95_latency_seconds` | api p95 alarm threshold in seconds. | `number` | `20` |
| `budget_missed_log_pattern` | Filter pattern for budget-miss log lines. | `string` | `{ $.event = "budget_not_met" }` |
| `budget_missed_threshold` | Budget misses per 5 minutes that alarm; null: no alarm. | `number` | `null` |

## Outputs

| Name | Description |
|---|---|
| `log_group_names` | Log group per app. |
| `alarm_topic_arn` | SNS topic receiving every alarm. |
| `dashboard_name` | CloudWatch dashboard. |
| `metrics_namespace` | Namespace of the log-derived metrics. |
