variable "name_prefix" {
  description = "Prefix for every resource name. The bucket is <name_prefix>-payloads."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK for SSE-KMS. Null falls back to SSE-S3."
  type        = string
  default     = null
}

variable "enforce_tls" {
  description = "Deny any request not made over TLS. Disable only for an emulator that speaks plain HTTP."
  type        = bool
  default     = true
}

variable "expiration_days" {
  description = "Days a job payload, job result or stored run content object is kept before S3 deletes it."
  type        = number
  default     = 30
  validation {
    condition     = var.expiration_days >= 1
    error_message = "expiration_days must be at least 1."
  }
}

variable "cors_origins" {
  description = "Browser origins allowed to GET objects with JavaScript (the dashboard URL). Empty = no CORS configuration."
  type        = list(string)
  default     = []
}

variable "force_destroy" {
  description = "Allow `terraform destroy` to delete a non-empty bucket. Never in production."
  type        = bool
  default     = false
}

variable "report_expiration_days" {
  description = "Days a benchmark report (synthetic data only) is kept before S3 deletes it."
  type        = number
  default     = 365
  validation {
    condition     = var.report_expiration_days >= 1
    error_message = "report_expiration_days must be at least 1."
  }
}
