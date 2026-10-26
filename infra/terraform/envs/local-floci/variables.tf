variable "endpoint" {
  description = "Emulator endpoint. http://floci:4566 inside compose, http://localhost:4366 from the host."
  type        = string
  default     = "http://localhost:4366"
}

variable "name_prefix" {
  description = "Must match PAYLOADS_BUCKET (<name_prefix>-payloads) and KMS_KEY_ID (alias/<name_prefix>) in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "contextforge-local"
}

variable "cors_origins" {
  description = "Dashboard origins allowed to fetch payloads with JavaScript (none needed by default)."
  type        = list(string)
  default     = ["http://localhost:4310", "http://127.0.0.1:4310"]
}
