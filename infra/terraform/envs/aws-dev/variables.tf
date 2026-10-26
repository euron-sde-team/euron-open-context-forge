variable "region" {
  description = "AWS region."
  type        = string
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"
}

variable "extra_tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}

variable "name_prefix" {
  description = "Prefix for every resource name (at most 24 characters); the payloads bucket name derives from it, so make it globally unique (e.g. \"acme-contextforge-dev\")."
  type        = string
}

variable "hostname" {
  description = "Public host name of the deployment, e.g. contextforge-dev.example.com."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate in the same region covering hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the hostname alias record. Null: create the CNAME yourself (load_balancer_dns_name output)."
  type        = string
  default     = null
}

variable "image_tag" {
  description = "Image tag to deploy (the git commit or a release)."
  type        = string
}

variable "alarm_email" {
  description = "Alarm notification address."
  type        = string
  default     = null
}

variable "api_extra_environment" {
  description = "Extra api/worker environment (e.g. AUTH_REQUIRED, DEFAULT_UPSTREAM, LLM_SUMMARIZER_URL). Never secrets."
  type        = map(string)
  default     = {}
}

variable "store_content" {
  description = "Keep run inputs and outputs in S3 for inspection (STORE_CONTENT). Off: stats only."
  type        = bool
  default     = false
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.small"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to scrape /metrics through the load balancer."
  type        = list(string)
  default     = []
}

variable "budget_missed_threshold" {
  description = "Budget misses per 5 minutes that raise an alarm. Null: no alarm."
  type        = number
  default     = null
}

variable "worker_metrics_cidrs" {
  description = "In-VPC Prometheus CIDRs allowed to scrape the worker's /metrics on port 9464. Empty: no worker ingress."
  type        = list(string)
  default     = []
}
